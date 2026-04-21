import logging
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient, PartitionKey
from src.config import Config

logger = logging.getLogger(__name__)

_client = None
_container = None


def _get_container():
    global _client, _container
    if _container is None:
        credential = DefaultAzureCredential()
        _client = CosmosClient(url=Config.COSMOS_ENDPOINT, credential=credential)
        db = _client.get_database_client(Config.COSMOS_DATABASE)
        _container = db.get_container_client(Config.COSMOS_CONTAINER)
    return _container


def save_item(item: dict) -> dict:
    """Save a found item to Cosmos DB."""
    container = _get_container()
    return container.create_item(body=item)


def get_recent_items(limit: int = None) -> list[dict]:
    """Get recently found items, newest first."""
    if limit is None:
        limit = Config.RECENT_ITEMS_LIMIT
    container = _get_container()

    query = (
        "SELECT c.id, c.category, c.item_name, c.description, c.color, c.colors, c.brand, "
        "c.size, c.condition, c.distinguishing_features, c.ocr_text, c.location_found, "
        "c.found_date, c.image_urls, c.thumb_urls, c.status, c.reported_by "
        f"FROM c ORDER BY c.found_date DESC OFFSET 0 LIMIT {int(limit)}"
    )

    items = list(
        container.query_items(
            query=query,
            enable_cross_partition_query=True,
        )
    )
    return items


def search_items(fields: dict, query_embedding: list[float] | None = None) -> list[dict]:
    """Hybrid search over items.

    If `query_embedding` is provided and container has a vector policy,
    candidates are ranked by VectorDistance + keyword overlap. Otherwise falls
    back to pure keyword search.

    Args:
        fields: dict with optional keys: category, item_name, color/colors, brand, size, keywords
        query_embedding: optional 1536-d embedding of the user's query text
    """
    container = _get_container()

    if query_embedding:
        return _hybrid_search(container, fields, query_embedding)
    return _keyword_search(container, fields)


def _hybrid_search(container, fields: dict, query_embedding: list[float]) -> list[dict]:
    """Vector top-K + keyword boost."""
    top_k = Config.VECTOR_SEARCH_TOP_K

    # Cosmos NoSQL vector query: use VectorDistance in ORDER BY.
    # Exclude the embedding from projection to keep payload small.
    query = (
        "SELECT TOP @top c.id, c.category, c.item_name, c.description, c.color, c.colors, "
        "c.brand, c.size, c.condition, c.distinguishing_features, c.ocr_text, "
        "c.location_found, c.found_date, c.image_urls, c.thumb_urls, c.status, c.reported_by, "
        "VectorDistance(c.embedding, @qv) AS similarity "
        "FROM c "
        "WHERE IS_DEFINED(c.embedding) "
        "ORDER BY VectorDistance(c.embedding, @qv)"
    )
    params = [
        {"name": "@top", "value": top_k},
        {"name": "@qv", "value": query_embedding},
    ]

    try:
        candidates = list(
            container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
    except Exception:
        logger.exception("Vector query failed; falling back to keyword search")
        return _keyword_search(container, fields)

    # Drop very low similarity matches, but if NOTHING clears the floor we
    # still want to return the top vector neighbors (with a softer floor) and
    # let the relative cutoff handle pruning. Falling back to pure keyword
    # search here causes generic queries (e.g. "alcohol") to return every
    # item in the matching category.
    min_sim = Config.HYBRID_MIN_SIMILARITY
    strong = [c for c in candidates if c.get("similarity", 0) >= min_sim]
    if strong:
        # Also keep close vector neighbors within 0.15 of the strongest match.
        # This rescues genuine matches like iPhone (0.34) when the literal
        # keyword match (Smartphone, 0.48) sits just above the hard floor.
        top_sim = strong[0].get("similarity", 0) or 0
        neighbor_floor = max(0.20, top_sim - 0.15)
        candidates = [
            c for c in candidates
            if (c.get("similarity", 0) or 0) >= neighbor_floor
        ]
        had_strong = True
    else:
        soft_floor = max(0.20, min_sim - 0.15)
        candidates = [c for c in candidates if c.get("similarity", 0) >= soft_floor]
        had_strong = False

    # Add keyword score on top of vector similarity.
    for c in candidates:
        c["_hybrid_score"] = c.get("similarity", 0) * 10 + _keyword_score(c, fields)

    candidates.sort(key=lambda x: x["_hybrid_score"], reverse=True)

    # Relative cutoff. Three regimes:
    #   - Strong signal (top hybrid >= 10): clear winner with literal keyword
    #     evidence (brand/OCR hit), so keep candidates within 70% of top.
    #   - Strong vector match but weak keywords (had_strong True): keep
    #     neighbors within 0.15 similarity of the top match. Surfaces close
    #     semantic matches like iPhone (0.34) when literal Smartphone (0.48)
    #     is the top neighbor.
    #   - No strong vector match (had_strong False): apply tight similarity
    #     cutoff (95% of top similarity) to stop generic queries like
    #     "alcohol" from dragging in every neighbor in the same broad category.
    if candidates:
        top = candidates[0]["_hybrid_score"]
        top_sim = candidates[0].get("similarity", 0) or 0
        if top >= 10:
            # Strong keyword regime: keep within 70% of top hybrid OR within
            # 0.15 sim of top vector match. The OR rescues close semantic
            # neighbours (e.g. Coca-Cola for "soft drink" when Schweppes ran
            # away with the keyword bonus because "soda" is in its name).
            sim_floor = max(0.20, top_sim - 0.15)
            hyb_floor = top * 0.7
            candidates = [
                c for c in candidates
                if c["_hybrid_score"] >= hyb_floor
                or (c.get("similarity", 0) or 0) >= sim_floor
            ]
        elif had_strong and top_sim > 0:
            sim_floor = max(0.20, top_sim - 0.15)
            candidates = [
                c for c in candidates
                if (c.get("similarity", 0) or 0) >= sim_floor
            ]
        elif top_sim > 0:
            candidates = [
                c for c in candidates
                if (c.get("similarity", 0) or 0) >= top_sim * 0.95
            ]

    # If none passed, return empty rather than dumping the whole keyword-matched
    # universe (which floods generic queries with noise).
    if not candidates:
        return []

    return candidates


def _keyword_search(container, fields: dict) -> list[dict]:
    """Pure keyword search (fallback when no embeddings available)."""
    or_conditions = []
    params = []

    if fields.get("category"):
        or_conditions.append("c.category = @category")
        params.append({"name": "@category", "value": fields["category"]})

    if fields.get("color"):
        or_conditions.append("CONTAINS(LOWER(c.color), @color)")
        params.append({"name": "@color", "value": fields["color"].lower()})

    if fields.get("brand") and fields["brand"].lower() not in ("unknown", "null", "none"):
        or_conditions.append("CONTAINS(LOWER(c.brand), @brand)")
        params.append({"name": "@brand", "value": fields["brand"].lower()})

    if fields.get("item_name"):
        or_conditions.append("CONTAINS(LOWER(c.item_name), @item_name)")
        params.append({"name": "@item_name", "value": fields["item_name"].lower()})

    if fields.get("size"):
        or_conditions.append("c.size = @size")
        params.append({"name": "@size", "value": fields["size"]})

    keywords = fields.get("keywords", [])
    for i, kw in enumerate(keywords[:5]):
        param_name = f"@kw{i}"
        or_conditions.append(
            f"(CONTAINS(LOWER(c.description), {param_name}) "
            f"OR CONTAINS(LOWER(c.item_name), {param_name}) "
            f"OR CONTAINS(LOWER(c.distinguishing_features), {param_name}) "
            f"OR CONTAINS(LOWER(c.ocr_text ?? ''), {param_name}))"
        )
        params.append({"name": param_name, "value": kw.lower()})

    where_clause = " OR ".join(or_conditions) if or_conditions else "1=1"
    # Exclude embedding to keep payload small.
    query = (
        "SELECT c.id, c.category, c.item_name, c.description, c.color, c.colors, c.brand, "
        "c.size, c.condition, c.distinguishing_features, c.ocr_text, c.location_found, "
        "c.found_date, c.image_urls, c.thumb_urls, c.status, c.reported_by "
        f"FROM c WHERE {where_clause} ORDER BY c.found_date DESC OFFSET 0 LIMIT 50"
    )

    items = list(
        container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        )
    )

    if or_conditions and items:
        items = _rank_results(items, fields)

    return items


def _keyword_score(item: dict, fields: dict) -> int:
    """Compute keyword-based score for hybrid ranking.

    Brand and OCR matches are weighted heavily because they represent literal
    evidence on the item itself (e.g. visible 'TUMI' label) and are usually
    much stronger signals than semantic neighbors.
    """
    s = 0
    if fields.get("category") and item.get("category") == fields["category"]:
        s += 3
    if fields.get("color") and fields["color"].lower() in (item.get("color") or "").lower():
        s += 2
    if fields.get("item_name") and fields["item_name"].lower() in (item.get("item_name") or "").lower():
        s += 4
    if fields.get("brand") and fields.get("brand").lower() not in ("unknown", "null", "none"):
        brand_q = fields["brand"].lower()
        if brand_q in (item.get("brand") or "").lower():
            s += 10  # strong literal brand match
        elif brand_q in (item.get("ocr_text") or "").lower():
            s += 8  # brand visible in OCR but not parsed as brand field
    if fields.get("size") and item.get("size") == fields["size"]:
        s += 1
    for kw in fields.get("keywords", [])[:5]:
        kw_l = kw.lower()
        if len(kw_l) < 3:
            continue
        desc = (item.get("description") or "").lower()
        name = (item.get("item_name") or "").lower()
        features = (item.get("distinguishing_features") or "").lower()
        ocr = (item.get("ocr_text") or "").lower()
        brand = (item.get("brand") or "").lower()
        if kw_l in ocr or kw_l in brand:
            s += 4  # literal text on the item is strong evidence
        elif kw_l in name:
            s += 2
        elif kw_l in desc or kw_l in features:
            s += 1
    return s


def _rank_results(items: list[dict], fields: dict) -> list[dict]:
    """Rank items by how many search fields match, then drop low-relevance ones."""
    scored = []
    for item in items:
        s = 0
        if fields.get("category") and item.get("category") == fields["category"]:
            s += 3
        if fields.get("color") and fields["color"].lower() in (item.get("color") or "").lower():
            s += 2
        if fields.get("item_name") and fields["item_name"].lower() in (item.get("item_name") or "").lower():
            s += 4
        if fields.get("brand") and fields.get("brand").lower() not in ("unknown", "null", "none"):
            if fields["brand"].lower() in (item.get("brand") or "").lower():
                s += 3
        if fields.get("size") and item.get("size") == fields["size"]:
            s += 1
        for kw in fields.get("keywords", [])[:5]:
            kw_l = kw.lower()
            desc = (item.get("description") or "").lower()
            name = (item.get("item_name") or "").lower()
            features = (item.get("distinguishing_features") or "").lower()
            if kw_l in name:
                s += 2
            elif kw_l in desc or kw_l in features:
                s += 1
        scored.append((s, item))

    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        return []

    # Keep only items with score >= 30% of the top score (minimum 2)
    top_score = scored[0][0]
    threshold = max(2, top_score * 0.3)
    return [item for score, item in scored if score >= threshold]

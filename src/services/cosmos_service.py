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

    # Drop very low similarity matches
    min_sim = Config.HYBRID_MIN_SIMILARITY
    candidates = [c for c in candidates if c.get("similarity", 0) >= min_sim]

    # Add keyword score on top of vector similarity.
    for c in candidates:
        c["_hybrid_score"] = c.get("similarity", 0) * 10 + _keyword_score(c, fields)

    candidates.sort(key=lambda x: x["_hybrid_score"], reverse=True)

    # If none passed the similarity bar, fall back to keyword search.
    if not candidates:
        return _keyword_search(container, fields)

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
    """Compute keyword-based score for hybrid ranking (re-used from _rank_results)."""
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
        ocr = (item.get("ocr_text") or "").lower()
        if kw_l in name:
            s += 2
        elif kw_l in desc or kw_l in features or kw_l in ocr:
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

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

    query = f"SELECT * FROM c ORDER BY c.found_date DESC OFFSET 0 LIMIT {int(limit)}"

    items = list(
        container.query_items(
            query=query,
            enable_cross_partition_query=True,
        )
    )
    return items


def search_items(fields: dict) -> list[dict]:
    """Search items by structured metadata fields.

    Args:
        fields: dict with optional keys: category, item_name, color, brand, size, keywords
    """
    container = _get_container()

    # Build OR-based conditions so partial matches are returned
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

    # Keyword search across description, item_name, and distinguishing_features
    keywords = fields.get("keywords", [])
    for i, kw in enumerate(keywords[:5]):
        param_name = f"@kw{i}"
        or_conditions.append(
            f"(CONTAINS(LOWER(c.description), {param_name}) "
            f"OR CONTAINS(LOWER(c.item_name), {param_name}) "
            f"OR CONTAINS(LOWER(c.distinguishing_features), {param_name}))"
        )
        params.append({"name": param_name, "value": kw.lower()})

    where_clause = " OR ".join(or_conditions) if or_conditions else "1=1"
    query = f"SELECT * FROM c WHERE {where_clause} ORDER BY c.found_date DESC OFFSET 0 LIMIT 50"

    items = list(
        container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        )
    )

    # Rank results and filter out low-relevance matches
    if or_conditions and items:
        items = _rank_results(items, fields)

    return items


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

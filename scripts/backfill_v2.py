"""Backfill items_v2 from items with embeddings + new fields.

Reads each item from the old `items` container, computes an embedding from
item_name + description + features + ocr_text, backfills `colors` array /
`ocr_text` when missing, then upserts into `items_v2`.

Safe to re-run: upserts by id.
"""
import os
import sys
import logging

# Ensure we use the OLD container for read.
os.environ.setdefault("COSMOS_CONTAINER", "items")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient
from src.config import Config
from src.services import ai_service

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SOURCE = "items"
TARGET = "items_v2"

credential = DefaultAzureCredential()
client = CosmosClient(url=Config.COSMOS_ENDPOINT, credential=credential)
db = client.get_database_client(Config.COSMOS_DATABASE)
src_container = db.get_container_client(SOURCE)
dst_container = db.get_container_client(TARGET)


def backfill_colors(item: dict) -> None:
    if not item.get("colors"):
        color = (item.get("color") or "").strip()
        if color:
            item["colors"] = [c.strip() for c in color.split(",") if c.strip()][:3]
        else:
            item["colors"] = []


def ensure_ocr(item: dict) -> None:
    if "ocr_text" not in item:
        item["ocr_text"] = ""


def main():
    # Read all items from old container.
    items = list(src_container.query_items(
        query="SELECT * FROM c",
        enable_cross_partition_query=True,
    ))
    logger.info(f"Found {len(items)} items in {SOURCE}")

    migrated = 0
    skipped = 0
    for item in items:
        # Strip Cosmos metadata fields.
        for k in ("_rid", "_self", "_etag", "_attachments", "_ts"):
            item.pop(k, None)

        backfill_colors(item)
        ensure_ocr(item)

        # Generate embedding.
        search_text = ai_service.build_search_text(item)
        if not search_text:
            logger.warning(f"[skip] {item.get('id')}: empty search_text")
            skipped += 1
            continue
        try:
            item["embedding"] = ai_service.generate_embedding(search_text)
        except Exception as e:
            logger.error(f"[skip] {item.get('id')}: embedding failed ({e})")
            skipped += 1
            continue

        dst_container.upsert_item(body=item)
        migrated += 1
        logger.info(f"[ok]  {item.get('id')}  {item.get('item_name', '')[:40]}")

    logger.info(f"\nMigrated: {migrated}   Skipped: {skipped}")


if __name__ == "__main__":
    main()

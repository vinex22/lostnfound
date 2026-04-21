"""Re-extract metadata for existing items_v2 entries using the new prompt.

Downloads each item's full-size images from Blob Storage, runs
ai_service.extract_metadata() with the latest prompt, regenerates the embedding,
and upserts back to items_v2 — preserving id/found_date/location_found/
reported_by/image_urls/thumb_urls/status.

Safe to re-run.

Usage:
    .venv\\Scripts\\python.exe scripts\\reextract_v2.py [--ids id1,id2 | --only-empty-ocr]
"""
import os
import sys
import logging
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient
from src.config import Config
from src.services import ai_service, storage_service

logging.basicConfig(level=logging.INFO, format="%(message)s")
# Quiet azure SDK noise
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# Fields preserved from the existing doc — never overwritten by re-extraction.
PRESERVE_FIELDS = {
    "id", "found_date", "location_found", "reported_by",
    "image_urls", "thumb_urls", "status",
}

# Fields whose values come from the new extraction.
EXTRACT_FIELDS = {
    "category", "item_name", "description", "color", "colors", "brand",
    "size", "condition", "distinguishing_features", "ocr_text", "confidence",
}


def _blob_name_from_url(url: str) -> str:
    # image_urls are stored as "/images/<blob_name>"; strip the prefix.
    return url.removeprefix("/images/")


def _load_images_for_item(item: dict) -> list[tuple[bytes, str]]:
    images = []
    for url in item.get("image_urls", []):
        blob_name = _blob_name_from_url(url)
        try:
            data, ct = storage_service.download_image(blob_name)
            images.append((data, ct))
        except Exception as e:
            logger.warning(f"  ! failed to download {blob_name}: {e}")
    return images


def reextract_one(container, item: dict) -> str:
    images = _load_images_for_item(item)
    if not images:
        return "skip-no-images"

    metadata = ai_service.extract_metadata(images)

    if metadata.get("needs_more_images"):
        return "skip-needs-more-images"

    # Build new doc: keep preserved fields, replace extracted ones.
    new_item = {k: v for k, v in item.items() if k in PRESERVE_FIELDS or k.startswith("_")}
    # Strip Cosmos system metadata; upsert will re-issue.
    for k in ("_rid", "_self", "_etag", "_attachments", "_ts"):
        new_item.pop(k, None)

    for k in EXTRACT_FIELDS:
        if k in metadata:
            new_item[k] = metadata[k]

    # Defaults for any required field not produced by the model.
    new_item.setdefault("category", item.get("category", "other"))
    new_item.setdefault("item_name", item.get("item_name", "Unknown item"))
    new_item.setdefault("ocr_text", "")
    new_item.setdefault("colors", [])

    # Regenerate embedding from refreshed text.
    search_text = ai_service.build_search_text(new_item)
    if search_text:
        new_item["embedding"] = ai_service.generate_embedding(search_text)

    container.upsert_item(body=new_item)
    return "ok"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", help="Comma-separated item ids to re-extract")
    parser.add_argument("--only-empty-ocr", action="store_true",
                        help="Only re-extract items where ocr_text is empty")
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    client = CosmosClient(url=Config.COSMOS_ENDPOINT, credential=credential)
    db = client.get_database_client(Config.COSMOS_DATABASE)
    container = db.get_container_client("items_v2")

    if args.ids:
        ids = [s.strip() for s in args.ids.split(",") if s.strip()]
        items = []
        for i in ids:
            results = list(container.query_items(
                query="SELECT * FROM c WHERE c.id = @id",
                parameters=[{"name": "@id", "value": i}],
                enable_cross_partition_query=True,
            ))
            items.extend(results)
    else:
        items = list(container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True,
        ))
        if args.only_empty_ocr:
            items = [i for i in items if not (i.get("ocr_text") or "").strip()]

    logger.info(f"Re-extracting {len(items)} item(s)\n")

    counts = {"ok": 0, "skip-no-images": 0, "skip-needs-more-images": 0, "error": 0}
    for item in items:
        item_id = item.get("id")
        name = (item.get("item_name") or "")[:40]
        try:
            status = reextract_one(container, item)
            counts[status] = counts.get(status, 0) + 1
            logger.info(f"[{status:25}] {item_id}  {name}")
        except Exception as e:
            counts["error"] += 1
            logger.exception(f"[error                    ] {item_id}  {name}: {e}")

    logger.info(f"\nResults: {counts}")


if __name__ == "__main__":
    main()

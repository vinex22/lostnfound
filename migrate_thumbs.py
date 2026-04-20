"""Migration: Generate thumbnails for existing items and update Cosmos DB."""
import io
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from PIL import Image, ImageOps
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient
from azure.storage.blob import BlobServiceClient, ContentSettings

COSMOS_ENDPOINT = os.environ["COSMOS_ENDPOINT"]
STORAGE_URL = os.environ["AZURE_STORAGE_ACCOUNT_URL"]

cred = DefaultAzureCredential()

# Cosmos DB
cosmos = CosmosClient(COSMOS_ENDPOINT, cred)
db = cosmos.get_database_client("lostnfound")
container = db.get_container_client("items")

# Storage
blob_svc = BlobServiceClient(STORAGE_URL, cred)
blob_container = blob_svc.get_container_client("images")

items = list(container.query_items("SELECT * FROM c", enable_cross_partition_query=True))
print(f"Found {len(items)} items to migrate")

for item in items:
    if item.get("thumb_urls") and "--force" not in sys.argv:
        print(f"  SKIP {item['id'][:8]} — already has thumb_urls (use --force to regenerate)")
        continue

    thumb_urls = []
    for img_url in item.get("image_urls", []):
        # img_url is like /images/abc123/def456.jpg
        blob_name = img_url.replace("/images/", "", 1)

        # Download full image
        try:
            blob_client = blob_container.get_blob_client(blob_name)
            download = blob_client.download_blob()
            img_bytes = download.readall()
        except Exception as e:
            print(f"  ERROR downloading {blob_name}: {e}")
            continue

        # Generate thumbnail
        img = Image.open(io.BytesIO(img_bytes))
        img = ImageOps.exif_transpose(img)  # Fix rotation from phone cameras
        img.thumbnail((300, 300), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=70)
        thumb_bytes = buf.getvalue()

        # Upload thumbnail
        base = blob_name.rsplit(".", 1)[0]
        thumb_name = f"{base}_thumb.webp"
        blob_container.upload_blob(
            name=thumb_name,
            data=thumb_bytes,
            content_settings=ContentSettings(content_type="image/webp"),
            overwrite=True,
        )
        thumb_urls.append(f"/images/{thumb_name}")
        print(f"  Created thumb: {thumb_name} ({len(thumb_bytes)} bytes)")

    # Update Cosmos DB document
    item["thumb_urls"] = thumb_urls
    container.replace_item(item=item["id"], body=item)
    print(f"  Updated {item['id'][:8]} ({item['item_name']}) with {len(thumb_urls)} thumb(s)")

print("\nMigration complete!")

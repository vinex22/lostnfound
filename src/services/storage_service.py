import io
import uuid
import logging
from PIL import Image
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from src.config import Config

logger = logging.getLogger(__name__)

_blob_service = None
_container_client = None


def _get_container_client():
    global _blob_service, _container_client
    if _container_client is None:
        credential = DefaultAzureCredential()
        _blob_service = BlobServiceClient(
            account_url=Config.AZURE_STORAGE_ACCOUNT_URL,
            credential=credential,
        )
        _container_client = _blob_service.get_container_client(Config.STORAGE_CONTAINER)
    return _container_client


def _generate_thumbnail(image_bytes: bytes) -> bytes:
    """Resize image to 300px max and convert to WebP."""
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((300, 300), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=70)
    buf.seek(0)
    return buf.getvalue()


def upload_image(image_bytes: bytes, content_type: str = "image/jpeg", item_id: str = None) -> tuple[str, str]:
    """Upload an image + its thumbnail to Blob Storage.

    Returns:
        (full_blob_name, thumb_blob_name)
    """
    container = _get_container_client()

    ext = "jpg"
    if "png" in content_type:
        ext = "png"
    elif "webp" in content_type:
        ext = "webp"

    file_id = uuid.uuid4().hex
    prefix = item_id or uuid.uuid4().hex
    blob_name = f"{prefix}/{file_id}.{ext}"
    thumb_name = f"{prefix}/{file_id}_thumb.webp"

    # Upload full-size image
    container.upload_blob(
        name=blob_name,
        data=image_bytes,
        content_settings=ContentSettings(content_type=content_type),
        overwrite=True,
    )

    # Generate and upload thumbnail
    thumb_bytes = _generate_thumbnail(image_bytes)
    container.upload_blob(
        name=thumb_name,
        data=thumb_bytes,
        content_settings=ContentSettings(content_type="image/webp"),
        overwrite=True,
    )

    logger.info("Uploaded blob: %s + thumb: %s", blob_name, thumb_name)
    return blob_name, thumb_name


def download_image(blob_name: str) -> tuple[bytes, str]:
    """Download an image from Blob Storage.

    Returns:
        (image_bytes, content_type)
    """
    container = _get_container_client()
    blob_client = container.get_blob_client(blob_name)
    download = blob_client.download_blob()
    props = download.properties
    content_type = props.content_settings.content_type or "image/jpeg"
    return download.readall(), content_type

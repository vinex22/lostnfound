import uuid
import logging
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


def upload_image(image_bytes: bytes, content_type: str = "image/jpeg", item_id: str = None) -> str:
    """Upload an image to Blob Storage.

    Returns:
        The blob name (used to construct the proxy URL)
    """
    container = _get_container_client()

    ext = "jpg"
    if "png" in content_type:
        ext = "png"
    elif "webp" in content_type:
        ext = "webp"

    blob_name = f"{item_id or uuid.uuid4().hex}/{uuid.uuid4().hex}.{ext}"

    container.upload_blob(
        name=blob_name,
        data=image_bytes,
        content_settings=ContentSettings(content_type=content_type),
        overwrite=True,
    )

    logger.info("Uploaded blob: %s", blob_name)
    return blob_name


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

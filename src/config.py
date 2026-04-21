import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Azure AI / OpenAI
    AZURE_AI_SERVICES_ENDPOINT = os.environ.get("AZURE_AI_SERVICES_ENDPOINT")
    AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.environ.get(
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"
    )
    EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
    OPENAI_API_VERSION = os.environ.get("OPENAI_API_VERSION", "2024-12-01-preview")

    # Cosmos DB
    COSMOS_ENDPOINT = os.environ.get("COSMOS_ENDPOINT")
    COSMOS_DATABASE = os.environ.get("COSMOS_DATABASE", "lostnfound")
    COSMOS_CONTAINER = os.environ.get("COSMOS_CONTAINER", "items")

    # Storage
    AZURE_STORAGE_ACCOUNT_URL = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
    STORAGE_CONTAINER = os.environ.get("STORAGE_CONTAINER", "images")

    # App
    DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
    MAX_IMAGES = 3
    MAX_IMAGE_SIZE_MB = 10
    RECENT_ITEMS_LIMIT = 20

    # Search
    VECTOR_SEARCH_TOP_K = int(os.environ.get("VECTOR_SEARCH_TOP_K", "30"))
    HYBRID_MIN_SIMILARITY = float(os.environ.get("HYBRID_MIN_SIMILARITY", "0.35"))

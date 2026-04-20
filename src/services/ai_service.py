import json
import base64
import logging
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from src.config import Config

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(),
            "https://cognitiveservices.azure.com/.default",
        )
        _client = AzureOpenAI(
            azure_endpoint=Config.AZURE_AI_SERVICES_ENDPOINT,
            azure_ad_token_provider=token_provider,
            api_version=Config.OPENAI_API_VERSION,
        )
    return _client


METADATA_EXTRACTION_PROMPT = """You are an AI assistant for an airport Lost & Found system.
Analyze the image(s) and extract metadata about the item shown.

Return ONLY a valid JSON object (no markdown, no code blocks) with these fields:
{
  "category": "one of: electronics, clothing, bags, accessories, documents, food_drink, toys, sports, medical, jewelry, keys, other",
  "item_name": "specific name of the item (e.g. 'iPhone 15 Pro', 'Blue North Face Jacket')",
  "description": "detailed text description in English",
  "color": "primary color(s)",
  "brand": "brand if visible, else 'unknown'",
  "size": "small, medium, or large",
  "condition": "new, good, fair, or poor",
  "distinguishing_features": "any unique identifiers like stickers, scratches, labels, engravings",
  "confidence": "high, medium, or low",
  "needs_more_images": false
}

Set needs_more_images to true ONLY if the image is too blurry, dark, or ambiguous to identify the item."""


SEARCH_TEXT_PROMPT = """You are a search assistant for a Lost & Found database.
Convert the user's search query into structured fields. The user may write in any language — understand it and extract English values for querying.

IMPORTANT: Be generous with keywords — include synonyms, alternate spellings, and related terms to maximize recall.
For example, "phone" should also include keywords like "smartphone", "mobile", "cell phone".

Return ONLY a valid JSON object (no markdown):
{
  "category": "one of: electronics, clothing, bags, accessories, documents, food_drink, toys, sports, medical, jewelry, keys, other — pick the best match, or null if unclear",
  "item_name": "specific item name if mentioned, else null (keep it short, e.g. 'iphone', 'jacket')",
  "color": "color if mentioned, else null",
  "brand": "brand if mentioned, else null",
  "size": "small, medium, or large — only if mentioned, else null",
  "keywords": ["array", "of", "5-8", "search", "keywords", "including", "synonyms"],
  "user_language": "detected language code (en, hi, zh, ja, etc.)"
}"""


SEARCH_IMAGE_PROMPT = """You are an AI assistant for an airport Lost & Found system.
A passenger is looking for a lost item and has provided a photo of what it looks like (or a similar item).
Extract metadata to search the database.

Return ONLY a valid JSON object (no markdown):
{
  "category": "one of: electronics, clothing, bags, accessories, documents, food_drink, toys, sports, medical, jewelry, keys, other",
  "item_name": "what the item appears to be",
  "color": "primary color(s)",
  "brand": "brand if visible, else null",
  "size": "small, medium, or large",
  "keywords": ["array", "of", "search", "keywords"],
  "user_language": "en"
}"""


def _parse_json_response(text: str) -> dict:
    """Parse JSON from GPT response, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])
    return json.loads(text)


def _image_to_content(image_bytes: bytes, content_type: str = "image/jpeg") -> dict:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{content_type};base64,{b64}"},
    }


def extract_metadata(images: list[tuple[bytes, str]]) -> dict:
    """Extract item metadata from one or more images.

    Args:
        images: list of (image_bytes, content_type) tuples

    Returns:
        Extracted metadata dict
    """
    client = _get_client()

    content = [{"type": "text", "text": "Analyze this item:"}]
    for img_bytes, ct in images:
        content.append(_image_to_content(img_bytes, ct))

    response = client.chat.completions.create(
        model=Config.AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": METADATA_EXTRACTION_PROMPT},
            {"role": "user", "content": content},
        ],
        max_completion_tokens=800,
        temperature=0.1,
    )

    return _parse_json_response(response.choices[0].message.content)


def search_by_text(query: str) -> dict:
    """Convert a natural language search query to structured fields."""
    client = _get_client()

    response = client.chat.completions.create(
        model=Config.AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": SEARCH_TEXT_PROMPT},
            {"role": "user", "content": query},
        ],
        max_completion_tokens=400,
        temperature=0.1,
    )

    return _parse_json_response(response.choices[0].message.content)


def search_by_image(image_bytes: bytes, content_type: str = "image/jpeg") -> dict:
    """Extract search metadata from a photo of a lost item."""
    client = _get_client()

    content = [
        {"type": "text", "text": "I'm looking for this item I lost:"},
        _image_to_content(image_bytes, content_type),
    ]

    response = client.chat.completions.create(
        model=Config.AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": SEARCH_IMAGE_PROMPT},
            {"role": "user", "content": content},
        ],
        max_completion_tokens=400,
        temperature=0.1,
    )

    return _parse_json_response(response.choices[0].message.content)

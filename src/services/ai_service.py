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
The user may upload 1-3 photos of the SAME physical item from different angles or distances.
Consolidate evidence across ALL images and extract metadata for that single item.

CRITICAL RULES:
- Treat all images as views of ONE item. Do not describe them separately.
- Identify the SINGLE primary item in the foreground. Ignore background, surface, table, floor, hands, packaging, or other items.
- Do NOT mention setting, location, lighting, surroundings, or how the item is placed.
- If multiple items are visible, focus on the most prominent / centrally framed one.
- `description` must describe ONLY the item itself: what it is, shape, material, color details, visible text/logos on it, ports/buttons/straps, and visible wear or damage. Be detailed and specific — this text is used for search. Use evidence from ALL images (e.g. front + back + side).
- `distinguishing_features` must list marks, stickers, scratches, engravings, or labels that are ON the item itself. Use "none visible" if there are none.
- `colors` must be an ARRAY of the item's colors in order of visual prominence (primary first). Use common color names ("black", "navy blue", "silver", "tan"). 1-3 entries max.
- `ocr_text` must contain any readable text, numbers, logos, or serial numbers visible ON the item (brand names, model labels, engravings, printed text, stickers). Use "" if none visible. For documents/ID cards, include all readable text. Do NOT transcribe text from the background.
- Never invent details you cannot see (no guessing model numbers, owners, or origins).

Return ONLY a valid JSON object (no markdown, no code blocks) with these fields:
{
  "category": "one of: electronics, clothing, bags, accessories, documents, food_drink, toys, sports, medical, jewelry, keys, other",
  "item_name": "specific name of the item (e.g. 'iPhone 15 Pro', 'Blue North Face Jacket')",
  "description": "detailed description of the item only — consolidate evidence from all images",
  "colors": ["array", "of", "color", "names", "primary first"],
  "color": "primary color (for backward compatibility, should match colors[0])",
  "brand": "brand visible on the item, else 'unknown'",
  "size": "small, medium, or large",
  "condition": "new, good, fair, or poor",
  "distinguishing_features": "marks/stickers/scratches/engravings on the item, or 'none visible'",
  "ocr_text": "readable text/logos/serials visible on the item, or ''",
  "confidence": "high, medium, or low",
  "needs_more_images": false
}

Set needs_more_images to true ONLY if the image(s) are too blurry, dark, or ambiguous to identify the item."""


TWO_PASS_REFINE_PROMPT = """You previously extracted metadata for a lost item with LOW confidence.
Look again at the image(s) and focus carefully on fine details: visible text, brand logos, model numbers, small scratches, color nuances, material texture, and distinguishing marks.
Re-extract the same JSON schema but produce better, more specific values. If you still cannot be more specific, keep the existing value.
Return ONLY the JSON object (same schema), no markdown."""



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

    Runs a two-pass flow: if the first pass returns low confidence, a targeted
    refinement pass re-examines the image(s) for fine details.

    Args:
        images: list of (image_bytes, content_type) tuples

    Returns:
        Extracted metadata dict
    """
    client = _get_client()

    content = [{"type": "text", "text": "Analyze this item (consolidate across all provided images):"}]
    for img_bytes, ct in images:
        content.append(_image_to_content(img_bytes, ct))

    response = client.chat.completions.create(
        model=Config.AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": METADATA_EXTRACTION_PROMPT},
            {"role": "user", "content": content},
        ],
        max_completion_tokens=1000,
        temperature=0.1,
    )

    metadata = _parse_json_response(response.choices[0].message.content)

    # Two-pass: if low confidence and images are usable, refine.
    if metadata.get("confidence") == "low" and not metadata.get("needs_more_images"):
        try:
            logger.info("Low-confidence extraction — running refinement pass")
            refine_user = [
                {"type": "text", "text": f"Previous extraction (low confidence):\n{json.dumps(metadata)}"},
            ]
            for img_bytes, ct in images:
                refine_user.append(_image_to_content(img_bytes, ct))

            refine_resp = client.chat.completions.create(
                model=Config.AZURE_OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": TWO_PASS_REFINE_PROMPT},
                    {"role": "user", "content": refine_user},
                ],
                max_completion_tokens=1000,
                temperature=0.1,
            )
            refined = _parse_json_response(refine_resp.choices[0].message.content)
            # Only replace fields that got more specific (non-empty, non-default).
            for k, v in refined.items():
                if v and v not in ("unknown", "none visible", "", []):
                    metadata[k] = v
        except Exception:
            logger.exception("Refinement pass failed; using initial extraction")

    # Normalize: ensure `colors` array and `color` scalar are both present.
    if "colors" in metadata and isinstance(metadata["colors"], list) and metadata["colors"]:
        if not metadata.get("color"):
            metadata["color"] = metadata["colors"][0]
    elif metadata.get("color"):
        metadata["colors"] = [c.strip() for c in str(metadata["color"]).split(",") if c.strip()][:3]

    return metadata


def generate_embedding(text: str) -> list[float]:
    """Generate a text embedding for semantic search."""
    if not text or not text.strip():
        return []
    client = _get_client()
    resp = client.embeddings.create(
        model=Config.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        input=text[:8000],
    )
    return resp.data[0].embedding


def build_search_text(metadata: dict) -> str:
    """Build the canonical text used for embeddings from extracted metadata."""
    parts = [
        metadata.get("item_name") or "",
        metadata.get("category") or "",
        metadata.get("brand") or "",
        ", ".join(metadata.get("colors") or []) or metadata.get("color") or "",
        metadata.get("description") or "",
        metadata.get("distinguishing_features") or "",
        metadata.get("ocr_text") or "",
    ]
    return " | ".join(p for p in parts if p and p.lower() not in ("unknown", "none visible"))


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

    fields = _parse_json_response(response.choices[0].message.content)
    fields["query_text"] = query
    return fields


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

    fields = _parse_json_response(response.choices[0].message.content)
    fields["query_text"] = build_search_text(fields)
    return fields

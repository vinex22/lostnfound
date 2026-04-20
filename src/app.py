import os
import uuid
import logging
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify, Response, abort

# Configure Azure Monitor before anything else
if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor
    configure_azure_monitor(logger_name="lostnfound")

from src.config import Config
from src.services import ai_service, cosmos_service, storage_service

logging.basicConfig(level=logging.DEBUG if Config.DEBUG else logging.INFO)
logger = logging.getLogger("lostnfound")

# Suppress noisy Azure SDK HTTP logs (REDACTED headers every second from Live Metrics)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.monitor.opentelemetry").setLevel(logging.WARNING)

app = Flask(__name__)
app.config.from_object(Config)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/report")
def report():
    return render_template("report.html")


@app.route("/search")
def search():
    return render_template("search.html")


# ---------------------------------------------------------------------------
# API — Report
# ---------------------------------------------------------------------------

@app.route("/api/report", methods=["POST"])
def api_report():
    """Accept up to 3 images + location, extract metadata, store everything."""
    files = request.files.getlist("images")
    if not files or len(files) == 0:
        return jsonify({"error": "At least one image is required"}), 400
    if len(files) > Config.MAX_IMAGES:
        return jsonify({"error": f"Maximum {Config.MAX_IMAGES} images allowed"}), 400

    location = request.form.get("location", "").strip()
    reported_by = request.form.get("reported_by", "").strip()

    # Read image bytes
    images = []
    for f in files:
        img_bytes = f.read()
        ct = f.content_type or "image/jpeg"
        if len(img_bytes) > Config.MAX_IMAGE_SIZE_MB * 1024 * 1024:
            return jsonify({"error": f"Image exceeds {Config.MAX_IMAGE_SIZE_MB}MB limit"}), 400
        images.append((img_bytes, ct))

    # Extract metadata via GPT
    try:
        metadata = ai_service.extract_metadata(images)
    except Exception as e:
        logger.exception("Metadata extraction failed")
        return jsonify({"error": "Failed to analyze images", "detail": str(e)}), 500

    # Check if GPT wants more images
    if metadata.get("needs_more_images"):
        return jsonify({
            "needs_more_images": True,
            "partial_metadata": metadata,
            "message": "The image quality is insufficient. Please upload clearer photos.",
        }), 200

    # Upload images to Blob Storage
    item_id = uuid.uuid4().hex
    image_blob_names = []
    thumb_blob_names = []
    for img_bytes, ct in images:
        try:
            blob_name, thumb_name = storage_service.upload_image(img_bytes, ct, item_id=item_id)
            image_blob_names.append(blob_name)
            thumb_blob_names.append(thumb_name)
        except Exception as e:
            logger.exception("Image upload failed")
            return jsonify({"error": "Failed to upload image", "detail": str(e)}), 500

    # Build document
    item = {
        "id": item_id,
        "category": metadata.get("category", "other"),
        "item_name": metadata.get("item_name", "Unknown item"),
        "description": metadata.get("description", ""),
        "color": metadata.get("color", ""),
        "brand": metadata.get("brand", "unknown"),
        "size": metadata.get("size", "medium"),
        "condition": metadata.get("condition", "fair"),
        "distinguishing_features": metadata.get("distinguishing_features", ""),
        "location_found": location,
        "found_date": datetime.now(timezone.utc).isoformat(),
        "image_urls": [f"/images/{bn}" for bn in image_blob_names],
        "thumb_urls": [f"/images/{tn}" for tn in thumb_blob_names],
        "status": "unclaimed",
        "reported_by": reported_by,
    }

    # Save to Cosmos DB
    try:
        cosmos_service.save_item(item)
    except Exception as e:
        logger.exception("Cosmos DB save failed")
        return jsonify({"error": "Failed to save item", "detail": str(e)}), 500

    return jsonify({"success": True, "item": item}), 201


# ---------------------------------------------------------------------------
# API — Search
# ---------------------------------------------------------------------------

@app.route("/api/search/text", methods=["POST"])
def api_search_text():
    """Natural language text search."""
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Search query is required"}), 400

    try:
        fields = ai_service.search_by_text(query)
    except Exception as e:
        logger.exception("Search query analysis failed")
        return jsonify({"error": "Failed to analyze search query", "detail": str(e)}), 500

    try:
        items = cosmos_service.search_items(fields)
    except Exception as e:
        logger.exception("Cosmos DB search failed")
        return jsonify({"error": "Search failed", "detail": str(e)}), 500

    return jsonify({"items": items, "search_fields": fields})


@app.route("/api/search/image", methods=["POST"])
def api_search_image():
    """Camera/photo-based search."""
    f = request.files.get("image")
    if not f:
        return jsonify({"error": "An image is required"}), 400

    img_bytes = f.read()
    ct = f.content_type or "image/jpeg"

    if len(img_bytes) > Config.MAX_IMAGE_SIZE_MB * 1024 * 1024:
        return jsonify({"error": f"Image exceeds {Config.MAX_IMAGE_SIZE_MB}MB limit"}), 400

    try:
        fields = ai_service.search_by_image(img_bytes, ct)
    except Exception as e:
        logger.exception("Image search analysis failed")
        return jsonify({"error": "Failed to analyze image", "detail": str(e)}), 500

    try:
        items = cosmos_service.search_items(fields)
    except Exception as e:
        logger.exception("Cosmos DB search failed")
        return jsonify({"error": "Search failed", "detail": str(e)}), 500

    return jsonify({"items": items, "search_fields": fields})


# ---------------------------------------------------------------------------
# API — Recent Items Feed
# ---------------------------------------------------------------------------

@app.route("/api/items/recent")
def api_recent_items():
    try:
        items = cosmos_service.get_recent_items()
    except Exception as e:
        logger.exception("Failed to fetch recent items")
        return jsonify({"error": "Failed to load items", "detail": str(e)}), 500
    return jsonify({"items": items})


# ---------------------------------------------------------------------------
# Image Proxy (Storage is behind PE, no public access)
# ---------------------------------------------------------------------------

@app.route("/images/<path:blob_name>")
def serve_image(blob_name):
    try:
        data, content_type = storage_service.download_image(blob_name)
        return Response(data, mimetype=content_type,
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception:
        abort(404)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=Config.DEBUG)

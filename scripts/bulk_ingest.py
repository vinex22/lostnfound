"""Bulk-ingest random lost-item images from public URLs into the live app.

Downloads images from a curated list of public URLs (Wikimedia Commons,
Picsum, etc.) and POSTs each to the running web app's /api/report endpoint.
The app handles GPT extraction, blob upload, and Cosmos insert exactly as if
a user reported the item.

Usage:
    .venv\\Scripts\\python.exe scripts\\bulk_ingest.py            # ingest all
    .venv\\Scripts\\python.exe scripts\\bulk_ingest.py --limit 5   # first 5
    .venv\\Scripts\\python.exe scripts\\bulk_ingest.py --url http://localhost:5000  # local

Notes:
    - Each item gets a random fake "found at <gate>" location.
    - Skips entries where the download fails (404, etc.).
    - 1-2s sleep between items to avoid hammering GPT-5.4.
"""
from __future__ import annotations
import argparse
import io
import random
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import requests

# ---------------------------------------------------------------------------
# Curated catalog of (label, topic). LoremFlickr serves a real Flickr image
# matching the topic at the given size; `lock` makes it deterministic so we
# don't re-ingest the same picture if the script is re-run.
# Pattern: https://loremflickr.com/640/480/<topic>?lock=<n>
# ---------------------------------------------------------------------------
_RAW: list[tuple[str, str, int]] = [
    # (label, loremflickr topic, lock seed) — lock keeps the image stable across runs
    # --- electronics ---
    ("Sony headphones",            "headphones",       101),
    ("Kindle e-reader",            "kindle",           102),
    ("Nintendo Switch",            "nintendo,switch",  103),
    ("Canon DSLR camera",          "dslr,camera",      104),
    ("GoPro action camera",        "gopro",            105),
    ("USB power bank",             "powerbank",        106),
    ("MacBook laptop",             "laptop,macbook",   107),
    ("iPad tablet",                "ipad,tablet",      108),
    ("Bluetooth speaker",          "bluetooth,speaker",109),
    ("Smartphone Android",         "smartphone,android",110),
    ("Wireless mouse",             "wireless,mouse",   111),
    ("Mechanical keyboard",        "mechanical,keyboard",112),
    ("USB-C cable",                "usb,cable",        113),
    ("Apple Watch",                "smartwatch",       114),
    ("Drone quadcopter",           "drone,quadcopter", 115),
    ("Smart fitness band",         "fitness,band",     116),
    ("HDMI adapter",               "hdmi,adapter",     117),
    ("VR headset",                 "vr,headset",       118),

    # --- bags / luggage ---
    ("Roller suitcase",            "suitcase",         150),
    ("Leather briefcase",          "briefcase",        151),
    ("Tote bag",                   "totebag",          152),
    ("Hiking backpack",            "hiking,backpack",  153),
    ("Duffel bag",                 "duffel,bag",       154),
    ("Laptop sleeve",              "laptop,sleeve",    155),
    ("Crossbody handbag",          "handbag",          156),
    ("Camera bag",                 "camera,bag",       157),
    ("Gym sports bag",             "gym,bag",          158),
    ("Fanny pack",                 "fannypack,bumbag", 159),

    # --- clothing / accessories ---
    ("Wool scarf",                 "scarf",            200),
    ("Leather wallet",             "wallet",           201),
    ("Sunglasses",                 "sunglasses",       202),
    ("Baseball cap",               "cap,hat",          203),
    ("Knitted gloves",             "gloves",           204),
    ("Wristwatch",                 "wristwatch",       205),
    ("Silk tie",                   "necktie,suit",     206),
    ("Black umbrella",             "umbrella",         207),
    ("Rain jacket",                "raincoat",         208),
    ("Wool beanie",                "beanie,hat",       209),
    ("Pair of sneakers",           "sneakers",         210),
    ("Leather belt",               "belt,leather",     211),
    ("Sandals",                    "sandals",          212),
    ("Hoodie",                     "hoodie",           213),
    ("Reading glasses",            "reading,glasses",  214),

    # --- books / documents ---
    ("Hardcover book",             "book",             250),
    ("Spiral notebook",            "notebook",         251),
    ("Passport",                   "passport",         252),
    ("Boarding pass",              "boarding,pass",    253),
    ("Business cards",             "business,cards",   254),
    ("Travel guidebook",           "guidebook,travel", 255),
    ("Magazine",                   "magazine",         256),
    ("Folder of papers",           "folder,documents", 257),
    ("Sticky notes pad",           "sticky,notes",     258),

    # --- food / drink ---
    ("Stainless water bottle",     "waterbottle",      300),
    ("Travel coffee mug",          "mug,coffee",       301),
    ("Lunch box",                  "lunchbox",         302),
    ("Snack bar",                  "snack,bar",        303),
    ("Glass jar",                  "jar,glass",        304),
    ("Thermos flask",              "thermos,flask",    305),

    # --- toys / kids ---
    ("Teddy bear",                 "teddybear",        350),
    ("Lego bricks",                "lego",             351),
    ("Toy car",                    "toy,car",          352),
    ("Plush dinosaur",             "plush,dinosaur",   353),
    ("Coloring book",              "coloring,book",    354),
    ("Pacifier",                   "pacifier,baby",    355),
    ("Building blocks",            "blocks,toy",       356),

    # --- jewelry ---
    ("Silver necklace",            "necklace",         400),
    ("Pearl earrings",             "earrings",         401),
    ("Gold bracelet",              "bracelet,gold",    402),
    ("Diamond ring",               "ring,diamond",     403),
    ("Charm bracelet",             "charm,bracelet",   404),
    ("Pocket watch",               "pocket,watch",     405),

    # --- sports / outdoor ---
    ("Yoga mat",                   "yoga,mat",         450),
    ("Tennis racket",              "tennis,racket",    451),
    ("Soccer ball",                "soccer,ball",      452),
    ("Skateboard",                 "skateboard",       453),
    ("Bicycle helmet",             "helmet,bicycle",   454),
    ("Hiking boots",               "hiking,boots",     455),
    ("Frisbee",                    "frisbee",          456),
    ("Climbing rope",              "climbing,rope",    457),

    # --- musical ---
    ("Acoustic guitar",            "guitar,acoustic",  500),
    ("Harmonica",                  "harmonica",        501),
    ("Headphone case",             "headphone,case",   502),

    # --- misc / household ---
    ("Set of keys",                "keys",             550),
    ("Compact umbrella",           "umbrella,compact", 551),
    ("Pill organizer",             "pill,organizer",   552),
    ("Reading lamp",               "lamp,desk",        553),
    ("Travel pillow",              "travel,pillow",    554),
    ("Sleeping eye mask",          "sleep,mask",       555),
    ("Hand sanitizer bottle",      "sanitizer,bottle", 556),
    ("Face mask",                  "facemask",         557),
    ("Stuffed plush toy",          "plush,toy",        558),
    ("Picture frame",              "picture,frame",    559),
    ("Map foldable",               "map,paper",        560),
    ("Fountain pen",               "fountain,pen",     561),
    ("Lipstick",                   "lipstick,makeup",  562),
    ("Perfume bottle",             "perfume,bottle",   563),
    ("Eyeglass case",              "eyeglass,case",    564),
]
CATALOG: list[tuple[str, str]] = [
    (label, f"https://loremflickr.com/640/480/{topic}?lock={lock}")
    for label, topic, lock in _RAW
]

GATES = [f"Gate {g}" for g in ("A12", "B7", "C3", "D15", "E22", "F1", "G9")]
AREAS = ["Departure lounge", "Baggage claim", "Security checkpoint", "Restroom",
         "Food court", "Boarding gate", "Lounge seat", "Taxi stand"]


def download_image(url: str, timeout: int = 20) -> bytes | None:
    """Fetch an image with a UA header (Wikimedia rejects empty UAs)."""
    try:
        req = Request(url, headers={
            "User-Agent": "lostnfound-bulk-ingest/1.0 (https://github.com/vinayjain)",
        })
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (HTTPError, URLError, TimeoutError) as e:
        print(f"    ! download failed: {e}")
        return None


def post_report(app_url: str, label: str, img_bytes: bytes) -> tuple[bool, str]:
    location = f"{random.choice(GATES)} - {random.choice(AREAS)}"
    files = {"images": (f"{label}.jpg", img_bytes, "image/jpeg")}
    data = {"location": location, "reported_by": "bulk-ingest"}
    try:
        r = requests.post(f"{app_url.rstrip('/')}/api/report",
                          files=files, data=data, timeout=120)
        if r.status_code in (200, 201):
            j = r.json()
            if j.get("needs_more_images"):
                return False, "needs_more_images"
            return True, j.get("item", {}).get("item_name", "?")
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except requests.RequestException as e:
        return False, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://app-lostnfound-s1thjq.azurewebsites.net",
                    help="Base URL of the running app")
    ap.add_argument("--start", type=int, default=0,
                    help="Skip the first N entries (useful to resume)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Only ingest the first N entries (after --start)")
    ap.add_argument("--shuffle", action="store_true", help="Randomize order")
    ap.add_argument("--sleep", type=float, default=1.5,
                    help="Seconds to wait between uploads")
    args = ap.parse_args()

    catalog = CATALOG[:]
    if args.shuffle:
        random.shuffle(catalog)
    if args.start > 0:
        catalog = catalog[args.start:]
    if args.limit > 0:
        catalog = catalog[:args.limit]

    print(f"Target: {args.url}")
    print(f"Items to attempt: {len(catalog)}\n")

    ok = fail = 0
    for i, (label, url) in enumerate(catalog, 1):
        print(f"[{i}/{len(catalog)}] {label}")
        print(f"    src: {url}")
        img = download_image(url)
        if img is None:
            fail += 1
            continue
        print(f"    downloaded {len(img):,} bytes — uploading...")
        success, msg = post_report(args.url, label, img)
        if success:
            ok += 1
            print(f"    OK  -> {msg}")
        else:
            fail += 1
            print(f"    FAIL -> {msg}")
        time.sleep(args.sleep)

    print(f"\nDone. {ok} ingested, {fail} failed.")


if __name__ == "__main__":
    main()

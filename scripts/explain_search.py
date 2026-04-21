"""Step-by-step "explain like I'm 5" trace of a search query.

Walks through EXACTLY what the production code does in src/app.py and
src/services/cosmos_service.py, printing the inputs, intermediate values,
and outputs of every stage so you can see why each item was kept or dropped.

Usage:
    .venv\\Scripts\\python.exe scripts\\explain_search.py phone
    .venv\\Scripts\\python.exe scripts\\explain_search.py alcohol
    .venv\\Scripts\\python.exe scripts\\explain_search.py "tumi backpack"
"""
import os
import sys
import json
import logging
import textwrap

# Silence noisy SDK loggers BEFORE anything imports azure/openai.
for name in ("azure", "azure.identity", "azure.core", "openai",
             "httpx", "httpcore", "urllib3", "msal"):
    logging.getLogger(name).setLevel(logging.WARNING)

# Bootstrap env BEFORE importing app modules.
os.environ.setdefault('AZURE_AI_SERVICES_ENDPOINT', 'https://foundry-multimodel.services.ai.azure.com')
os.environ.setdefault('COSMOS_ENDPOINT', 'https://cosmos-lostnfound-s1thjq.documents.azure.com:443/')
os.environ.setdefault('AZURE_STORAGE_ACCOUNT_URL', 'https://stlostnfound.blob.core.windows.net')
os.environ.setdefault('COSMOS_CONTAINER', 'items_v2')

sys.path.insert(0, '.')

from src.app import _build_embed_text                # the same fn used by /api/search/text
from src.services import ai_service, cosmos_service  # production modules
from src.services.cosmos_service import (
    _get_container,
    _keyword_score,
)
from src.config import Config


# ---------- pretty-printing helpers ----------
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"


def banner(title: str) -> None:
    print()
    print(BOLD + CYAN + "=" * 78 + RESET)
    print(BOLD + CYAN + f" {title}" + RESET)
    print(BOLD + CYAN + "=" * 78 + RESET)


def step(num: int, title: str, why: str) -> None:
    print()
    print(BOLD + f"[STEP {num}] {title}" + RESET)
    for line in textwrap.wrap(why, width=78):
        print(DIM + "    " + line + RESET)
    print()


def kv(label: str, value) -> None:
    print(f"    {YELLOW}{label}:{RESET} {value}")


def row(prefix: str, sim: float, hyb, brand: str, name: str, kept: bool | None = None) -> None:
    sim_s = f"{sim:.4f}" if isinstance(sim, (int, float)) else "  -   "
    hyb_s = f"{hyb:.2f}" if isinstance(hyb, (int, float)) else "  -  "
    mark = ""
    if kept is True:
        mark = GREEN + " KEEP" + RESET
    elif kept is False:
        mark = RED + " DROP" + RESET
    name = (name or "")[:55]
    brand = (brand or "-")[:14]
    print(f"  {prefix} sim={sim_s}  hyb={hyb_s}  brand={brand:<14}  {name}{mark}")


# ---------- the actual trace ----------
def explain(query: str) -> None:
    banner(f"Tracing search for: {query!r}")

    # --------------------------------------------------------------
    step(1, "Ask the LLM to parse the user's free text into structured fields",
         "We send the raw query to GPT and get back item_name, brand, color, "
         "category, keywords, etc. This normalises any language to English and "
         "expands a single word like 'phone' into related terms ('smartphone', "
         "'mobile', 'cell phone', ...). Code: ai_service.search_by_text().")
    fields = ai_service.search_by_text(query)
    print(json.dumps(fields, indent=2, ensure_ascii=False))

    # --------------------------------------------------------------
    step(2, "Build the embedding TEXT (not the vector yet)",
         "A single token embeds weakly, so src/app.py::_build_embed_text() "
         "concatenates query_text + item_name + brand + color + first 5 "
         "keywords into one richer string. This pushes the query vector closer "
         "to how item documents were embedded.")
    embed_text = _build_embed_text(fields, query)
    kv("Concatenated text we will embed", repr(embed_text))

    # --------------------------------------------------------------
    step(3, "Convert the text into a 1536-dim VECTOR (the embedding)",
         "ai_service.generate_embedding() calls Azure OpenAI's "
         "text-embedding-3-small model. The result is a list of 1536 floats "
         "that encodes the *meaning* of the text in a high-dim space.")
    qv = ai_service.generate_embedding(embed_text)
    kv("Vector dimension", len(qv))
    kv("First 5 numbers", [round(x, 4) for x in qv[:5]])
    kv("Last 5 numbers", [round(x, 4) for x in qv[-5:]])

    # --------------------------------------------------------------
    step(4, "Ask Cosmos DB for the K nearest neighbours by cosine distance",
         "VECTOR_SEARCH_TOP_K controls how many candidates we recall. Cosmos "
         "uses its diskANN vector index on c.embedding to do this fast. "
         "We project lightweight columns (no embeddings back!) plus the "
         "computed similarity. SQL: ORDER BY VectorDistance(c.embedding, @qv).")
    kv("VECTOR_SEARCH_TOP_K", Config.VECTOR_SEARCH_TOP_K)
    kv("HYBRID_MIN_SIMILARITY (hard floor)", Config.HYBRID_MIN_SIMILARITY)

    cnt = _get_container()
    raw_q = (
        "SELECT TOP @top c.id, c.category, c.item_name, c.description, c.color, c.colors, "
        "c.brand, c.size, c.condition, c.distinguishing_features, c.ocr_text, "
        "VectorDistance(c.embedding, @qv) AS similarity "
        "FROM c WHERE IS_DEFINED(c.embedding) "
        "ORDER BY VectorDistance(c.embedding, @qv)"
    )
    candidates = list(cnt.query_items(
        query=raw_q,
        parameters=[
            {"name": "@top", "value": Config.VECTOR_SEARCH_TOP_K},
            {"name": "@qv", "value": qv},
        ],
        enable_cross_partition_query=True,
    ))
    print(f"    Cosmos returned {len(candidates)} candidate row(s). Top 10:")
    for i, c in enumerate(candidates[:10], 1):
        row(f"#{i:2}", c.get("similarity"), None, c.get("brand"), c.get("item_name"))

    # --------------------------------------------------------------
    step(5, "Apply the SIMILARITY FLOOR (two-tier)",
         "Anything below 0.35 is usually unrelated. But if AT LEAST ONE item "
         "passes 0.35, we also keep close neighbours within 0.15 of the top "
         "match (so iPhone @0.34 isn't dropped just because Smartphone @0.48 "
         "is the literal hit). If NOTHING reaches 0.35, we fall back to a "
         "soft floor of 0.20 and let the relative cutoff decide.")
    min_sim = Config.HYBRID_MIN_SIMILARITY
    strong = [c for c in candidates if c.get("similarity", 0) >= min_sim]
    if strong:
        top_sim = strong[0].get("similarity", 0) or 0
        neighbor_floor = max(0.20, top_sim - 0.15)
        kept = [c for c in candidates if (c.get("similarity", 0) or 0) >= neighbor_floor]
        had_strong = True
        kv("At least one item >= 0.35?", f"YES (top sim={top_sim:.4f})")
        kv("Neighbour floor (top - 0.15, min 0.20)", f"{neighbor_floor:.4f}")
    else:
        soft_floor = max(0.20, min_sim - 0.15)
        kept = [c for c in candidates if c.get("similarity", 0) >= soft_floor]
        had_strong = False
        kv("At least one item >= 0.35?", "NO -> using soft floor")
        kv("Soft floor (min_sim - 0.15, min 0.20)", f"{soft_floor:.4f}")

    kept_ids = {c["id"] for c in kept}
    print(f"    Result of floor stage: {len(kept)} kept, {len(candidates) - len(kept)} dropped.")
    for i, c in enumerate(candidates[:10], 1):
        row(f"#{i:2}", c.get("similarity"), None, c.get("brand"), c.get("item_name"),
            kept=(c["id"] in kept_ids))
    candidates = kept

    # --------------------------------------------------------------
    step(6, "Add a KEYWORD score on top of similarity (the 'hybrid' part)",
         "Pure vector search ignores literal evidence (brand text, OCR). "
         "_keyword_score() scans each survivor for: brand match (+10), brand-"
         "in-OCR (+8), keyword in OCR/brand (+4), keyword in name (+2), "
         "category match (+3), color match (+2), etc. Final hybrid score = "
         "similarity * 10 + keyword_score.")
    for c in candidates:
        ks = _keyword_score(c, fields)
        c["_kw_score"] = ks
        c["_hybrid_score"] = c.get("similarity", 0) * 10 + ks
    candidates.sort(key=lambda x: x["_hybrid_score"], reverse=True)
    print("    Hybrid scoring (sorted by hybrid score):")
    for i, c in enumerate(candidates, 1):
        sim = c.get("similarity", 0) or 0
        kw = c.get("_kw_score", 0)
        hyb = c.get("_hybrid_score", 0)
        print(f"  #{i:2}  sim={sim:.4f}  *10 + kw={kw:>3} = hyb={hyb:6.2f}  "
              f"brand={(c.get('brand') or '-')[:14]:<14}  {(c.get('item_name') or '')[:55]}")

    # --------------------------------------------------------------
    step(7, "Apply the RELATIVE cutoff (three regimes)",
         "Even after re-ranking, the bottom of the list is usually noise. "
         "  - If top hybrid >= 10 (clear keyword winner): keep within 70% of top "
         "    OR within 0.15 sim of top vector match (rescues close vector "
         "    neighbours when one item ran away with the keyword bonus). "
         "  - Else if had_strong (strong vector hit, weak keywords): keep "
         "    neighbours within 0.15 sim of top. "
         "  - Else (no strong match at all): keep within 95% of top similarity "
         "    -- prevents 'alcohol' from dragging in every drink.")
    if candidates:
        top = candidates[0]["_hybrid_score"]
        top_sim = candidates[0].get("similarity", 0) or 0
        if top >= 10:
            regime = f"strong-keyword (top hyb={top:.2f} >= 10)"
            hyb_floor = top * 0.7
            sim_floor = max(0.20, top_sim - 0.15)
            survivors = [
                c for c in candidates
                if c["_hybrid_score"] >= hyb_floor
                or (c.get("similarity", 0) or 0) >= sim_floor
            ]
            kv("Regime", regime)
            kv("Cutoff", f"hybrid >= {hyb_floor:.2f} (70% of {top:.2f})  OR  sim >= {sim_floor:.4f} (top sim {top_sim:.4f} - 0.15)")
        elif had_strong and top_sim > 0:
            regime = "strong-vector / weak-keyword (had_strong=True)"
            cut_floor = max(0.20, top_sim - 0.15)
            survivors = [c for c in candidates if (c.get("similarity", 0) or 0) >= cut_floor]
            kv("Regime", regime)
            kv("Cutoff", f"sim >= {cut_floor:.4f}  (top sim {top_sim:.4f} - 0.15)")
        elif top_sim > 0:
            regime = "no-strong-match (had_strong=False)"
            cut_floor = top_sim * 0.95
            survivors = [c for c in candidates if (c.get("similarity", 0) or 0) >= cut_floor]
            kv("Regime", regime)
            kv("Cutoff", f"sim >= {cut_floor:.4f}  (95% of top sim {top_sim:.4f})")
        else:
            survivors = candidates
            kv("Regime", "n/a -- pass-through")
        survivor_ids = {c["id"] for c in survivors}
        print()
        for i, c in enumerate(candidates, 1):
            row(f"#{i:2}", c.get("similarity"), c.get("_hybrid_score"),
                c.get("brand"), c.get("item_name"),
                kept=(c["id"] in survivor_ids))
        candidates = survivors

    # --------------------------------------------------------------
    step(8, "FINAL RESULT",
         "These are the rows the user sees on /api/search/text.")
    if not candidates:
        print(RED + "    (no items returned)" + RESET)
    else:
        for i, c in enumerate(candidates, 1):
            print(GREEN + f"  #{i}  {(c.get('item_name') or '')}" + RESET)
            print(f"      brand={c.get('brand')}  category={c.get('category')}  "
                  f"sim={c.get('similarity'):.4f}  hyb={c.get('_hybrid_score'):.2f}  "
                  f"kw_score={c.get('_kw_score')}")
    print()


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "phone"
    explain(q)

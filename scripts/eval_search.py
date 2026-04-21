"""End-to-end search evaluation.

Lists every item in the v2 container, then runs a curated set of queries
through the FULL search pipeline (LLM field parse + rich embedding +
hybrid Cosmos search) and prints a single summary table.

Usage:
    $env:COSMOS_CONTAINER='items_v2'
    .venv\\Scripts\\python.exe scripts\\eval_search.py
"""
import os, json, sys, time

os.environ.setdefault('AZURE_AI_SERVICES_ENDPOINT', 'https://foundry-multimodel.services.ai.azure.com')
os.environ.setdefault('COSMOS_ENDPOINT', 'https://cosmos-lostnfound-s1thjq.documents.azure.com:443/')
os.environ.setdefault('AZURE_STORAGE_ACCOUNT_URL', 'https://stlostnfound.blob.core.windows.net')
os.environ.setdefault('COSMOS_CONTAINER', 'items_v2')

sys.path.insert(0, '.')
from src.services import ai_service, cosmos_service
from src.services.cosmos_service import _get_container

# Curated queries: (query, what we EXPECT to see — None = anything reasonable)
QUERIES = [
    # Brand/literal — should be tight
    ("tumi",            ["TUMI"]),
    ("tumi backpack",   ["TUMI"]),
    ("schweppes",       ["Schweppes"]),
    ("johnnie walker",  ["Johnnie Walker"]),
    ("apple",           ["Apple"]),
    ("iphone",          ["Apple"]),
    ("airpods",         ["Apple"]),
    ("magsafe",         ["Apple"]),
    ("wurkkos",         ["Wurkkos"]),
    ("hoco",            ["hoco"]),

    # Generic/category — should return only the truly relevant ones
    ("alcohol",         ["Johnnie Walker"]),
    ("whisky",          ["Johnnie Walker"]),
    ("scotch",          ["Johnnie Walker"]),
    ("soda",            ["Schweppes", "Coca-Cola"]),
    ("coke",            ["Coca-Cola"]),
    ("snack",           ["KUNNA", "Abu Auf"]),
    ("candy",           ["Abu Auf"]),
    ("water bottle",    ["water bottle"]),
    ("flashlight",      ["Wurkkos"]),
    ("torch",           ["Wurkkos"]),
    ("charger",         ["hoco"]),
    ("usb",             ["hoco"]),
    ("mouse",           ["Microsoft"]),
    ("keys",            None),
    ("receipts",        ["receipt"]),
    ("backpack",        ["backpack"]),
    ("black bag",       ["backpack"]),

    # Tricky / cross-language
    ("Apple ايفون",     ["Apple"]),       # Arabic 'iPhone'
    ("سكوتش",          ["Johnnie Walker"]), # Arabic 'Scotch'
]


def build_embed_text(fields, query):
    parts = [fields.get(k) for k in ('query_text', 'item_name', 'brand', 'color') if fields.get(k)]
    parts += [k for k in (fields.get('keywords') or [])[:5] if k]
    return ' '.join(parts).strip() or query


def list_all_items():
    cnt = _get_container()
    rows = list(cnt.query_items(
        query="SELECT c.id, c.brand, c.item_name, c.category FROM c",
        enable_cross_partition_query=True,
    ))
    return rows


def run_query(q):
    fields = ai_service.search_by_text(q)
    embed_text = build_embed_text(fields, q)
    qv = ai_service.generate_embedding(embed_text)
    items = cosmos_service.search_items(fields, query_embedding=qv)
    return fields, items


def short(item):
    name = (item.get('item_name') or '')[:40]
    brand = (item.get('brand') or '-')[:16]
    sim = item.get('similarity')
    hyb = item.get('_hybrid_score')
    return f"[{brand}] {name} (sim={sim:.2f} hyb={hyb:.1f})" if sim is not None else f"[{brand}] {name}"


def expected_match(items, expected):
    if expected is None:
        return "n/a"
    text_blob = ' '.join((it.get('brand') or '') + ' ' + (it.get('item_name') or '') for it in items).lower()
    hits = sum(1 for e in expected if e.lower() in text_blob)
    miss = [e for e in expected if e.lower() not in text_blob]
    extra = len(items) - hits
    if hits == len(expected) and extra == 0:
        return "OK   "
    if hits == len(expected) and extra > 0:
        return f"NOISY(+{extra})"
    return f"MISS({','.join(miss)})"


def main():
    print("=" * 100)
    print("ITEMS IN DB")
    print("=" * 100)
    items = list_all_items()
    items.sort(key=lambda x: (x.get('category') or '', x.get('brand') or ''))
    for it in items:
        print(f"  [{it.get('category') or '-':<14}] {it.get('brand') or '-':<16}  {it.get('item_name')}")
    print(f"\nTotal: {len(items)} items\n")

    print("=" * 100)
    print(f"QUERY EVALUATION ({len(QUERIES)} queries)")
    print("=" * 100)
    print(f"{'STATUS':<14} {'QUERY':<22} {'N':<3} TOP RESULTS")
    print("-" * 100)
    summary = []
    for q, expected in QUERIES:
        try:
            fields, results = run_query(q)
            status = expected_match(results, expected)
            top = '; '.join(short(r) for r in results[:3])
            print(f"{status:<14} {q:<22} {len(results):<3} {top}")
            summary.append((q, status, len(results)))
        except Exception as e:
            print(f"{'ERROR':<14} {q:<22} -   {e}")
            summary.append((q, "ERROR", 0))
        time.sleep(0.2)

    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    ok = sum(1 for _, s, _ in summary if s == "OK   ")
    noisy = sum(1 for _, s, _ in summary if s.startswith("NOISY"))
    miss = sum(1 for _, s, _ in summary if s.startswith("MISS"))
    err = sum(1 for _, s, _ in summary if s == "ERROR")
    na = sum(1 for _, s, _ in summary if s == "n/a")
    print(f"  OK:    {ok}")
    print(f"  NOISY: {noisy}  (correct items found, but extras returned)")
    print(f"  MISS:  {miss}   (missing expected items)")
    print(f"  N/A:   {na}")
    print(f"  ERR:   {err}")


if __name__ == '__main__':
    main()

"""Reproduce a 'tumi' search and explain what each candidate scored."""
import os, json
os.environ.setdefault('AZURE_AI_SERVICES_ENDPOINT', 'https://foundry-multimodel.services.ai.azure.com')
os.environ.setdefault('COSMOS_ENDPOINT', 'https://cosmos-lostnfound-s1thjq.documents.azure.com:443/')
os.environ.setdefault('AZURE_STORAGE_ACCOUNT_URL', 'https://stlostnfound.blob.core.windows.net')
os.environ.setdefault('COSMOS_CONTAINER', 'items_v2')

import sys; sys.path.insert(0, '.')
from src.services import ai_service, cosmos_service
from src.config import Config

QUERY = sys.argv[1] if len(sys.argv) > 1 else 'tumi backpack'

print(f"=== Query: '{QUERY}' ===\n")

fields = ai_service.search_by_text(QUERY)
print("1) Parsed fields from search_by_text:")
print(json.dumps(fields, indent=2))

embed_parts = [fields.get(k) for k in ('query_text','item_name','brand','color') if fields.get(k)]
embed_parts += [k for k in (fields.get('keywords') or [])[:5] if k]
embed_text = ' '.join(embed_parts) or QUERY
qv = ai_service.generate_embedding(embed_text)
print(f"\n2) Embedding text used for vector: {embed_text!r}")
print(f"   Embedding dim: {len(qv)}")
print(f"   HYBRID_MIN_SIMILARITY threshold: {Config.HYBRID_MIN_SIMILARITY}")
print(f"   VECTOR_SEARCH_TOP_K: {Config.VECTOR_SEARCH_TOP_K}")

items = cosmos_service.search_items(fields, query_embedding=qv)

print(f"\n3) Returned {len(items)} item(s).\n")
for i, it in enumerate(items[:10], 1):
    sim = it.get('similarity')
    hyb = it.get('_hybrid_score')
    sim_s = f"{sim:.4f}" if isinstance(sim,(int,float)) else "  -   "
    hyb_s = f"{hyb:.2f}" if isinstance(hyb,(int,float)) else "  -  "
    print(f"#{i}  sim={sim_s}  hybrid={hyb_s}  brand={(it.get('brand') or '-'):<12}  {it.get('item_name')}")

# Also show all candidates before cutoff (re-run raw vector query)
print("\n--- Raw top 8 vector neighbors (no cutoff) ---")
from src.services.cosmos_service import _get_container
cnt = _get_container()
q = ("SELECT TOP 8 c.item_name, c.brand, c.ocr_text, "
     "VectorDistance(c.embedding, @qv) AS sim FROM c WHERE IS_DEFINED(c.embedding) "
     "ORDER BY VectorDistance(c.embedding, @qv)")
for r in cnt.query_items(query=q, parameters=[{'name':'@qv','value':qv}], enable_cross_partition_query=True):
    print(f"  sim={r['sim']:.4f}  brand={r.get('brand') or '-':<10}  {r['item_name']}")

# Also show all candidates before cutoff (re-run raw vector query)
print("\n--- Raw top 8 vector neighbors (no cutoff) ---")
from src.services.cosmos_service import _get_container
cnt = _get_container()
q = ("SELECT TOP 8 c.item_name, c.brand, c.ocr_text, "
     "VectorDistance(c.embedding, @qv) AS sim FROM c WHERE IS_DEFINED(c.embedding) "
     "ORDER BY VectorDistance(c.embedding, @qv)")
for r in cnt.query_items(query=q, parameters=[{'name':'@qv','value':qv}], enable_cross_partition_query=True):
    print(f"  sim={r['sim']:.4f}  brand={r.get('brand') or '-':<10}  {r['item_name']}")

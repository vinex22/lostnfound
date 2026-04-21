import os, sys, json
os.environ.setdefault('AZURE_AI_SERVICES_ENDPOINT', 'https://foundry-multimodel.services.ai.azure.com')
sys.path.insert(0, '.')
from src.services import ai_service, cosmos_service
from src.services.cosmos_service import _get_container, _hybrid_search

qv = ai_service.generate_embedding('tumi backpack')
container = _get_container()
fields = {'brand': 'TUMI', 'item_name': 'backpack', 'category': 'bags',
          'keywords': ['backpack','bag','TUMI','Tumi']}
import logging; logging.basicConfig(level=logging.DEBUG)
items = _hybrid_search(container, fields, qv)
print(f"\nReturned {len(items)} items")
for it in items:
    print(f"  sim={it.get('similarity')!r:<20} hybrid={it.get('_hybrid_score')!r:<10} brand={it.get('brand')!r:<10} name={it.get('item_name')}")

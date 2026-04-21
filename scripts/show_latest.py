"""Show full info for the most recently created item in items_v2."""
import json
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient

c = CosmosClient('https://cosmos-lostnfound-s1thjq.documents.azure.com:443/', credential=DefaultAzureCredential())
cnt = c.get_database_client('lostnfound').get_container_client('items_v2')
r = list(cnt.query_items(
    'SELECT TOP 1 * FROM c ORDER BY c._ts DESC',
    enable_cross_partition_query=True))
if not r:
    print('no items')
else:
    item = r[0]
    emb = item.pop('embedding', None)
    print(json.dumps(item, indent=2, ensure_ascii=False))
    if emb:
        print(f"\nembedding: dim={len(emb)} first5={emb[:5]}")

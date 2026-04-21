from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient

c = CosmosClient('https://cosmos-lostnfound-s1thjq.documents.azure.com:443/', credential=DefaultAzureCredential())
cnt = c.get_database_client('lostnfound').get_container_client('items_v2')
r = list(cnt.query_items('SELECT c.item_name, c.ocr_text FROM c WHERE LENGTH(c.ocr_text) > 0', enable_cross_partition_query=True))
for x in r:
    print(f"{x['item_name']}\n  OCR: {x['ocr_text'][:200]}\n")
print(f'Total with OCR: {len(r)}/14')

"""Direct cosmos query to see raw VectorDistance values."""
import os
os.environ.setdefault('AZURE_AI_SERVICES_ENDPOINT', 'https://foundry-multimodel.services.ai.azure.com')
import sys; sys.path.insert(0, '.')
from src.services import ai_service
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient

qv = ai_service.generate_embedding('tumi backpack')
c = CosmosClient('https://cosmos-lostnfound-s1thjq.documents.azure.com:443/', credential=DefaultAzureCredential())
cnt = c.get_database_client('lostnfound').get_container_client('items_v2')
q = ("SELECT TOP 10 c.item_name, c.brand, "
     "VectorDistance(c.embedding, @qv) AS sim "
     "FROM c WHERE IS_DEFINED(c.embedding) "
     "ORDER BY VectorDistance(c.embedding, @qv)")
for r in cnt.query_items(query=q, parameters=[{'name':'@qv','value':qv}], enable_cross_partition_query=True):
    print(f"{r['sim']:.4f}  {r.get('brand') or '-':<10}  {r['item_name']}")

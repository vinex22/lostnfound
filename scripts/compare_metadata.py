"""Compare metadata: old `items` container vs re-extracted `items_v2`."""
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient

cred = DefaultAzureCredential()
c = CosmosClient('https://cosmos-lostnfound-s1thjq.documents.azure.com:443/', credential=cred)
db = c.get_database_client('lostnfound')
old_c = db.get_container_client('items')
new_c = db.get_container_client('items_v2')

FIELDS = ['item_name', 'description', 'color', 'colors', 'brand', 'condition',
          'distinguishing_features', 'ocr_text', 'confidence']

new_items = list(new_c.query_items('SELECT * FROM c', enable_cross_partition_query=True))

def fmt(v, maxlen=200):
    if v is None or v == '' or v == []:
        return '(empty)'
    if isinstance(v, list):
        return '[' + ', '.join(str(x) for x in v) + ']'
    s = str(v)
    return s if len(s) <= maxlen else s[:maxlen] + '...'

for nv in new_items:
    iid = nv['id']
    try:
        ov = old_c.read_item(item=iid, partition_key=iid)
    except Exception:
        # try cross partition
        r = list(old_c.query_items(
            query='SELECT * FROM c WHERE c.id=@id',
            parameters=[{'name':'@id','value':iid}],
            enable_cross_partition_query=True))
        ov = r[0] if r else None
    print('=' * 100)
    print(f"ID: {iid}")
    if not ov:
        print('  (no old version found)')
        continue
    for f in FIELDS:
        ov_v = ov.get(f)
        nv_v = nv.get(f)
        if ov_v == nv_v:
            continue
        print(f"\n  [{f}]")
        print(f"    OLD: {fmt(ov_v)}")
        print(f"    NEW: {fmt(nv_v)}")
    print()

"""Create items_v2 container with vector embedding policy via Python SDK."""
import os
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient, PartitionKey

ENDPOINT = "https://cosmos-lostnfound-s1thjq.documents.azure.com:443/"
DATABASE = "lostnfound"
CONTAINER = "items_v2"

vector_embedding_policy = {
    "vectorEmbeddings": [
        {
            "path": "/embedding",
            "dataType": "float32",
            "distanceFunction": "cosine",
            "dimensions": 1536,
        }
    ]
}

indexing_policy = {
    "indexingMode": "consistent",
    "automatic": True,
    "includedPaths": [{"path": "/*"}],
    "excludedPaths": [
        {"path": "/embedding/*"},
        {"path": "/_etag/?"},
    ],
    "vectorIndexes": [
        {"path": "/embedding", "type": "diskANN"},
    ],
}

full_text_policy = {
    "defaultLanguage": "en-US",
    "fullTextPaths": [
        {"path": "/description", "language": "en-US"},
        {"path": "/item_name", "language": "en-US"},
        {"path": "/distinguishing_features", "language": "en-US"},
        {"path": "/ocr_text", "language": "en-US"},
    ],
}

client = CosmosClient(url=ENDPOINT, credential=DefaultAzureCredential())
db = client.get_database_client(DATABASE)

print(f"Creating container {CONTAINER}...")
container = db.create_container_if_not_exists(
    id=CONTAINER,
    partition_key=PartitionKey(path="/category"),
    indexing_policy=indexing_policy,
    vector_embedding_policy=vector_embedding_policy,
    full_text_policy=full_text_policy,
)
props = container.read()
print("Created:")
print(f"  id: {props['id']}")
print(f"  partitionKey: {props['partitionKey']}")
print(f"  vectorEmbeddingPolicy: {props.get('vectorEmbeddingPolicy')}")
print(f"  indexingPolicy.vectorIndexes: {props['indexingPolicy'].get('vectorIndexes')}")
print(f"  fullTextPolicy: {props.get('fullTextPolicy')}")

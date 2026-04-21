"""Create items_v2 with vector + full-text policy via ARM REST API."""
import json
import subprocess
import sys
import urllib.request

SUB = "555a1e03-73fb-4f88-9296-59bd703d16f3"
RG = "rg-lostnfound"
ACCOUNT = "cosmos-lostnfound-s1thjq"
DB = "lostnfound"
CONTAINER = "items_v2"
API_VERSION = "2024-12-01-preview"

token = subprocess.check_output(
    ["az", "account", "get-access-token", "--resource", "https://management.azure.com",
     "--query", "accessToken", "-o", "tsv"],
    text=True, shell=True,
).strip()

url = (
    f"https://management.azure.com/subscriptions/{SUB}/resourceGroups/{RG}"
    f"/providers/Microsoft.DocumentDB/databaseAccounts/{ACCOUNT}"
    f"/sqlDatabases/{DB}/containers/{CONTAINER}?api-version={API_VERSION}"
)

body = {
    "properties": {
        "resource": {
            "id": CONTAINER,
            "partitionKey": {"paths": ["/category"], "kind": "Hash"},
            "indexingPolicy": {
                "indexingMode": "consistent",
                "automatic": True,
                "includedPaths": [{"path": "/*"}],
                "excludedPaths": [
                    {"path": "/embedding/*"},
                    {"path": "/_etag/?"},
                ],
                "vectorIndexes": [
                    {"path": "/embedding", "type": "diskANN"}
                ],
            },
            "vectorEmbeddingPolicy": {
                "vectorEmbeddings": [
                    {
                        "path": "/embedding",
                        "dataType": "float32",
                        "distanceFunction": "cosine",
                        "dimensions": 1536,
                    }
                ]
            },
            "fullTextPolicy": {
                "defaultLanguage": "en-US",
                "fullTextPaths": [
                    {"path": "/description", "language": "en-US"},
                    {"path": "/item_name", "language": "en-US"},
                    {"path": "/distinguishing_features", "language": "en-US"},
                    {"path": "/ocr_text", "language": "en-US"},
                ],
            },
        },
        "options": {},
    }
}

req = urllib.request.Request(
    url,
    method="PUT",
    data=json.dumps(body).encode(),
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req) as resp:
        print(f"Status: {resp.status}")
        print(resp.read().decode()[:2000])
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.reason}")
    print(e.read().decode())
    sys.exit(1)

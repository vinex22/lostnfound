# ☁️ Deployment Guide — Lost & Found

Deploy to Azure App Service (Linux, Python 3.12).

## Prerequisites

- Azure CLI installed and logged in (`az login`)
- Subscription: `555a1e03-73fb-4f88-9296-59bd703d16f3`
- Resource Group: `rg-lostnfound` (Central India)

## Infrastructure (already provisioned)

| Resource | Name |
|----------|------|
| App Service Plan | `plan-lostnfound` (B1 Linux) |
| Web App | `app-lostnfound-s1thjq` |
| Cosmos DB | `cosmos-lostnfound-s1thjq` (Serverless, NoSQL) |
| Storage | `stlostnfound` (LRS) |
| Managed Identity | `id-lostnfound` |
| VNet | `vnet-lostnfound` (10.0.0.0/16) |
| Private Endpoints | Cosmos DB + Storage |
| App Insights | `appi-lostnfound` |

## Deploy Code

```powershell
# From the project root
az webapp up --resource-group rg-lostnfound --name app-lostnfound-s1thjq --runtime "PYTHON:3.12"
```

The startup command is already configured:
```
gunicorn --bind 0.0.0.0:8000 src.app:app
```

## App Settings

These are already set on the web app. To update:

```powershell
az webapp config appsettings set --resource-group rg-lostnfound --name app-lostnfound-s1thjq --settings \
  AZURE_AI_SERVICES_ENDPOINT=https://foundry-multimodel.services.ai.azure.com \
  AZURE_OPENAI_DEPLOYMENT=gpt-5.4 \
  COSMOS_ENDPOINT=https://cosmos-lostnfound-s1thjq.documents.azure.com:443/ \
  COSMOS_DATABASE=lostnfound \
  COSMOS_CONTAINER=items \
  AZURE_STORAGE_ACCOUNT_URL=https://stlostnfound.blob.core.windows.net \
  STORAGE_CONTAINER=images \
  AZURE_CLIENT_ID=ea1b7da4-7752-4fd0-8dcd-4f3f0e69c652 \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true
```

## RBAC Roles (on Managed Identity `id-lostnfound`)

| Role | Scope |
|------|-------|
| Cosmos DB Built-in Data Contributor | `cosmos-lostnfound-s1thjq` |
| Storage Blob Data Contributor | `stlostnfound` |
| Cognitive Services OpenAI User | `foundry-multimodel` (aifoundry RG) |

## Networking

- App Service is VNet-integrated via `snet-webapp` (10.0.0.0/24)
- Cosmos DB accessible via Private Endpoint in `snet-pe` (10.0.1.0/24)
- Storage accessible via Private Endpoint in `snet-pe`
- Private DNS zones linked to VNet for PE resolution
- **No public access** on Cosmos DB or Storage

## Monitoring

- App Insights: `appi-lostnfound` (OpenTelemetry distro, Live Metrics enabled)
- Log Analytics: `log-lostnfound`
- View logs: `az webapp log tail --name app-lostnfound-s1thjq -g rg-lostnfound`

## Recreate Infrastructure from Scratch

See [../.azure/deployment-plan.md](../.azure/deployment-plan.md) for the full provisioning checklist.

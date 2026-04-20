# 📦 Lost & Found

[Python 3.12](https://www.python.org/) [Flask](https://flask.palletsprojects.com/) [Azure OpenAI](https://azure.microsoft.com/products/ai-services/openai-service) [License: MIT](LICENSE) [Deploy: Azure App Service](https://app-lostnfound-s1thjq.azurewebsites.net)

Created by [vinayjain@microsoft.com](mailto:vinayjain@microsoft.com) / [vinex22@gmail.com](mailto:vinex22@gmail.com)

**AI-Powered Airport Lost & Found** — employees report found items by snapping a photo; GPT-5.4 extracts rich metadata automatically. Passengers search by text (any language) or by uploading a photo of their lost item. Built with Flask, Cosmos DB, Blob Storage, and `DefaultAzureCredential` (no API keys 🔑).

> **Live instance:** [https://app-lostnfound-s1thjq.azurewebsites.net](https://app-lostnfound-s1thjq.azurewebsites.net)

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Prerequisites](#-prerequisites)
- [Project Structure](#-project-structure)
- [Configuration](#-configuration)
- [Local Development](#-local-development)
- [API Endpoints](#-api-endpoints)
- [Architecture](#-architecture)
- [Deployment](#-deployment)
- [Troubleshooting](#-troubleshooting)
- [License](#-license)

---

## 🔎 Overview

1. **Report** — Employee uploads up to 3 photos + free-text location → GPT-5.4 extracts structured metadata (category, brand, color, size, condition, distinguishing features)
2. **Search (Text)** — Type a natural language query in any language → GPT converts to structured fields → OR-based Cosmos DB query with relevance ranking
3. **Search (Camera)** — Upload/snap a photo of your lost item → GPT extracts metadata → matches against the database
4. **Dashboard** — Browse recently found items with click-to-expand detail modal

---

## ✈️ Features

- **AI Vision Metadata Extraction** — GPT-5.4 reads brand, color, text, distinguishing marks from photos
- **Multi-language Search** — query in English, Hindi, Chinese, Japanese, etc.
- **Camera Capture** — mobile-first with `capture="environment"` for rear camera
- **Photo Search** — find items by uploading a similar photo
- **Up to 3 photos per item** — GPT can request more if quality is insufficient
- **Private Endpoints** — Cosmos DB and Storage accessible only via VNet
- **Managed Identity** — zero API keys, zero SAS tokens, zero passwords
- **Application Insights** — OpenTelemetry instrumentation with Live Metrics
- **Mobile-first responsive UI** — clean minimal design inspired by modern web apps

---

## ✅ Prerequisites

1. Python 3.12+
2. Azure AI Services account with GPT-5.4 deployment (vision-capable)
3. Azure Cosmos DB NoSQL (Serverless)
4. Azure Blob Storage account
5. `Cognitive Services OpenAI User` role for your identity
6. `az login` completed (for local dev)

---

## 📁 Project Structure

```
lostnfound/
├── src/
│   ├── app.py                    # Flask application + API routes
│   ├── config.py                 # Configuration from environment
│   ├── __init__.py
│   ├── services/
│   │   ├── ai_service.py         # GPT-5.4 metadata extraction + search
│   │   ├── cosmos_service.py     # Cosmos DB CRUD + search queries
│   │   └── storage_service.py    # Blob Storage upload/download
│   ├── templates/
│   │   ├── base.html             # Base template (nav, branding)
│   │   ├── index.html            # Dashboard (recent items feed)
│   │   ├── report.html           # Report found item page
│   │   └── search.html           # Search page (text + camera tabs)
│   └── static/
│       ├── css/style.css         # Custom CSS (no Bootstrap)
│       └── js/
│           ├── report.js         # Report page logic
│           └── search.js         # Search page logic
├── docs/
│   ├── architecture.drawio       # Editable draw.io diagram
│   └── DEPLOYMENT.md             # Azure deployment guide
├── wiki/                         # Agent knowledge base (gitignored)
├── .azure/
│   └── deployment-plan.md        # Azure deployment plan
├── .env.example                  # Environment variable template
├── .gitignore
├── LICENSE
├── README.md
├── requirements.txt
└── startup.sh                    # Gunicorn startup command
```

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_AI_SERVICES_ENDPOINT` | Yes | Azure AI Foundry endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT` | No | Model deployment name (default: `gpt-5.4`) |
| `COSMOS_ENDPOINT` | Yes | Cosmos DB endpoint URL |
| `COSMOS_DATABASE` | No | Database name (default: `lostnfound`) |
| `COSMOS_CONTAINER` | No | Container name (default: `items`) |
| `AZURE_STORAGE_ACCOUNT_URL` | Yes | Blob Storage endpoint URL |
| `STORAGE_CONTAINER` | No | Blob container name (default: `images`) |
| `AZURE_CLIENT_ID` | No | Managed identity client ID (for App Service) |
| `DEBUG` | No | Enable debug logging (`true`/`false`) |

---

## 🚀 Local Development

```bash
# Clone the repo
git clone https://github.com/vinex22/lostnfound.git
cd lostnfound

# Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows PowerShell
# source .venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your Azure resource values

# Run the app
python -m flask --app src.app run --host 0.0.0.0 --port 8000 --debug
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## 🔌 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Dashboard — recent items feed |
| `GET` | `/report` | Report found item page |
| `GET` | `/search` | Search page (text + camera) |
| `POST` | `/api/report` | Submit found item (multipart: images + location) |
| `POST` | `/api/search/text` | Natural language text search |
| `POST` | `/api/search/image` | Photo-based search |
| `GET` | `/api/items/recent` | Get recent items JSON |
| `GET` | `/images/<path>` | Image proxy (storage behind PE) |

---

## 🧠 Architecture

Edit the diagram: open [docs/architecture.drawio](docs/architecture.drawio) in [draw.io](https://app.diagrams.net/) or VS Code.

**Flow:**

1. Employee/passenger accesses the web app via browser (mobile camera or desktop)
2. **Report**: Photos sent to GPT-5.4 → extracts structured metadata → images stored in Blob Storage → metadata saved to Cosmos DB
3. **Search (Text)**: GPT-5.4 converts natural language to query fields → Cosmos DB OR-query with relevance ranking
4. **Search (Camera)**: GPT-5.4 extracts metadata from search photo → matches against DB

**Azure Resources (Central India):**

| Resource | Name | Purpose |
|----------|------|---------|
| Resource Group | `rg-lostnfound` | All resources |
| App Service | `app-lostnfound-s1thjq` | Flask web app (B1 Linux) |
| Cosmos DB | `cosmos-lostnfound-s1thjq` | NoSQL metadata store (Serverless) |
| Storage | `stlostnfound` | Blob storage for images |
| Managed Identity | `id-lostnfound` | Passwordless auth to all services |
| VNet | `vnet-lostnfound` | Network isolation |
| Private Endpoints | PE for Cosmos DB + Storage | No public access |
| App Insights | `appi-lostnfound` | Monitoring + Live Metrics |
| Log Analytics | `log-lostnfound` | Centralized logging |
| Azure OpenAI | `foundry-multimodel` / `gpt-5.4` | Vision model (in `aifoundry` RG) |

**Security:**
- No API keys, SAS tokens, or passwords — all auth via `DefaultAzureCredential` + managed identity
- Cosmos DB and Storage behind Private Endpoints (public access disabled)
- App Service VNet-integrated to reach PEs

---

## ☁️ Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full Azure deployment instructions.

```powershell
# Quick deploy
az webapp up --resource-group rg-lostnfound --name app-lostnfound-s1thjq --runtime "PYTHON:3.12"
```

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| 401/403 from Azure AI | Ensure `Cognitive Services OpenAI User` role on AI Services account |
| Cosmos DB Forbidden | Assign `Cosmos DB Built-in Data Contributor` (RBAC, not ARM role) |
| Blob upload fails | Verify MI has `Storage Blob Data Contributor` on storage account |
| 503 after deploy | Check logs: `az webapp log tail --name app-lostnfound-s1thjq -g rg-lostnfound` |
| `max_tokens` error | GPT-5.4 requires `max_completion_tokens` (not `max_tokens`) |
| Camera not working | Camera access requires HTTPS; `.azurewebsites.net` provides this |
| ModuleNotFoundError | Set `SCM_DO_BUILD_DURING_DEPLOYMENT=true` in app settings |

---

## 📜 License

MIT — see [LICENSE](LICENSE) for details.

---

## 🤝 Contributing

Contributions welcome! Please open an issue first to discuss what you'd like to change.

---

Built with ❤️ using Azure AI Services · [Live Demo](https://app-lostnfound-s1thjq.azurewebsites.net)

**Keywords:** lost and found AI, airport lost property, Azure OpenAI GPT-5.4 multimodal, Cosmos DB NoSQL, image metadata extraction, Flask camera app, managed identity, private endpoints

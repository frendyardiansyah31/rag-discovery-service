# UIII Library RAG Service

A Retrieval-Augmented Generation (RAG) service for the UIII (Universitas Islam Internasional Indonesia) Library. It harvests academic metadata from a DSpace repository, indexes it with dense vector embeddings, and answers natural-language queries using hybrid semantic search combined with an LLM.

## Features

- Harvest library catalog metadata from DSpace via OAI-PMH
- Hybrid search: BM25 full-text + KNN vector search with RRF normalization (OpenSearch) or dense-vector KNN (Elasticsearch)
- Cross-encoder reranking for improved result relevance
- Answer generation via Groq API (LLaMA 3.1 8B Instant)
- REST API with `/health` and `/query` endpoints

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn |
| Embedding Model | `paraphrase-multilingual-MiniLM-L12-v2` (sentence-transformers) |
| Reranker Model | `BAAI/bge-reranker-base` (CrossEncoder) |
| Vector / Search DB | OpenSearch (primary) or Elasticsearch (alternative) |
| LLM Backend | [Groq API](https://console.groq.com/) — LLaMA 3.1 8B Instant |
| Data Harvesting | [Sickle](https://sickle.readthedocs.io/) — OAI-PMH client for DSpace |
| Runtime | Python 3.10, PyTorch (CPU) |

## Project Structure

```
rag-service/
├── main.py               # FastAPI app — /health and /query endpoints
├── retriever.py          # OpenSearch retriever: hybrid BM25+KNN + reranker
├── retriever_es.py       # Elasticsearch retriever: KNN + reranker
├── llm.py                # Groq LLM client for answer generation
├── start.sh              # Convenience script to launch the API server
├── requirements.txt      # Python dependencies
├── .env.example          # Environment variable template
└── ingest/
    ├── harvester.py      # Harvest records from DSpace OAI-PMH endpoint
    ├── create_index.py   # Create OpenSearch index + hybrid search pipeline
    ├── create_index_es.py# Create Elasticsearch index with dense_vector mapping
    ├── run_ingest.py     # Embed and bulk-index documents into OpenSearch
    └── run_ingest_es.py  # Embed and bulk-index documents into Elasticsearch
```

## Setup

### 1. Clone and create virtual environment

```bash
git clone <repo-url>
cd rag-service

python3.10 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> PyTorch is installed as the CPU-only build. GPU support requires a separate torch installation.

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
# OpenSearch (primary)
OS_HOST=https://localhost:9200
OS_USER=admin
OS_PASSWORD=your_opensearch_password

# Elasticsearch (alternative)
ES_HOST=https://localhost:9200
ES_USER=elastic
ES_PASSWORD=your_elasticsearch_password

# Groq API
GROQ_API_KEY=your_groq_api_key

# DSpace OAI-PMH endpoint
DSPACE_OAI_URL=https://your-dspace-instance/oai/request
```

### 4. Prepare the search index

**Step 4a — Harvest metadata from DSpace:**

```bash
python ingest/harvester.py
```

This writes `dspace_sample.json` with up to 200 harvested records.

**Step 4b — Create the index (OpenSearch):**

```bash
python ingest/create_index.py
```

Or for Elasticsearch:

```bash
python ingest/create_index_es.py
```

**Step 4c — Embed and index documents:**

```bash
python ingest/run_ingest.py        # OpenSearch
# or
python ingest/run_ingest_es.py     # Elasticsearch
```

## Running the API

```bash
bash start.sh
```

The server starts on `http://0.0.0.0:8001`.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/query` | Ask a question against the library collection |

**Example request:**

```bash
curl -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Islamic finance in Southeast Asia", "top_k": 5}'
```

**Example response:**

```json
{
  "answer": "Based on the available collection, ...",
  "sources": [
    {
      "title": "...",
      "abstract": "...",
      "author": ["..."],
      "date": "2022",
      "url": "https://...",
      "score": 0.921
    }
  ],
  "query_time_ms": 340
}
```

# UIII Library RAG Service — Runbook

## Stack

| Komponen | Detail |
|---|---|
| **App** | FastAPI + Uvicorn, port `8001` |
| **Search** | OpenSearch 2.19.5, port `9200` |
| **Retrieval** | BM25 + KNN hybrid search, RRF normalization |
| **Reranker** | `BAAI/bge-reranker-base` (CrossEncoder) |
| **Embeddings** | `paraphrase-multilingual-MiniLM-L12-v2` (384 dims) |
| **LLM** | Groq API — `llama-3.1-8b-instant` |

---

## Endpoints

| Method | Path | Deskripsi |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/query` | RAG query |
| `GET` | `/docs` | OpenAPI UI |

**Contoh query:**
```bash
curl -s -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Islamic economics", "top_k": 5}'
```

---

## Perintah Berguna

### RAG Service

```bash
# Status
sudo systemctl status rag-service

# Start / Stop / Restart
sudo systemctl start rag-service
sudo systemctl stop rag-service
sudo systemctl restart rag-service

# Enable / Disable auto-start saat boot
sudo systemctl enable rag-service
sudo systemctl disable rag-service
```

### OpenSearch

```bash
# Status
sudo systemctl status opensearch

# Start / Stop / Restart
sudo systemctl start opensearch
sudo systemctl stop opensearch
sudo systemctl restart opensearch

# Cek cluster health
curl -sk -u admin:"R@gService_2024!" https://localhost:9200/_cluster/health | python3 -m json.tool

# Cek jumlah dokumen di index
curl -sk -u admin:"R@gService_2024!" https://localhost:9200/library_rag_docs/_count | python3 -m json.tool
```

---

## Cara Cek Log untuk Debug

### Log RAG Service (realtime)
```bash
sudo journalctl -u rag-service -f
```

### Log RAG Service (50 baris terakhir)
```bash
sudo journalctl -u rag-service -n 50 --no-pager
```

### Log RAG Service (sejak restart terakhir)
```bash
sudo journalctl -u rag-service -b --no-pager
```

### Log OpenSearch
```bash
# Realtime
sudo journalctl -u opensearch -f

# Error saja
sudo tail -f /var/log/opensearch/opensearch.log | grep -i error

# Semua log OpenSearch
ls /var/log/opensearch/
```

### Debug error 500 pada /query
```bash
# Lihat traceback lengkap
sudo journalctl -u rag-service -n 100 --no-pager | grep -A 30 "ERROR\|Exception"
```

### Cek apakah service listening di port yang benar
```bash
ss -tlnp | grep -E "8001|9200"
```

---

## Ingest Ulang Data

Jalankan dari direktori `/home/libraryserver/rag-service`:

```bash
cd /home/libraryserver/rag-service

# 1. Buat ulang index + search pipeline
venv/bin/python3 ingest/create_index.py

# 2. Harvest data dari DSpace OAI (simpan ke dspace_sample.json)
venv/bin/python3 ingest/harvester.py

# 3. Generate embedding + bulk index ke OpenSearch
venv/bin/python3 ingest/run_ingest.py
```

---

## Rollback ke Elasticsearch

```bash
# 1. Stop RAG service & OpenSearch
sudo systemctl stop rag-service opensearch

# 2. Start Elasticsearch
sudo systemctl start elasticsearch

# 3. Di .env: comment OS_*, uncomment ES_*
nano /home/libraryserver/rag-service/.env

# 4. Ganti file aktif dengan versi ES
cp ingest/create_index_es.py ingest/create_index.py
cp ingest/run_ingest_es.py ingest/run_ingest.py
cp retriever_es.py retriever.py

# 5. Jalankan ingest ulang lalu restart service
venv/bin/python3 ingest/create_index.py
venv/bin/python3 ingest/run_ingest.py
sudo systemctl start rag-service
```

---

## Lokasi File Penting

| File | Deskripsi |
|---|---|
| `/home/libraryserver/rag-service/.env` | Konfigurasi API key dan koneksi |
| `/home/libraryserver/rag-service/main.py` | FastAPI app & endpoint |
| `/home/libraryserver/rag-service/retriever.py` | Logic hybrid search OpenSearch |
| `/home/libraryserver/rag-service/llm.py` | Integrasi Groq LLM |
| `/home/libraryserver/rag-service/ingest/` | Script create index, harvest, ingest |
| `/etc/systemd/system/rag-service.service` | Systemd unit file |
| `/var/log/opensearch/` | Log OpenSearch |

# Project Context — UIII Library RAG Service

File ini berisi konteks lengkap project untuk melanjutkan pengerjaan di sesi berikutnya.

---

## Overview

RAG (Retrieval-Augmented Generation) service untuk UIII Library (Universitas Islam Internasional Indonesia). Menjawab pertanyaan natural language tentang koleksi perpustakaan dengan menggabungkan pencarian semantik pada metadata dan full-text PDF.

**GitHub:** `https://github.com/frendyardiansyah31/rag-discovery-service.git`
**Working dir:** `/home/libraryserver/rag-service`
**Venv:** `/home/libraryserver/rag-service/venv`

> Catatan: venv sebelumnya dibuat di `/home/librag/rag-service/` (path lama). Shebang pip sudah difix ke path baru.

---

## Infrastruktur VM

| Komponen | Detail |
|---|---|
| OS | Ubuntu 22.04, kernel 5.15.0-119 (pending upgrade ke 179) |
| RAM | 4 GB total, ~1.3 GB available |
| User app | `libraryserver` |
| Shared folder VirtualBox | `/media/sf_shared-folder-vb/` |

---

## Stack Lengkap

| Layer | Teknologi |
|---|---|
| API | FastAPI + Uvicorn, port `8001`, systemd `rag-service` |
| Search DB | OpenSearch 2.19.5, port `9200`, systemd `opensearch` |
| Cache / Broker | Redis 6.0.16, port `6379`, systemd `redis-server` |
| Task Queue | Celery 5.6.3 (worker jalan manual, belum systemd) |
| Embedding | `paraphrase-multilingual-MiniLM-L12-v2` (384-dim, CPU) |
| Reranker | `BAAI/bge-reranker-base` (CrossEncoder) — dipakai di `retriever.py` lama, belum di flow baru |
| LLM | Groq API — `llama-3.1-8b-instant` via OpenAI-compatible client |
| PDF Extract | PyMuPDF (`import fitz`) |
| Data Source | DSpace 8.1 — `https://repository.uiii.ac.id/server` |
| OAI Harvest | Sickle — `https://repository.uiii.ac.id/server/oai/request` |

---

## OpenSearch Indexes

### `library_rag_docs` (metadata index, sudah ada sejak awal)
- **200 dokumen** dari harvest OAI-PMH DSpace
- Fields: `title`, `abstract`, `author`, `subject`, `date`, `url`, `source`, `embedding`, `chunk_text`
- Pipeline: hybrid BM25 + KNN + RRF normalization (`hybrid-rrf-pipeline`)

### `repository_chunks` (PDF chunks index, dibuat di sesi ini)
- **233 chunks** dari 7 PDF yang berhasil diproses (test dengan 10 dokumen)
- Fields: `chunk_id`, `doc_id`, `title`, `source`, `page`, `section`, `chunk_text`, `embedding`
- KNN: `knn_vector`, 384-dim, nmslib, cosinesimil

---

## Arsitektur Query Flow (Terkini)

```
User query
↓
Step 1: BM25 search → library_rag_docs → top 5 kandidat doc_id
↓
Step 2: kNN search → repository_chunks → post_filter by doc_id kandidat
↓
Step 3: Prioritize chunks: methodology → results → conclusion → introduction → abstract → body
↓
Step 4: Assemble context (max ~2000 token)
   → Fallback ke abstract untuk doc yang PDF-nya belum ada di chunks index
   → notes[] ditambahkan ke response untuk doc yang fallback
↓
Step 5: Groq LLM → generate answer
↓
Step 6: Return { answer, sources, query_time_ms, notes? }
```

---

## Arsitektur PDF Pipeline

```
library_rag_docs → ambil doc_id yang belum ada di repository_chunks
↓
DSpace 8 REST API:
  1. GET /server/api/pid/find?id=hdl:{handle} → item UUID
  2. GET /server/api/core/items/{uuid}/bundles → ORIGINAL bundle UUID
  3. GET /server/api/core/bundles/{uuid}/bitstreams → PDF bitstream UUID
  4. GET /server/api/core/bitstreams/{uuid}/content → download PDF
↓
PyMuPDF extract text per halaman
  → < 500 char total → flag needs_ocr, skip
↓
Chunking: 800 token, overlap 150, section detection per halaman
↓
Batch embedding (model load sekali di worker init)
↓
Bulk index ke repository_chunks (per 50 chunks)
↓
Redis status tracking: pdf:{doc_id}:status
```

**PDF access note:** Sebagian PDF di DSpace mengembalikan `401 Unauthorized` — dokumen restricted. Pipeline handle dengan flag `failed` di Redis.

---

## Struktur File

```
rag-service/
├── main.py                    # FastAPI app — /health, /query (updated: pakai rag_query)
├── rag_query.py               # Dual-index retrieval: BM25 metadata + kNN chunks + fallback
├── llm.py                     # Groq LLM — terima context dari PDF chunks atau abstract
├── retriever.py               # (Legacy) OpenSearch hybrid retriever + CrossEncoder reranker
├── retriever_es.py            # (Legacy) Elasticsearch retriever
├── embedding_service.py       # Batch embedding, model load sekali di worker init
├── pdf_extractor.py           # PyMuPDF extract + chunking + section detection
├── celery_tasks.py            # Celery app + pdf_pipeline task + Beat schedule (02:30 WIB)
├── redis_tracker.py           # Redis status helpers (set/get/list by status)
├── test_pdf_pipeline.py       # Test pipeline tanpa Celery, 1-N docs, log ke logs/
├── start.sh                   # Launch script uvicorn
├── requirements.txt
├── .env                       # Secrets (tidak di-commit)
├── .env.example               # Template env vars
├── PLAN-pdf-pipeline.md       # Implementation plan (checklist updated)
├── CONTEXT.md                 # File ini
├── RUNBOOK.md                 # Ops runbook
├── logs/                      # Log file test pipeline (gitignored)
└── ingest/
    ├── harvester.py           # OAI-PMH harvest dari DSpace
    ├── create_index.py        # Buat index library_rag_docs + hybrid pipeline
    ├── create_chunks_index.py # Buat index repository_chunks (dibuat di sesi ini)
    ├── run_ingest.py          # Embed + bulk index ke OpenSearch
    ├── create_index_es.py     # (Legacy) Elasticsearch index
    └── run_ingest_es.py       # (Legacy) Elasticsearch ingest
```

---

## Environment Variables (`.env`)

```env
GROQ_API_KEY=...
OS_HOST=https://localhost:9200
OS_USER=admin
OS_PASSWORD=...
DSPACE_OAI_URL=https://repository.uiii.ac.id/server/oai/request
REDIS_URL=redis://localhost:6379/0          # default, belum di .env
DSPACE_SERVER_URL=https://repository.uiii.ac.id/server  # default, belum di .env
```

> `REDIS_URL` dan `DSPACE_SERVER_URL` belum ditambahkan ke `.env` dan `.env.example` — keduanya pakai nilai default di kode. Tambahkan kalau perlu custom.

---

## Services

| Service | Status | Cara Jalankan |
|---|---|---|
| `rag-service` | Systemd, auto-start | `systemctl restart rag-service` |
| `opensearch` | Systemd, auto-start | `systemctl restart opensearch` |
| `redis-server` | Systemd, auto-start | `systemctl restart redis-server` |
| Celery worker | **Manual, belum systemd** | `venv/bin/celery -A celery_tasks worker --concurrency=1 --loglevel=info` |
| Celery Beat | **Belum dijalankan** | `venv/bin/celery -A celery_tasks beat --loglevel=info` |

---

## Yang Sudah Selesai (Sesi Ini)

- [x] Phase 1 — Index `repository_chunks` dibuat di OpenSearch
- [x] Phase 2a — `redis_tracker.py`
- [x] Phase 2b — `pdf_extractor.py`
- [x] Phase 2c — `embedding_service.py`
- [x] Phase 2d — `celery_tasks.py` (DSpace 8 REST API flow)
- [x] Phase 2e — Test 10 dokumen: 7 berhasil, 3 gagal (401 restricted)
- [x] Phase 3 — `rag_query.py` dual-index + fallback
- [x] Phase 4 — `main.py` diupdate, `llm.py` diupdate
- [x] Redis installed native (apt), systemd
- [x] Dependencies baru: `pymupdf`, `celery[redis]`, `redis`, `requests`
- [x] RAG endpoint live dan tested — jawaban dari isi PDF + fallback abstract berjalan

---

## Yang Belum / Todo

- [ ] Celery worker sebagai systemd service (supaya auto-start saat reboot)
- [ ] Celery Beat dijalankan (nightly schedule jam 02:30 WIB)
- [ ] Proses full batch 200 dokumen (sekarang baru 7 dari 10 test)
- [ ] Tambah `REDIS_URL` dan `DSPACE_SERVER_URL` ke `.env.example`
- [ ] Update `README.md` dan `RUNBOOK.md` untuk mencerminkan pipeline baru
- [ ] SSH key server belum didaftarkan ke GitHub (push pakai PAT lama yang sudah direvoke)
- [ ] Reboot VM untuk apply kernel 5.15.0-179

---

## DSpace 8 REST API — Pattern yang Sudah Terkonfirmasi

```bash
# 1. Resolve handle → item UUID
GET /server/api/pid/find?id=hdl:20.500.14576/392

# 2. Get bundles → cari "ORIGINAL"
GET /server/api/core/items/{item_uuid}/bundles

# 3. Get bitstreams dari ORIGINAL bundle
GET /server/api/core/bundles/{bundle_uuid}/bitstreams

# 4. Download PDF
GET /server/api/core/bitstreams/{bitstream_uuid}/content
```

---

## Perintah Berguna

```bash
# Cek chunks terindex
curl -sk -u admin:"R@gService_2024!" https://localhost:9200/repository_chunks/_count

# Test query RAG
curl -s -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Islamic finance methodology", "top_k": 3}' | python3 -m json.tool

# Jalankan Celery worker
venv/bin/celery -A celery_tasks worker --concurrency=1 --loglevel=info

# Jalankan Celery Beat
venv/bin/celery -A celery_tasks beat --loglevel=info

# Test pipeline manual (N dokumen)
venv/bin/python test_pdf_pipeline.py --limit 20

# Cek status Redis per doc
venv/bin/python -c "from redis_tracker import get_all_failed; print(get_all_failed())"

# Lihat log test terbaru
cat logs/$(ls -t logs/ | head -1)
```

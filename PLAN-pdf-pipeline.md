# Plan: PDF Full-Text Pipeline Extension

Extend RAG pipeline agar bisa menjawab pertanyaan detail dari isi PDF (metodologi, hasil, kesimpulan) — bukan hanya dari metadata/abstract.

---

## Current State

```
VM 2 Stack:
  FastAPI + OpenSearch + Sentence Transformer (multilingual-e5-small, 384-dim)
  + Groq (llama-3.1-8b-instant) + Celery + Redis

OpenSearch index `library_rag_docs`:
  fields: id, title, author, abstract, url, source, embedding
  pipeline: hybrid BM25 + kNN + RRF normalization (sudah jalan)

Celery Beat: nightly metadata indexing (sudah configured)
```

---

## Target Architecture

```
Existing Flow:
  OAI-PMH → Metadata → OpenSearch (library_rag_docs) → RAG

New Addition:
  OAI-PMH → PDF URL → Download PDF → PyMuPDF extract
  → Cek hasil (< 500 char → flag needs_ocr, skip)
  → Chunking (800 token, overlap 150)
  → Embedding (multilingual-e5-small, 384-dim)
  → OpenSearch index: repository_chunks
  → Extended RAG query flow
```

---

## Deliverables

| File | Deskripsi |
|---|---|
| `ingest/create_chunks_index.py` | Buat OpenSearch index `repository_chunks` |
| `pdf_extractor.py` | PyMuPDF extract + chunking logic |
| `embedding_service.py` | Batch embedding, model load sekali di worker init |
| `celery_tasks.py` | Task `pdf_pipeline` + Celery Beat schedule |
| `redis_tracker.py` | Status tracking helpers |
| `rag_query.py` | Extended dual-index query flow dengan fallback |

---

## Phase 1 — OpenSearch Index `repository_chunks`

**File:** `ingest/create_chunks_index.py`

Index terpisah, tidak mengganggu `library_rag_docs`.

```json
{
  "chunk_id": "123_001",
  "doc_id": "123",
  "title": "...",
  "source": "dspace",
  "page": 12,
  "section": "methodology",
  "chunk_text": "...",
  "embedding": [384-dim vector]
}
```

Mapping:
- `chunk_id`, `doc_id`, `source`, `section` → `keyword`
- `title`, `chunk_text` → `text`
- `page` → `integer`
- `embedding` → `knn_vector`, dimension: `384`, engine: `nmslib`, space: `cosinesimil`

Settings:
- `index.knn: true`
- `knn.algo_param.ef_search: 100`

---

## Phase 2 — Celery Task: `pdf_pipeline`

**File:** `celery_tasks.py`

Dijadwalkan via Celery Beat, jalan malam setelah nightly metadata indexing selesai.

### Task Flow

```
1. Query library_rag_docs → ambil semua doc_id yang belum ada di repository_chunks
   (check by doc_id, idempotent — skip kalau sudah ada)
2. Resolve PDF URL via DSpace REST API:
   GET /rest/items/{id}/bitstreams
3. Download PDF → simpan di /tmp/{doc_id}.pdf
4. PyMuPDF (fitz) extract text per halaman
5. Cek total panjang teks:
   - < 500 char → update Redis status → "needs_ocr", skip
   - >= 500 char → lanjut ke chunking
6. Chunking: 800 token, overlap 150, per section kalau memungkinkan
7. Embedding per chunk (batched, model sudah di-load di worker init)
8. Bulk index ke repository_chunks (per 50 chunks)
9. Hapus /tmp/{doc_id}.pdf
10. Update Redis status → "embedded"
```

### Redis Status Tracking

```
Key: pdf:{doc_id}:status
Values: pending | downloaded | extracted | embedded | failed | needs_ocr
```

**File:** `redis_tracker.py` — helper `get_status`, `set_status`, `get_all_failed`

### Worker Config

```bash
celery -A celery_tasks worker --concurrency=1 --loglevel=info
```
`--concurrency=1` untuk jaga RAM VM 4GB — embedding model besar.

### Celery Beat Schedule

```python
"pdf-pipeline-nightly": {
    "task": "celery_tasks.pdf_pipeline",
    "schedule": crontab(hour=2, minute=30),  # setelah metadata indexing jam 2:00
}
```

---

## Phase 3 — Extended RAG Query Flow

**File:** `rag_query.py`

Modifikasi endpoint `/query` yang ada.

```
User query
↓
Step 1: BM25 search → library_rag_docs → dapat kandidat doc_id (top 5)
↓
Step 2: Vector search → repository_chunks → post_filter by doc_id kandidat
↓
Step 3: Prioritize chunks by section order:
         methodology → results → conclusion → introduction → abstract
↓
Step 4: Assemble context (max ~2000 token total)
↓
Step 5: Kirim ke Groq dengan system prompt akademik
↓
Step 6: Return AI summary + source attribution (doc_id, title, page, section)
```

### OpenSearch Query Pattern (Step 2)

```json
{
  "knn": {
    "embedding": { "vector": [...], "k": 20 }
  },
  "post_filter": {
    "terms": { "doc_id": ["123", "456", "789"] }
  }
}
```

---

## Phase 4 — Fallback Logic

Kalau `repository_chunks` kosong untuk doc tertentu (PDF gagal / `needs_ocr`):

```
→ Gunakan abstract dari library_rag_docs
→ Tambahkan flag di response:
  "note": "Summary based on abstract only — full text not available"
```

---

## Catatan Implementasi

```
1. Import PDF: import fitz  (install: pip install pymupdf)
2. OpenSearch client: opensearch-py — bukan elasticsearch-py
3. Embedding model: load SEKALI di worker init, bukan per task
4. Bulk index: per 50 chunks, bukan satu-satu
5. PDF storage: /tmp/ sementara, hapus setelah selesai
6. DSpace PDF URL: resolve via REST API /rest/items/{id}/bitstreams
   — bukan dari OAI-PMH langsung
7. OCR (Tesseract): defer — flag needs_ocr saja dulu
8. Test dengan 10-20 dokumen dulu sebelum full batch
9. kNN field type di OpenSearch: knn_vector (bukan dense_vector)
```

---

## Dependencies Baru

Tambah ke `requirements.txt`:

```
pymupdf
celery[redis]
redis
```

---

## Urutan Pengerjaan

- [x] **Phase 1** — Buat `ingest/create_chunks_index.py`, jalankan buat index
- [x] **Phase 2a** — Buat `redis_tracker.py`
- [x] **Phase 2b** — Buat `pdf_extractor.py` (extract + chunking)
- [x] **Phase 2c** — Buat `embedding_service.py` (batch embedding, worker init pattern)
- [x] **Phase 2d** — Buat `celery_tasks.py` (pdf_pipeline task + Beat schedule)
- [ ] **Phase 2e** — Test dengan 10-20 dokumen
- [x] **Phase 3** — Buat `rag_query.py` (extended dual-index + fallback)
- [x] **Phase 4** — Integrasi fallback ke endpoint `/query` di `main.py`
- [x] Update `requirements.txt`
- [ ] Update `README.md` dan `RUNBOOK.md`

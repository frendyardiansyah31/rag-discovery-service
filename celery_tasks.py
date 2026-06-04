import logging
import os
import tempfile

import requests
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv
from opensearchpy import OpenSearch, helpers

load_dotenv()

from pdf_extractor import extract_chunks
from embedding_service import embed_chunks
from redis_tracker import (
    set_status,
    STATUS_PENDING, STATUS_DOWNLOADED, STATUS_EXTRACTED,
    STATUS_EMBEDDED, STATUS_FAILED, STATUS_NEEDS_OCR,
)

logger = logging.getLogger(__name__)

REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DSPACE_SERVER    = os.getenv("DSPACE_SERVER_URL", "https://repository.uiii.ac.id/server")
METADATA_INDEX   = "library_rag_docs"
CHUNKS_INDEX    = "repository_chunks"
BULK_SIZE       = 50

app = Celery("rag_tasks", broker=REDIS_URL, backend=REDIS_URL)

app.conf.beat_schedule = {
    "pdf-pipeline-nightly": {
        "task": "celery_tasks.pdf_pipeline",
        # Runs at 02:30, after nightly metadata indexing at 02:00
        "schedule": crontab(hour=2, minute=30),
    },
}
app.conf.timezone = "Asia/Jakarta"


def _get_os_client() -> OpenSearch:
    return OpenSearch(
        hosts=[os.getenv("OS_HOST", "https://localhost:9200")],
        http_auth=(os.getenv("OS_USER"), os.getenv("OS_PASSWORD")),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    )


def _get_unprocessed_docs(es: OpenSearch) -> list[dict]:
    """Return docs from metadata index that have no chunks yet."""
    # Fetch all doc_ids already in chunks index
    existing = set()
    resp = es.search(
        index=CHUNKS_INDEX,
        body={"size": 0, "aggs": {"doc_ids": {"terms": {"field": "doc_id", "size": 10000}}}},
    )
    for bucket in resp["aggregations"]["doc_ids"]["buckets"]:
        existing.add(bucket["key"])

    # Fetch all docs from metadata index
    docs = []
    resp = es.search(
        index=METADATA_INDEX,
        body={"query": {"match_all": {}}, "size": 10000, "_source": ["title", "url", "source"]},
    )
    for hit in resp["hits"]["hits"]:
        doc_id = hit["_id"]
        if doc_id not in existing:
            docs.append({
                "doc_id": doc_id,
                "title":  hit["_source"].get("title", ""),
                "url":    hit["_source"].get("url", ""),
                "source": hit["_source"].get("source", "dspace"),
            })

    return docs


def _extract_handle(url: str) -> str | None:
    """Extract handle string from hdl.handle.net or /handle/ URL."""
    import re
    m = re.search(r'(?:hdl\.handle\.net|/handle)/(\d+\.\d+\.\d+/\d+)', url)
    return m.group(1) if m else None


def _resolve_pdf_url(handle_url: str) -> str | None:
    """
    Resolve PDF download URL via DSpace 8 REST API.
    Flow: handle → item UUID → ORIGINAL bundle → PDF bitstream → content URL
    """
    try:
        handle = _extract_handle(handle_url)
        if not handle:
            logger.warning(f"Cannot extract handle from URL: {handle_url}")
            return None

        # Step 1: resolve handle → item UUID
        resp = requests.get(
            f"{DSPACE_SERVER}/api/pid/find",
            params={"id": f"hdl:{handle}"},
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()
        item_uuid = resp.json()["uuid"]

        # Step 2: get bundles, find ORIGINAL
        resp = requests.get(
            f"{DSPACE_SERVER}/api/core/items/{item_uuid}/bundles",
            timeout=15,
        )
        resp.raise_for_status()
        bundles = resp.json().get("_embedded", {}).get("bundles", [])
        original_bundle = next((b for b in bundles if b["name"] == "ORIGINAL"), None)
        if not original_bundle:
            return None

        bundle_uuid = original_bundle["uuid"]

        # Step 3: get bitstreams from ORIGINAL bundle, find PDF
        resp = requests.get(
            f"{DSPACE_SERVER}/api/core/bundles/{bundle_uuid}/bitstreams",
            timeout=15,
        )
        resp.raise_for_status()
        bitstreams = resp.json().get("_embedded", {}).get("bitstreams", [])
        pdf_bs = next(
            (bs for bs in bitstreams if "pdf" in bs.get("name", "").lower()
             or "pdf" in bs.get("metadata", {}).get("dc.format", [{}])[0].get("value", "").lower()),
            None,
        )
        if not pdf_bs:
            return None

        return f"{DSPACE_SERVER}/api/core/bitstreams/{pdf_bs['uuid']}/content"

    except Exception as e:
        logger.warning(f"Failed to resolve PDF URL for {handle_url}: {e}")
    return None


def _download_pdf(pdf_url: str, dest_path: str) -> bool:
    try:
        resp = requests.get(pdf_url, timeout=60, stream=True, verify=False)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        logger.warning(f"Failed to download {pdf_url}: {e}")
        return False


def _bulk_index_chunks(es: OpenSearch, chunks: list[dict]) -> None:
    actions = [
        {"_index": CHUNKS_INDEX, "_id": c["chunk_id"], "_source": c}
        for c in chunks
    ]
    for i in range(0, len(actions), BULK_SIZE):
        batch = actions[i : i + BULK_SIZE]
        helpers.bulk(es, batch)


@app.task(name="celery_tasks.pdf_pipeline")
def pdf_pipeline():
    es = _get_os_client()
    docs = _get_unprocessed_docs(es)
    logger.info(f"pdf_pipeline: {len(docs)} docs to process")

    for doc in docs:
        doc_id = doc["doc_id"]
        title  = doc["title"]
        source = doc["source"]

        set_status(doc_id, STATUS_PENDING)

        pdf_url = _resolve_pdf_url(doc["url"])
        if not pdf_url:
            set_status(doc_id, STATUS_FAILED)
            logger.warning(f"[{doc_id}] No PDF URL found, skipping")
            continue

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            if not _download_pdf(pdf_url, tmp_path):
                set_status(doc_id, STATUS_FAILED)
                continue

            set_status(doc_id, STATUS_DOWNLOADED)

            try:
                chunks = extract_chunks(tmp_path, doc_id=doc_id, title=title, source=source)
            except ValueError as e:
                if str(e) == "needs_ocr":
                    set_status(doc_id, STATUS_NEEDS_OCR)
                    logger.info(f"[{doc_id}] Text too short, flagged needs_ocr")
                    continue
                raise

            set_status(doc_id, STATUS_EXTRACTED)

            chunks = embed_chunks(chunks)
            _bulk_index_chunks(es, chunks)

            set_status(doc_id, STATUS_EMBEDDED)
            logger.info(f"[{doc_id}] Indexed {len(chunks)} chunks")

        except Exception as e:
            set_status(doc_id, STATUS_FAILED)
            logger.error(f"[{doc_id}] Pipeline error: {e}", exc_info=True)

        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    logger.info("pdf_pipeline: done")

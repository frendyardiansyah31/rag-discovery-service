"""
Test script for PDF pipeline — runs pipeline logic directly (no Celery)
on the first N docs from library_rag_docs.

Usage:
    python test_pdf_pipeline.py [--limit 10]
"""
import argparse
import logging
import os
import sys
import tempfile
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_log_filename = os.path.join(LOG_DIR, f"pdf_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_log_filename, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)
logger.info(f"Log file: {_log_filename}")
logger = logging.getLogger(__name__)

from opensearchpy import OpenSearch, helpers
from celery_tasks import (
    _get_os_client, _get_unprocessed_docs,
    _resolve_pdf_url, _download_pdf, _bulk_index_chunks,
    CHUNKS_INDEX,
)
from pdf_extractor import extract_chunks
from embedding_service import embed_chunks
from redis_tracker import set_status, get_status, STATUS_PENDING, STATUS_DOWNLOADED, \
    STATUS_EXTRACTED, STATUS_EMBEDDED, STATUS_FAILED, STATUS_NEEDS_OCR


def run_test(limit: int = 10):
    es = _get_os_client()
    docs = _get_unprocessed_docs(es)

    if not docs:
        logger.info("No unprocessed docs found — all already indexed.")
        return

    docs = docs[:limit]
    logger.info(f"Testing pipeline on {len(docs)} docs")

    results = {"embedded": 0, "needs_ocr": 0, "failed": 0, "no_pdf": 0}

    for i, doc in enumerate(docs, 1):
        doc_id = doc["doc_id"]
        title  = doc["title"]
        source = doc["source"]
        url    = doc["url"]

        logger.info(f"[{i}/{len(docs)}] {title[:60]}...")
        set_status(doc_id, STATUS_PENDING)

        # Step 1: resolve PDF URL
        pdf_url = _resolve_pdf_url(url)
        if not pdf_url:
            logger.warning(f"  -> No PDF found, skipping")
            set_status(doc_id, STATUS_FAILED)
            results["no_pdf"] += 1
            continue

        logger.info(f"  -> PDF URL resolved")

        # Step 2: download PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            if not _download_pdf(pdf_url, tmp_path):
                set_status(doc_id, STATUS_FAILED)
                results["failed"] += 1
                continue

            size_kb = os.path.getsize(tmp_path) // 1024
            logger.info(f"  -> Downloaded {size_kb} KB")
            set_status(doc_id, STATUS_DOWNLOADED)

            # Step 3: extract chunks
            try:
                chunks = extract_chunks(tmp_path, doc_id=doc_id, title=title, source=source)
            except ValueError as e:
                if str(e) == "needs_ocr":
                    logger.info(f"  -> Text too short, needs OCR")
                    set_status(doc_id, STATUS_NEEDS_OCR)
                    results["needs_ocr"] += 1
                    continue
                raise

            logger.info(f"  -> Extracted {len(chunks)} chunks")
            set_status(doc_id, STATUS_EXTRACTED)

            # Step 4: embed
            chunks = embed_chunks(chunks)
            logger.info(f"  -> Embedded {len(chunks)} chunks")

            # Step 5: index
            _bulk_index_chunks(es, chunks)
            set_status(doc_id, STATUS_EMBEDDED)
            results["embedded"] += 1
            logger.info(f"  -> Indexed OK")

        except Exception as e:
            logger.error(f"  -> Pipeline error: {e}", exc_info=True)
            set_status(doc_id, STATUS_FAILED)
            results["failed"] += 1

        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # Summary
    total_chunks = es.count(index=CHUNKS_INDEX)["count"]
    logger.info("\n=== Test Summary ===")
    logger.info(f"  Docs tested  : {len(docs)}")
    logger.info(f"  Embedded OK  : {results['embedded']}")
    logger.info(f"  Needs OCR    : {results['needs_ocr']}")
    logger.info(f"  No PDF found : {results['no_pdf']}")
    logger.info(f"  Failed       : {results['failed']}")
    logger.info(f"  Total chunks in index: {total_chunks}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10, help="Number of docs to test")
    args = parser.parse_args()
    run_test(limit=args.limit)

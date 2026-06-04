import os
import redis
from dotenv import load_dotenv
load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_client = redis.from_url(REDIS_URL, decode_responses=True)

STATUS_PENDING     = "pending"
STATUS_DOWNLOADED  = "downloaded"
STATUS_EXTRACTED   = "extracted"
STATUS_EMBEDDED    = "embedded"
STATUS_FAILED      = "failed"
STATUS_NEEDS_OCR   = "needs_ocr"


def _key(doc_id: str) -> str:
    return f"pdf:{doc_id}:status"


def set_status(doc_id: str, status: str) -> None:
    _client.set(_key(doc_id), status)


def get_status(doc_id: str) -> str | None:
    return _client.get(_key(doc_id))


def get_all_by_status(status: str) -> list[str]:
    """Return all doc_ids that match the given status."""
    keys = _client.keys("pdf:*:status")
    return [
        k.split(":")[1]
        for k in keys
        if _client.get(k) == status
    ]


def get_all_failed() -> list[str]:
    return get_all_by_status(STATUS_FAILED)


def get_all_needs_ocr() -> list[str]:
    return get_all_by_status(STATUS_NEEDS_OCR)

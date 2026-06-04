import asyncio
import logging
import os

from dotenv import load_dotenv
load_dotenv()

from opensearchpy import AsyncOpenSearch
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

MODEL_NAME      = "paraphrase-multilingual-MiniLM-L12-v2"
METADATA_INDEX  = "library_rag_docs"
CHUNKS_INDEX    = "repository_chunks"
METADATA_POOL   = 5    # top docs from metadata search
CHUNKS_POOL     = 20   # top chunks per kNN query
MAX_CONTEXT_TOKENS = 2000

# Section priority for context assembly (lower index = higher priority)
SECTION_ORDER = ["methodology", "results", "conclusion", "discussion", "introduction", "abstract", "body"]

logger.info(f"Loading embedding model: {MODEL_NAME}")
_model = SentenceTransformer(MODEL_NAME)
_model.encode("warmup")
logger.info("Embedding model ready.")

es = AsyncOpenSearch(
    hosts=[os.getenv("OS_HOST", "https://localhost:9200")],
    http_auth=(os.getenv("OS_USER"), os.getenv("OS_PASSWORD")),
    use_ssl=True,
    verify_certs=False,
    ssl_show_warn=False,
    request_timeout=30,
)


def _approx_tokens(text: str) -> int:
    return len(text) // 4


def _section_rank(section: str) -> int:
    try:
        return SECTION_ORDER.index(section)
    except ValueError:
        return len(SECTION_ORDER)


async def _search_metadata(query: str) -> list[dict]:
    """BM25 search on metadata index, returns top doc candidates."""
    resp = await es.search(
        index=METADATA_INDEX,
        body={
            "size": METADATA_POOL,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["title^2", "abstract"],
                }
            },
            "_source": ["title", "abstract", "author", "date", "url"],
        },
    )
    return [
        {
            "doc_id":   hit["_id"],
            "title":    hit["_source"].get("title", ""),
            "abstract": hit["_source"].get("abstract", ""),
            "author":   hit["_source"].get("author", []),
            "date":     hit["_source"].get("date", ""),
            "url":      hit["_source"].get("url", ""),
        }
        for hit in resp["hits"]["hits"]
    ]


async def _search_chunks(query_vec: list[float], doc_ids: list[str]) -> list[dict]:
    """kNN search on chunks index filtered to candidate doc_ids."""
    resp = await es.search(
        index=CHUNKS_INDEX,
        body={
            "size": CHUNKS_POOL,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": query_vec,
                        "k": CHUNKS_POOL,
                    }
                }
            },
            "post_filter": {
                "terms": {"doc_id": doc_ids}
            },
            "_source": ["doc_id", "title", "chunk_text", "section", "page"],
        },
    )
    return [hit["_source"] for hit in resp["hits"]["hits"]]


def _assemble_context(chunks: list[dict], metadata_docs: list[dict], fallback_doc_ids: set[str]) -> tuple[str, list[dict], list[str]]:
    """
    Build context string from chunks (prioritized by section).
    Falls back to abstract for docs with no chunks.
    Returns (context_text, sources, notes).
    """
    # Sort chunks by section priority
    chunks_sorted = sorted(chunks, key=lambda c: _section_rank(c.get("section", "body")))

    context_parts = []
    token_count = 0
    sources = []
    seen_doc_ids = set()

    for chunk in chunks_sorted:
        text = chunk["chunk_text"]
        tokens = _approx_tokens(text)
        if token_count + tokens > MAX_CONTEXT_TOKENS:
            break
        context_parts.append(
            f"[{chunk['title']}] (p.{chunk.get('page','?')}, {chunk.get('section','body')}):\n{text}"
        )
        token_count += tokens
        doc_id = chunk["doc_id"]
        if doc_id not in seen_doc_ids:
            seen_doc_ids.add(doc_id)
            for m in metadata_docs:
                if m["doc_id"] == doc_id:
                    sources.append(m)
                    break

    # Fallback: docs with no chunks → use abstract
    notes = []
    for doc in metadata_docs:
        if doc["doc_id"] in fallback_doc_ids and doc["doc_id"] not in seen_doc_ids:
            abstract = doc.get("abstract", "").strip()
            if abstract:
                tokens = _approx_tokens(abstract)
                if token_count + tokens <= MAX_CONTEXT_TOKENS:
                    context_parts.append(f"[{doc['title']}] (abstract):\n{abstract}")
                    token_count += tokens
                    seen_doc_ids.add(doc["doc_id"])
                    sources.append(doc)
                    notes.append(
                        f"'{doc['title']}': summary based on abstract only — full text not available"
                    )

    return "\n\n".join(context_parts), sources, notes


async def retrieve_extended(query: str, top_k: int = 5) -> tuple[str, list[dict], list[str]]:
    """
    Dual-index retrieval:
      1. BM25 on metadata → candidate doc_ids
      2. kNN on chunks filtered by doc_ids
      3. Fallback to abstract for docs with no chunks
    Returns (context_text, sources, notes).
    """
    query_vec = await asyncio.to_thread(_model.encode, query)

    metadata_docs = await _search_metadata(query)
    if not metadata_docs:
        return "", [], []

    doc_ids = [d["doc_id"] for d in metadata_docs]

    chunks = await _search_chunks(query_vec.tolist(), doc_ids)

    # Doc IDs that have no chunks → fallback to abstract
    chunk_doc_ids  = {c["doc_id"] for c in chunks}
    fallback_ids   = set(doc_ids) - chunk_doc_ids

    context, sources, notes = _assemble_context(chunks, metadata_docs, fallback_ids)

    # Trim sources to top_k
    sources = sources[:top_k]

    return context, sources, notes

import asyncio
import logging
import os

from dotenv import load_dotenv
load_dotenv()

from sentence_transformers import SentenceTransformer, CrossEncoder
from elasticsearch import AsyncElasticsearch

logger = logging.getLogger(__name__)

logger.info("Loading SentenceTransformer model...")
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
logger.info("Loading CrossEncoder reranker...")
reranker = CrossEncoder("BAAI/bge-reranker-base")

model.encode("warmup")
reranker.predict([("warmup query", "warmup doc")])
logger.info("RAG models ready.")

es = AsyncElasticsearch(
    os.getenv("ES_HOST"),
    basic_auth=(os.getenv("ES_USER"), os.getenv("ES_PASSWORD")),
    verify_certs=False,
    request_timeout=30,
    retry_on_timeout=True,
)

_POOL = 20


async def retrieve(query: str, top_k: int = 5) -> list:
    vec = await asyncio.to_thread(model.encode, query)

    resp = await es.search(
        index="library_rag_docs",
        query={"multi_match": {"query": query, "fields": ["title", "abstract"]}},
        knn={"field": "embedding", "query_vector": vec.tolist(), "k": _POOL, "num_candidates": 100},
        size=_POOL,
    )

    hits = resp["hits"]["hits"]
    pairs = [(query, f"{h['_source']['title']} {h['_source']['abstract']}") for h in hits]
    scores = await asyncio.to_thread(reranker.predict, pairs)

    reranked = sorted(zip(scores, hits), key=lambda x: x[0], reverse=True)

    return [
        {
            "title": h["_source"]["title"],
            "abstract": h["_source"]["abstract"],
            "author": h["_source"].get("author", []),
            "date": h["_source"].get("date", ""),
            "url": h["_source"].get("url", ""),
            "score": round(float(s), 3),
        }
        for s, h in reranked[:top_k]
    ]

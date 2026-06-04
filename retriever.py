import asyncio
import logging
import os

from dotenv import load_dotenv
load_dotenv()

from sentence_transformers import SentenceTransformer, CrossEncoder
from opensearchpy import AsyncOpenSearch

logger = logging.getLogger(__name__)

logger.info("Loading SentenceTransformer model...")
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
logger.info("Loading CrossEncoder reranker...")
reranker = CrossEncoder("BAAI/bge-reranker-base")

model.encode("warmup")
reranker.predict([("warmup query", "warmup doc")])
logger.info("RAG models ready.")

es = AsyncOpenSearch(
    hosts=[os.getenv("OS_HOST", "https://localhost:9200")],
    http_auth=(os.getenv("OS_USER"), os.getenv("OS_PASSWORD")),
    use_ssl=True,
    verify_certs=False,
    ssl_show_warn=False,
    request_timeout=30,
)

_POOL = 20


async def retrieve(query: str, top_k: int = 5) -> list:
    vec = await asyncio.to_thread(model.encode, query)

    body = {
        "size": _POOL,
        "query": {
            "hybrid": {
                "queries": [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["title^2", "abstract"],
                        }
                    },
                    {
                        "knn": {
                            "embedding": {
                                "vector": vec.tolist(),
                                "k": _POOL,
                            }
                        }
                    },
                ]
            }
        },
    }

    resp = await es.search(
        index="library_rag_docs",
        body=body,
        params={"search_pipeline": "hybrid-rrf-pipeline"},
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

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from retriever import es, retrieve
from llm import generate_answer


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await es.close()


app = FastAPI(title="UIII Library RAG Service", version="1.0.0", lifespan=lifespan)


class QueryRequest(BaseModel):
    query: str
    top_k: int = 5


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/query")
async def rag_query(req: QueryRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query required")

    t0 = time.time()
    sources = await retrieve(query, top_k=req.top_k)
    answer = await generate_answer(query, sources)

    return {
        "answer": answer,
        "sources": sources,
        "query_time_ms": int((time.time() - t0) * 1000),
    }

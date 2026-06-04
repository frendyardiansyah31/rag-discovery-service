import logging
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
BATCH_SIZE = 32

# Loaded once at module import (worker init), not per task
logger.info(f"Loading embedding model: {MODEL_NAME}")
_model = SentenceTransformer(MODEL_NAME)
_model.encode("warmup")
logger.info("Embedding model ready.")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts in batches. Returns list of 384-dim vectors."""
    vectors = _model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_chunks(chunks: list[dict]) -> list[dict]:
    """Add 'embedding' field to each chunk dict in-place and return the list."""
    texts = [c["chunk_text"] for c in chunks]
    vectors = embed_texts(texts)
    for chunk, vec in zip(chunks, vectors):
        chunk["embedding"] = vec
    return chunks

from dotenv import load_dotenv
load_dotenv()

import os
from elasticsearch import Elasticsearch

es = Elasticsearch(
    os.getenv("ES_HOST"),
    basic_auth=(os.getenv("ES_USER"), os.getenv("ES_PASSWORD")),
    verify_certs=False,
)

mapping = {
    "mappings": {
        "properties": {
            "title":      {"type": "text"},
            "abstract":   {"type": "text"},
            "author":     {"type": "keyword"},
            "subject":    {"type": "keyword"},
            "date":       {"type": "date", "format": "yyyy||yyyy-MM||yyyy-MM-dd"},
            "url":        {"type": "keyword"},
            "chunk_text": {"type": "text"},
            "source":     {"type": "keyword"},
            "embedding":  {"type": "dense_vector", "dims": 384, "index": True, "similarity": "cosine"},
        }
    }
}

es.indices.create(index="library_rag_docs", body=mapping)
print("Index created.")

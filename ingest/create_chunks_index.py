from dotenv import load_dotenv
load_dotenv()

import os
from opensearchpy import OpenSearch

es = OpenSearch(
    hosts=[os.getenv("OS_HOST", "https://localhost:9200")],
    http_auth=(os.getenv("OS_USER"), os.getenv("OS_PASSWORD")),
    use_ssl=True,
    verify_certs=False,
    ssl_show_warn=False,
)

INDEX = "repository_chunks"

if es.indices.exists(index=INDEX):
    es.indices.delete(index=INDEX)
    print(f"Deleted existing index '{INDEX}'")

mapping = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 100,
        }
    },
    "mappings": {
        "properties": {
            "chunk_id":   {"type": "keyword"},
            "doc_id":     {"type": "keyword"},
            "title":      {"type": "text"},
            "source":     {"type": "keyword"},
            "page":       {"type": "integer"},
            "section":    {"type": "keyword"},
            "chunk_text": {"type": "text"},
            "embedding": {
                "type": "knn_vector",
                "dimension": 384,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "nmslib",
                    "parameters": {"ef_construction": 128, "m": 16},
                },
            },
        }
    },
}

es.indices.create(index=INDEX, body=mapping)
print(f"Index '{INDEX}' created.")

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

INDEX = "library_rag_docs"

# Delete existing index if any
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
            "title":      {"type": "text"},
            "abstract":   {"type": "text"},
            "author":     {"type": "keyword"},
            "subject":    {"type": "keyword"},
            "date":       {"type": "date", "format": "yyyy||yyyy-MM||yyyy-MM-dd"},
            "url":        {"type": "keyword"},
            "chunk_text": {"type": "text"},
            "source":     {"type": "keyword"},
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

# Create hybrid BM25+KNN search pipeline with RRF normalization
pipeline = {
    "description": "Hybrid BM25 + KNN with RRF normalization",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "rrf"},
                "combination": {"technique": "arithmetic_mean"},
            }
        }
    ],
}

es.transport.perform_request(
    "PUT",
    "/_search/pipeline/hybrid-rrf-pipeline",
    body=pipeline,
)
print("Search pipeline 'hybrid-rrf-pipeline' created (BM25 + KNN + RRF).")

from dotenv import load_dotenv
load_dotenv()

import json
import os
from sentence_transformers import SentenceTransformer
from elasticsearch import Elasticsearch, helpers

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
es = Elasticsearch(
    os.getenv("ES_HOST"),
    basic_auth=(os.getenv("ES_USER"), os.getenv("ES_PASSWORD")),
    verify_certs=False,
)

with open("dspace_sample.json") as f:
    docs = json.load(f)


def gen_actions(docs):
    for doc in docs:
        chunk = f"{doc['title']}. {doc['abstract']}"
        vec = model.encode(chunk).tolist()
        yield {
            "_index": "library_rag_docs",
            "_source": {**doc, "chunk_text": chunk, "embedding": vec},
        }


helpers.bulk(es, gen_actions(docs))
print(f"Indexed {len(docs)} docs")

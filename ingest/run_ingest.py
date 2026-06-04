from dotenv import load_dotenv
load_dotenv()

import json
import os
from sentence_transformers import SentenceTransformer
from opensearchpy import OpenSearch, helpers

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

es = OpenSearch(
    hosts=[os.getenv("OS_HOST", "https://localhost:9200")],
    http_auth=(os.getenv("OS_USER"), os.getenv("OS_PASSWORD")),
    use_ssl=True,
    verify_certs=False,
    ssl_show_warn=False,
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
print(f"Indexed {len(docs)} docs into OpenSearch.")

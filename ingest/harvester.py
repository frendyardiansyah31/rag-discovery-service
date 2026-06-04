from dotenv import load_dotenv
load_dotenv()

import json
import os
from sickle import Sickle


def extract_url(identifiers: list) -> str:
    for x in identifiers:
        if "handle" in x:
            return x
    for x in identifiers:
        if x.startswith("http"):
            return x
    return ""


def harvest_dspace(max_records: int = 200) -> list:
    sickle = Sickle(os.getenv("DSPACE_OAI_URL"))
    records = sickle.ListRecords(metadataPrefix="oai_dc")
    results = []

    for i, rec in enumerate(records):
        if i >= max_records:
            break
        try:
            m = rec.metadata
            results.append({
                "title": " ".join(m.get("title", [""])),
                "abstract": " ".join(m.get("description", [""])),
                "author": m.get("creator", []),
                "subject": m.get("subject", []),
                "date": m.get("date", [""])[0][:4],
                "url": extract_url(m.get("identifier", [])),
                "source": "dspace",
            })
            print(f"Harvested {i+1}")
        except Exception as e:
            print(f"Error record {i}: {e}")

    return results


if __name__ == "__main__":
    data = harvest_dspace(200)
    with open("dspace_sample.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Harvested {len(data)} records")

import json
import sqlite3
from pathlib import Path

job_id = "8skxo"

conn = sqlite3.connect("data/jobs.sqlite")
conn.row_factory = sqlite3.Row
rows = [dict(row) for row in conn.execute("select * from jobs where job_id=?", (job_id,))]
print("DB")
print(json.dumps(rows, ensure_ascii=False, indent=2))

paths = [
    "outputs/ai-curated-candidates.json",
    "outputs/ai-collect-results.json",
    "outputs/next-confirm-candidates.json",
    "outputs/next-confirm-candidates-2.json",
    "outputs/next-confirm-candidates-3.json",
    "outputs/next-confirm-candidates-4.json",
    "outputs/next-confirm-candidates-5.json",
    "outputs/next-live-check-results.json",
    "outputs/next-live-check-results-2.json",
    "outputs/apply-results-live.json",
    "outputs/batch-next-submit-results.json",
    "outputs/batch-next2-submit-results.json",
    "outputs/batch-next3-submit-results.json",
    "outputs/batch22-submit-results.json",
    "outputs/batch18-submit-results.json",
]


def walk(value, found):
    if isinstance(value, dict):
        if value.get("job_id") == job_id or value.get("id") == job_id or value.get("jobNo") == job_id:
            found.append(value)
        for child in value.values():
            walk(child, found)
    elif isinstance(value, list):
        for child in value:
            walk(child, found)


for path_name in paths:
    path = Path(path_name)
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    if job_id not in text:
        continue
    found = []
    walk(json.loads(text), found)
    print(f"FOUND_IN {path_name} count={len(found)}")
    for item in found:
        print(json.dumps(item, ensure_ascii=False, indent=2))

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "jobs.sqlite"
QUEUE_PATH = ROOT / "outputs" / "review-needed-audit-queue.json"


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    status_counts = conn.execute(
        "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status ORDER BY status"
    ).fetchall()
    error_counts = conn.execute(
        """
        SELECT error, COUNT(*) AS count
        FROM jobs
        WHERE status = 'review_needed'
        GROUP BY error
        ORDER BY count DESC
        """
    ).fetchall()
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT job_id, company_name, job_title, job_url, status, reason, error, updated_at
            FROM jobs
            WHERE status = 'review_needed'
            ORDER BY updated_at DESC
            """
        )
    ]

    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("STATUS_COUNTS")
    for row in status_counts:
        print(tuple(row))
    print("ERROR_COUNTS")
    for row in error_counts:
        print(tuple(row))
    print("QUEUE", len(rows))
    print("SAMPLE")
    for row in rows[:8]:
        print(row)


if __name__ == "__main__":
    main()

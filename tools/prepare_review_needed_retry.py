import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "jobs.sqlite"
RETRY_QUEUE_PATH = ROOT / "outputs" / "review-needed-retry-queue.json"

EXTRA_ANSWER_ERRORS = {
    "Apply form had more than one textarea / extra unknown field; not submitted automatically",
    "unknown_extra_question_detected",
}


def now_taipei() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT job_id, company_name, job_title, job_url, status, reason, error, cover_letter
            FROM jobs
            WHERE status = 'review_needed'
            ORDER BY updated_at DESC
            """
        )
    ]

    ts = now_taipei()
    extra_count = 0
    retry_rows = []

    for row in rows:
        error = row.get("error") or ""
        if error in EXTRA_ANSWER_ERRORS:
            reason = f"需額外回答內容；原始原因：{error}"
            conn.execute(
                """
                UPDATE jobs
                SET error = ?, reason = ?, updated_at = ?
                WHERE job_id = ?
                """,
                ("EXTRA_ANSWER_REQUIRED", reason, ts, row["job_id"]),
            )
            extra_count += 1
            continue

        retry_rows.append(
            {
                "job_id": row["job_id"],
                "company_name": row["company_name"],
                "job_title": row["job_title"],
                "job_url": row["job_url"],
                "original_error": error,
                "cover_letter": row.get("cover_letter") or "",
            }
        )

    conn.commit()
    RETRY_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RETRY_QUEUE_PATH.write_text(
        json.dumps(retry_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"extra_answer_required_updated={extra_count}")
    print(f"retry_queue={len(retry_rows)}")
    print(RETRY_QUEUE_PATH)


if __name__ == "__main__":
    main()

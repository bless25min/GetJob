import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "jobs.sqlite"
RESULTS_PATH = ROOT / "outputs" / "review-needed-retry-results.json"


def now_taipei() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def main() -> None:
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    conn = sqlite3.connect(DB_PATH)
    ts = now_taipei()

    counts: dict[tuple[str, str], int] = {}
    for result in results:
        job_id = result["job_id"]
        status = result.get("status") or "review_needed"
        error = result.get("error") or ""
        note = result.get("note") or ""

        if error == "RETRY_AUTOMATION_ERROR":
            status = "review_needed"
            error = "RETRY_CONTROL_FAILED"
            note = "Chrome 控制環境在補跑期間重置，未完成分類；需下次再重試。"

        reason = note if note else None
        applied_at = ts if status in {"applied", "already_applied"} else None

        if applied_at:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, reason = ?, applied_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, error, reason, applied_at, ts, job_id),
            )
        else:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, reason = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, error, reason, ts, job_id),
            )

        counts[(status, error or "OK")] = counts.get((status, error or "OK"), 0) + 1

    conn.commit()

    for key, count in sorted(counts.items()):
        print(f"{key[0]}\t{key[1]}\t{count}")


if __name__ == "__main__":
    main()

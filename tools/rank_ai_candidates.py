import json
import sqlite3
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main


JSON_PATH = ROOT / "outputs" / "ai-strict-candidates.json"

AI_TERMS = [
    "ai",
    "生成式",
    "genai",
    "llm",
    "rag",
    "agent",
    "chatgpt",
    "claude",
    "mcp",
    "人工智慧",
    "機器學習",
]

FIT_TERMS = [
    "顧問",
    "導入",
    "產品",
    "專案",
    "pm",
    "project manager",
    "product manager",
    "saas",
    "售前",
    "pre-sales",
    "客戶成功",
    "customer success",
    "需求",
    "訪談",
    "教育訓練",
    "知識庫",
    "流程",
    "自動化",
    "數位轉型",
    "營運",
    "martech",
    "數據",
]

NEGATIVE_TERMS = [
    "韌體",
    "硬體",
    "driver",
    "kernel",
    "電路",
    "ic",
    "嵌入式",
    "影像辨識",
    "computer vision",
    "演算法研究",
    "博士",
    "研究員",
    "senior ai engineer",
]


def has_any(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def rank(row: sqlite3.Row) -> dict | None:
    title = main.safe_text(row["job_title"])
    full_text = main.safe_text(row["full_text"])
    keyword = main.safe_text(row["keyword"])
    text = f"{title}\n{full_text}"
    all_text = f"{text}\n{keyword}"

    if not has_any(text, AI_TERMS):
        return None

    score = 58
    reasons: list[str] = []

    title_lower = title.lower()
    text_lower = all_text.lower()

    ai_hits = [term for term in AI_TERMS if term.lower() in text_lower]
    fit_hits = [term for term in FIT_TERMS if term.lower() in text_lower]
    negative_hits = [term for term in NEGATIVE_TERMS if term.lower() in text_lower]

    score += min(18, len(ai_hits) * 4)
    score += min(24, len(fit_hits) * 3)
    score -= min(30, len(negative_hits) * 10)

    if any(term in title_lower for term in ["ai", "生成式", "llm", "rag", "agent", "人工智慧"]):
        score += 10
        reasons.append("職稱明確 AI 相關")
    if any(term in title_lower for term in ["顧問", "導入", "售前", "客戶成功"]):
        score += 8
        reasons.append("接近 B2B 顧問/導入/客戶成功")
    if any(term in title_lower for term in ["產品", "專案", "pm"]):
        score += 8
        reasons.append("符合產品或專案管理方向")
    if any(term in text_lower for term in ["知識庫", "rag", "agent", "流程", "自動化", "教育訓練"]):
        score += 7
        reasons.append("貼近企業 AI 落地場景")
    if negative_hits:
        reasons.append("含偏工程研究訊號，需人工確認")

    score = max(0, min(100, score))
    if score < 70:
        return None

    return {
        "job_id": row["job_id"],
        "company_name": row["company_name"],
        "job_title": row["job_title"],
        "job_url": row["job_url"],
        "keyword": row["keyword"],
        "location": row["location"],
        "status": row["status"],
        "score": score,
        "reason": "；".join(reasons) or "職缺文字明確含 AI 且符合顧問/PM/導入方向",
    }


def main_cli() -> None:
    conn = sqlite3.connect(ROOT / "data" / "jobs.sqlite")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT job_id, company_name, job_title, job_url, keyword, location, status, full_text
        FROM jobs
        WHERE status = 'found'
        """
    ).fetchall()

    candidates = [candidate for row in rows if (candidate := rank(row))]
    candidates.sort(key=lambda item: (-item["score"], item["company_name"], item["job_title"]))
    JSON_PATH.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    for item in candidates:
        conn.execute(
            """
            UPDATE jobs
            SET score = ?, reason = ?, cover_letter_angle = ?, updated_at = CURRENT_TIMESTAMP
            WHERE job_id = ?
            """,
            (
                item["score"],
                item["reason"],
                "AI 導入 / B2B 顧問 / PM 經驗切入",
                item["job_id"],
            ),
        )
    conn.commit()

    print(f"strict_ai_candidates={len(candidates)}")
    for index, item in enumerate(candidates[:30], start=1):
        print(
            f"{index}. {item['score']} {item['job_title']}｜{item['company_name']}｜"
            f"{item['location']}｜{item['job_url']}｜{item['reason']}"
        )
    print(JSON_PATH)


if __name__ == "__main__":
    main_cli()

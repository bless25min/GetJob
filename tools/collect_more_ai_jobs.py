import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main


OUTPUT_PATH = Path("outputs/ai-job-candidates.json")

KEYWORDS = [
    "AI 產品顧問",
    "AI 導入顧問",
    "AI 應用顧問",
    "AI 專案經理",
    "生成式 AI 顧問",
    "生成式 AI PM",
    "LLM 顧問",
    "RAG 顧問",
    "AI Agent PM",
    "AI Agent 顧問",
    "SaaS 顧問",
    "SaaS 導入顧問",
    "售前顧問 AI",
    "客戶成功 AI",
    "產品顧問 AI",
    "數位轉型顧問 AI",
    "流程自動化 顧問",
    "企業 AI 導入",
]

HIGH_SIGNAL_TERMS = [
    "ai",
    "生成式",
    "llm",
    "rag",
    "agent",
    "chatgpt",
    "導入",
    "顧問",
    "產品",
    "專案",
    "pm",
    "saas",
    "客戶成功",
    "售前",
    "流程",
    "自動化",
    "知識庫",
    "mcp",
]

PROFILE_SIGNAL_TERMS = [
    "b2b",
    "c-level",
    "企業",
    "數位轉型",
    "營運",
    "需求訪談",
    "需求分析",
    "教育訓練",
    "成效追蹤",
    "martech",
    "數據",
    "crm",
    "行銷",
    "workflow",
    "automation",
]

NEGATIVE_TERMS = [
    "韌體",
    "硬體",
    "driver",
    "kernel",
    "演算法研究",
    "電路",
    "ic",
    "嵌入式",
    "影像辨識",
    "computer vision",
    "博士",
    "研究員",
]


def score_candidate(job: dict) -> tuple[int, str]:
    title = main.safe_text(job.get("job_title")).lower()
    text = main.safe_text(job.get("full_text") or main.make_full_text(job)).lower()
    haystack = f"{title}\n{text}"

    score = 45
    reasons: list[str] = []

    for term in HIGH_SIGNAL_TERMS:
        if term.lower() in haystack:
            score += 4
    for term in PROFILE_SIGNAL_TERMS:
        if term.lower() in haystack:
            score += 3
    for term in NEGATIVE_TERMS:
        if term.lower() in haystack:
            score -= 12

    title_bonus_terms = ["顧問", "產品", "專案", "pm", "導入", "ai", "saas"]
    title_hits = [term for term in title_bonus_terms if term in title]
    score += min(18, len(title_hits) * 3)

    if "ai" in title or "生成式" in title or "llm" in title:
        reasons.append("職稱明確含 AI/生成式 AI/LLM")
    if "顧問" in title or "導入" in title:
        reasons.append("職務接近 AI 導入顧問")
    if "產品" in title or "pm" in title or "專案" in title:
        reasons.append("符合產品/專案管理方向")
    if "saas" in haystack or "客戶成功" in haystack or "售前" in haystack:
        reasons.append("貼近 B2B SaaS/售前/客戶成功")
    if any(term.lower() in haystack for term in NEGATIVE_TERMS):
        reasons.append("含偏工程研究或硬體訊號，需人工確認")

    score = max(0, min(100, score))
    return score, "；".join(reasons) or "AI/PM/顧問相關關鍵字命中"


def main_cli() -> None:
    main.ensure_dirs()
    main.ensure_db()
    config = main.load_config()
    search_config = dict(config.get("search", {}))
    search_config["keywords"] = KEYWORDS
    search_config["pages_per_keyword"] = 3
    search_config["pagesize"] = 20
    search_config["max_jobs_per_keyword"] = 60
    search_config["order"] = "date"
    search_config["isnew_days"] = 30
    search_config["fetch_details"] = False
    config["search"] = search_config

    delay = float(config.get("limits", {}).get("request_delay_seconds", 1.5))
    inserted = 0
    duplicate = 0
    failed: list[dict] = []
    candidates: list[dict] = []

    for keyword in KEYWORDS:
        keyword_count = 0
        for page in range(1, int(search_config["pages_per_keyword"]) + 1):
            try:
                items = main.fetch_104_jobs(keyword, page, config)
            except Exception as exc:
                failed.append({"keyword": keyword, "page": page, "error": str(exc)})
                continue

            for item in items:
                if keyword_count >= int(search_config["max_jobs_per_keyword"]):
                    break
                job = main.search_item_to_job(item, keyword)
                if not job.get("job_id"):
                    continue
                if main.db_get_job(job["job_id"]) or main.db_get_job_by_url(job["job_url"]):
                    duplicate += 1
                    continue
                job["full_text"] = main.make_full_text(job)
                score, reason = score_candidate(job)
                job["score"] = score
                job["reason"] = reason
                job["cover_letter_angle"] = "AI 導入 / B2B 顧問 / PM 經驗切入"
                job["status"] = "found"
                main.db_upsert_job(job)
                inserted += 1
                keyword_count += 1
                if score >= 70:
                    candidates.append(
                        {
                            "job_id": job["job_id"],
                            "company_name": job["company_name"],
                            "job_title": job["job_title"],
                            "job_url": job["job_url"],
                            "keyword": keyword,
                            "location": job["location"],
                            "score": score,
                            "reason": reason,
                        }
                    )
                time.sleep(delay)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidates.sort(key=lambda item: (-int(item["score"]), item["company_name"], item["job_title"]))
    OUTPUT_PATH.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"inserted={inserted}")
    print(f"duplicate={duplicate}")
    print(f"candidates_score_70_plus={len(candidates)}")
    print(f"failed={len(failed)}")
    if failed:
        print(json.dumps(failed, ensure_ascii=False, indent=2))
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main_cli()

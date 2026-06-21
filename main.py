import argparse
import json
import os
import re
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass


DB_PATH = Path("data/jobs.sqlite")
AUTH_STATE_PATH = Path("auth/auth_104.json")
SCREENSHOT_DIR = Path("outputs/screenshots")
LETTER_DIR = Path("outputs/letters")
DASHBOARD_PATH = Path("outputs/applications-dashboard.html")
DEFAULT_BROWSER_PROFILE_DIR = Path("auth/chrome-profile")
APP_TIMEZONE = "Asia/Taipei"
CDP_CONTEXT_IDS: set[int] = set()
SEARCH_API_URL = "https://www.104.com.tw/jobs/search/api/jobs"
SEARCH_ORDER_CODES = {
    "relevance": "15",
    "date": "16",
    "salary": "13",
    "views": "2",
    "14": "16",
}

STATUSES = [
    "found",
    "skipped",
    "letter_ready",
    "apply_ready",
    "applying",
    "applied",
    "failed",
    "review_needed",
    "already_applied",
]

DASHBOARD_STATUS_ORDER = {
    "applied": 0,
    "review_needed": 1,
    "failed": 2,
    "already_applied": 3,
    "skipped": 4,
    "applying": 5,
    "apply_ready": 6,
    "letter_ready": 7,
    "found": 8,
}

JOB_COLUMNS = [
    "job_id",
    "company_name",
    "job_title",
    "job_url",
    "keyword",
    "location",
    "salary_text",
    "description",
    "requirement",
    "skills",
    "full_text",
    "score",
    "reason",
    "cover_letter_angle",
    "cover_letter",
    "status",
    "error",
    "screenshot_path",
    "letter_path",
    "applied_at",
]

APPLY_BUTTON_TEXTS = ["我要應徵", "應徵", "立即應徵", "主動應徵"]
SUBMIT_BUTTON_TEXTS = ["送出", "確認送出", "確定應徵", "送出應徵", "完成應徵", "立即應徵"]
ALREADY_APPLIED_TEXTS = ["已應徵", "已投遞", "已主動應徵", "已經應徵"]
LOGIN_REQUIRED_TEXTS = ["會員登入", "請先登入", "登入會員"]
BLOCKING_TEXTS = ["驗證碼", "人機驗證", "安全驗證", "二階段驗證", "簡訊驗證", "帳號安全"]
QUESTION_TEXTS = ["額外問題", "應徵問答", "請回答", "問答題"]
SUCCESS_TEXTS = ["應徵成功", "已送出", "已應徵", "已投遞", "送出成功"]
TEXTAREA_SELECTORS = ["textarea", "[contenteditable='true']", "div[role='textbox']"]
STOP_APPLY_ERRORS = {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "TWO_FA_REQUIRED"}


def get_now_iso() -> str:
    return datetime.now(get_app_timezone()).isoformat(timespec="seconds")


def today_prefix() -> str:
    return datetime.now(get_app_timezone()).date().isoformat()


def get_app_timezone() -> Any:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        return None
    try:
        return ZoneInfo(APP_TIMEZONE)
    except Exception:
        return None


def resolve_db_path(db_path: Path | str | None = None) -> Path:
    return Path(DB_PATH if db_path is None else db_path)


def ensure_dirs() -> None:
    for path in [Path("auth"), Path("data"), SCREENSHOT_DIR, LETTER_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def ensure_db(db_path: Path | str | None = None) -> None:
    db_path = resolve_db_path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                company_name TEXT,
                job_title TEXT,
                job_url TEXT UNIQUE,
                keyword TEXT,
                location TEXT,
                salary_text TEXT,
                description TEXT,
                requirement TEXT,
                skills TEXT,
                full_text TEXT,
                score INTEGER,
                reason TEXT,
                cover_letter_angle TEXT,
                cover_letter TEXT,
                status TEXT,
                error TEXT,
                screenshot_path TEXT,
                letter_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                applied_at TEXT
            )
            """
        )
        conn.commit()


def db_connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(resolve_db_path(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def db_get_job(job_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with closing(db_connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return row_to_dict(row)


def db_get_job_by_url(job_url: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with closing(db_connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_url = ?", (job_url,)).fetchone()
    return row_to_dict(row)


def db_upsert_job(job: dict[str, Any], db_path: Path | str | None = None) -> bool:
    if not job.get("job_id"):
        raise ValueError("job_id is required")

    db_path = resolve_db_path(db_path)
    values = {column: job.get(column) for column in JOB_COLUMNS}
    values["status"] = values.get("status") or "found"
    placeholders = ", ".join("?" for _ in JOB_COLUMNS)
    update_clause = ", ".join(f"{column} = ?" for column in JOB_COLUMNS if column != "created_at")
    insert_sql = f"""
        INSERT INTO jobs ({", ".join(JOB_COLUMNS)})
        VALUES ({placeholders})
        ON CONFLICT(job_id) DO UPDATE SET {", ".join(
            f"{column} = excluded.{column}" for column in JOB_COLUMNS if column not in {"job_id"}
        )}, updated_at = CURRENT_TIMESTAMP
    """

    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        before = conn.total_changes
        try:
            conn.execute(insert_sql, [values[column] for column in JOB_COLUMNS])
            conn.commit()
            return conn.total_changes > before
        except sqlite3.IntegrityError:
            existing = conn.execute(
                "SELECT job_id FROM jobs WHERE job_url = ? LIMIT 1",
                (values["job_url"],),
            ).fetchone()
            if not existing:
                raise
            existing_job_id = existing["job_id"]
            update_values = [values[column] for column in JOB_COLUMNS if column != "job_id"]
            conn.execute(
                f"""
                UPDATE jobs
                SET {update_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                [values[column] for column in JOB_COLUMNS if column != "created_at"] + [existing_job_id],
            )
            if existing_job_id != values["job_id"]:
                conn.execute(
                    "UPDATE jobs SET job_id = ? WHERE job_id = ?",
                    (values["job_id"], existing_job_id),
                )
            conn.commit()
            return conn.total_changes > before


def db_update_job(job_id: str, db_path: Path | str | None = None, **fields: Any) -> None:
    allowed = set(JOB_COLUMNS) - {"job_id"}
    clean = {key: value for key, value in fields.items() if key in allowed}
    assignments = [f"{key} = ?" for key in clean]
    values = list(clean.values())
    assignments.append("updated_at = CURRENT_TIMESTAMP")

    with closing(sqlite3.connect(resolve_db_path(db_path))) as conn:
        conn.execute(
            f"UPDATE jobs SET {', '.join(assignments)} WHERE job_id = ?",
            [*values, job_id],
        )
        conn.commit()


def db_get_jobs_by_status(status: str, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with closing(db_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at ASC",
            (status,),
        ).fetchall()
    return [dict(row) for row in rows]


def db_status_counts(db_path: Path | str | None = None) -> dict[str, int]:
    ensure_db(db_path)
    counts = {status: 0 for status in STATUSES}
    with closing(db_connect(db_path)) as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status").fetchall()
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] = int(row["count"])
    return counts


def dashboard_job_rows(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    ensure_db(db_path)
    with closing(db_connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT
                job_id,
                company_name,
                job_title,
                job_url,
                keyword,
                location,
                salary_text,
                score,
                status,
                error,
                reason,
                cover_letter_angle,
                applied_at,
                updated_at
            FROM jobs
            ORDER BY
                CASE status
                    WHEN 'applied' THEN 0
                    WHEN 'review_needed' THEN 1
                    WHEN 'failed' THEN 2
                    WHEN 'already_applied' THEN 3
                    WHEN 'skipped' THEN 4
                    WHEN 'applying' THEN 5
                    WHEN 'apply_ready' THEN 6
                    WHEN 'letter_ready' THEN 7
                    WHEN 'found' THEN 8
                    ELSE 9
                END,
                COALESCE(applied_at, updated_at, '') DESC,
                company_name ASC,
                job_title ASC
            """
        ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def dashboard_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {status: 0 for status in STATUSES}
    for row in rows:
        status = safe_text(row.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return {
        "total": len(rows),
        "statuses": counts,
    }


def json_for_html(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("</", "<\\/")
    )


def render_dashboard_html(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> str:
    generated_at = generated_at or get_now_iso()
    data_json = json_for_html(rows)
    summary_json = json_for_html(summary)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>104 投遞紀錄</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #1d2430;
      --muted: #657080;
      --line: #d9dee7;
      --green: #137a4a;
      --amber: #9a5b00;
      --red: #b42318;
      --blue: #2357b8;
      --gray: #5d6673;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, "Noto Sans TC", "Microsoft JhengHei", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      padding: 24px 28px 12px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 24px;
      line-height: 1.25;
      letter-spacing: 0;
    }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
    }}
    main {{
      padding: 18px 28px 32px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }}
    .stat {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
    }}
    .stat strong {{
      display: block;
      font-size: 24px;
      line-height: 1.1;
      margin-top: 4px;
    }}
    .stat span {{
      color: var(--muted);
      font-size: 13px;
    }}
    .toolbar {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      margin-bottom: 12px;
    }}
    input, select {{
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      padding: 0 11px;
      font-size: 14px;
    }}
    input {{
      flex: 1 1 280px;
      min-width: 220px;
    }}
    select {{
      flex: 0 0 190px;
    }}
    .count {{
      color: var(--muted);
      font-size: 13px;
      margin-left: auto;
    }}
    .table-wrap {{
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    table {{
      width: 100%;
      min-width: 980px;
      border-collapse: collapse;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
      line-height: 1.35;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #eef1f5;
      color: #333b48;
      font-size: 12px;
      text-transform: uppercase;
      z-index: 1;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    a {{
      color: var(--blue);
      text-decoration: none;
      font-weight: 700;
    }}
    a:hover {{ text-decoration: underline; }}
    .status {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 3px 9px;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .status-applied {{ color: var(--green); background: #e9f6ef; }}
    .status-review_needed {{ color: var(--amber); background: #fff4df; }}
    .status-skipped {{ color: var(--gray); background: #eef0f3; }}
    .status-failed {{ color: var(--red); background: #fdebea; }}
    .status-other {{ color: var(--blue); background: #eaf0ff; }}
    .muted {{ color: var(--muted); }}
    .reason {{
      max-width: 360px;
      word-break: break-word;
    }}
    @media (max-width: 760px) {{
      header, main {{ padding-left: 14px; padding-right: 14px; }}
      h1 {{ font-size: 21px; }}
      .count {{ width: 100%; margin-left: 0; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>104 投遞紀錄</h1>
    <div class="meta">產生時間：{generated_at}</div>
  </header>
  <main>
    <section class="stats" id="stats"></section>
    <section class="toolbar">
      <input id="search-input" type="search" placeholder="搜尋公司、職稱、地點、原因">
      <select id="status-filter" aria-label="狀態篩選">
        <option value="all">全部狀態</option>
        <option value="applied">已投遞</option>
        <option value="review_needed">需人工處理</option>
        <option value="skipped">已略過</option>
        <option value="failed">失敗</option>
      </select>
      <div class="count" id="result-count"></div>
    </section>
    <section class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>狀態</th>
            <th>職稱</th>
            <th>公司</th>
            <th>地點</th>
            <th>來源關鍵字</th>
            <th>時間</th>
            <th>原因</th>
            <th>連結</th>
          </tr>
        </thead>
        <tbody id="jobs-body"></tbody>
      </table>
    </section>
  </main>
  <script>
    const applicationsData = {data_json};
    const dashboardSummary = {summary_json};
    const statusLabels = {{
      applied: "已投遞",
      review_needed: "需人工處理",
      skipped: "已略過",
      failed: "失敗",
      already_applied: "已投過",
      found: "未處理",
      letter_ready: "自介信已備妥",
      apply_ready: "待投遞",
      applying: "投遞中"
    }};
    const statusClass = (status) => {{
      if (["applied", "review_needed", "skipped", "failed"].includes(status)) return `status-${{status}}`;
      return "status-other";
    }};
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({{
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\\"": "&quot;",
      "'": "&#39;"
    }}[char]));
    const formatReason = (job) => job.error || job.reason || job.cover_letter_angle || "";
    const formatTime = (job) => job.applied_at || job.updated_at || "";
    const searchableText = (job) => [
      job.company_name,
      job.job_title,
      job.location,
      job.keyword,
      job.status,
      formatReason(job)
    ].join(" ").toLowerCase();
    function renderStats() {{
      const stats = [
        ["總數", dashboardSummary.total],
        ["已投遞", dashboardSummary.statuses.applied || 0],
        ["需人工處理", dashboardSummary.statuses.review_needed || 0],
        ["已略過", dashboardSummary.statuses.skipped || 0]
      ];
      document.getElementById("stats").innerHTML = stats.map(([label, value]) => `
        <div class="stat"><span>${{escapeHtml(label)}}</span><strong>${{escapeHtml(value)}}</strong></div>
      `).join("");
    }}
    function renderRows() {{
      const query = document.getElementById("search-input").value.trim().toLowerCase();
      const status = document.getElementById("status-filter").value;
      const filtered = applicationsData.filter((job) => {{
        const statusMatch = status === "all" || job.status === status;
        const queryMatch = !query || searchableText(job).includes(query);
        return statusMatch && queryMatch;
      }});
      document.getElementById("result-count").textContent = `顯示 ${{filtered.length}} / ${{applicationsData.length}} 筆`;
      document.getElementById("jobs-body").innerHTML = filtered.map((job) => `
        <tr>
          <td><span class="status ${{statusClass(job.status)}}">${{escapeHtml(statusLabels[job.status] || job.status)}}</span></td>
          <td><strong>${{escapeHtml(job.job_title || "(未命名職缺)")}}</strong><div class="muted">${{escapeHtml(job.job_id)}}</div></td>
          <td>${{escapeHtml(job.company_name)}}</td>
          <td>${{escapeHtml(job.location)}}</td>
          <td>${{escapeHtml(job.keyword)}}</td>
          <td>${{escapeHtml(formatTime(job))}}</td>
          <td class="reason">${{escapeHtml(formatReason(job))}}</td>
          <td>${{job.job_url ? `<a href="${{escapeHtml(job.job_url)}}" target="_blank" rel="noopener noreferrer">104</a>` : ""}}</td>
        </tr>
      `).join("");
    }}
    renderStats();
    renderRows();
    document.getElementById("search-input").addEventListener("input", renderRows);
    document.getElementById("status-filter").addEventListener("change", renderRows);
  </script>
</body>
</html>
"""


def write_dashboard(
    output_path: Path | str | None = None,
    db_path: Path | str | None = None,
) -> str:
    rows = dashboard_job_rows(db_path)
    summary = dashboard_summary(rows)
    path = Path(output_path) if output_path else DASHBOARD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_dashboard_html(rows, summary), encoding="utf-8")
    return str(path)


def db_count_applied_today(db_path: Path | str | None = None) -> int:
    with closing(db_connect(db_path)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM jobs WHERE status = 'applied' AND substr(applied_at, 1, 10) = ?",
            (today_prefix(),),
        ).fetchone()
    return int(row["count"]) if row else 0


def db_company_applied_today(company_name: str, db_path: Path | str | None = None) -> int:
    with closing(db_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM jobs
            WHERE status = 'applied'
              AND company_name = ?
              AND substr(applied_at, 1, 10) = ?
            """,
            (company_name, today_prefix()),
        ).fetchone()
    return int(row["count"]) if row else 0


def load_yaml(path: str | Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is not installed. Run: pip install -r requirements.txt") from exc

    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    return load_yaml(path)


def load_profile(path: str | Path = "profile.md") -> str:
    with open(path, "r", encoding="utf-8") as file:
        return file.read()


def browser_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("browser", {}) if isinstance(config.get("browser", {}), dict) else {}


def browser_cdp_endpoint(config: dict[str, Any]) -> str:
    endpoint = browser_config(config).get("cdp_endpoint") or browser_config(config).get("connect_over_cdp")
    return str(endpoint).strip() if endpoint else ""


def browser_uses_cdp(config: dict[str, Any]) -> bool:
    return bool(browser_cdp_endpoint(config))


def browser_uses_persistent_context(config: dict[str, Any]) -> bool:
    options = browser_config(config)
    return not browser_uses_cdp(config) and bool(options.get("use_persistent_context") or options.get("user_data_dir"))


def browser_user_data_dir(config: dict[str, Any]) -> Path:
    configured = browser_config(config).get("user_data_dir")
    return Path(configured) if configured else DEFAULT_BROWSER_PROFILE_DIR


def auth_ready(config: dict[str, Any]) -> bool:
    return AUTH_STATE_PATH.exists() or browser_uses_persistent_context(config) or browser_uses_cdp(config)


def browser_launch_options(config: dict[str, Any], *, force_headless: bool | None = None) -> dict[str, Any]:
    mode = config.get("mode", {})
    options = browser_config(config)
    launch_options: dict[str, Any] = {
        "headless": bool(mode.get("headless", False)) if force_headless is None else force_headless,
        "slow_mo": int(mode.get("slow_mo_ms", 300)),
    }
    channel = options.get("channel")
    if channel:
        launch_options["channel"] = channel
    return launch_options


def open_browser_context(playwright: Any, config: dict[str, Any], *, for_login: bool = False) -> tuple[Any, Any | None]:
    cdp_endpoint = browser_cdp_endpoint(config)
    if cdp_endpoint:
        browser = playwright.chromium.connect_over_cdp(cdp_endpoint)
        if not browser.contexts:
            raise RuntimeError("Connected Chrome has no browser context. Open Chrome with a normal profile first.")
        context = browser.contexts[0]
        CDP_CONTEXT_IDS.add(id(context))
        return context, browser

    if browser_uses_persistent_context(config):
        user_data_dir = browser_user_data_dir(config)
        user_data_dir.mkdir(parents=True, exist_ok=True)
        context = playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            **browser_launch_options(config, force_headless=False if for_login else None),
        )
        return context, None

    browser = playwright.chromium.launch(
        **browser_launch_options(config, force_headless=False if for_login else None)
    )
    if for_login:
        return browser.new_context(), browser
    return browser.new_context(storage_state=str(AUTH_STATE_PATH)), browser


def close_browser_context(context: Any, browser: Any | None) -> None:
    if id(context) in CDP_CONTEXT_IDS:
        CDP_CONTEXT_IDS.discard(id(context))
        return

    context.close()
    if browser is not None:
        browser.close()


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(safe_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(safe_text(item) for item in value.values())
    return str(value)


def strip_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_job_id(url_or_id: str) -> str:
    text = (url_or_id or "").strip()
    if not text:
        return ""
    match = re.search(r"/job/([0-9a-zA-Z]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"/job/ajax/content/([0-9a-zA-Z]+)", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[0-9a-zA-Z]+", text):
        return text
    return ""


def normalize_job_url(url_or_id: str) -> str:
    job_id = extract_job_id(url_or_id)
    if not job_id:
        return url_or_id.strip()
    return f"https://www.104.com.tw/job/{job_id}"


def make_full_text(job: dict[str, Any]) -> str:
    fields = [
        "company_name",
        "job_title",
        "location",
        "salary_text",
        "description",
        "requirement",
        "skills",
    ]
    return "\n".join(safe_text(job.get(field)) for field in fields if safe_text(job.get(field))).strip()


def contains_any(text: str, keywords: list[str] | None) -> bool:
    if not keywords:
        return False
    text_lower = safe_text(text).lower()
    return any(safe_text(keyword).lower() in text_lower for keyword in keywords if safe_text(keyword).strip())


def location_allowed(location: str, allowed_locations: list[str] | None) -> bool:
    if not allowed_locations:
        return True
    location_text = safe_text(location)
    if not location_text:
        return False
    return any(safe_text(item) in location_text or location_text in safe_text(item) for item in allowed_locations)


def rule_filter(job: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str]:
    filters = config.get("filters", {})
    title = safe_text(job.get("job_title"))
    full_text = safe_text(job.get("full_text")) or make_full_text(job)
    location = safe_text(job.get("location"))

    if contains_any(title, filters.get("reject_title_keywords", [])):
        return False, "RULE_REJECTED_TITLE"
    if contains_any(full_text, filters.get("reject_text_keywords", [])):
        return False, "RULE_REJECTED_TEXT"
    if not location_allowed(location, filters.get("allowed_locations", [])):
        return False, "RULE_REJECTED_LOCATION"
    return True, ""


def extract_json(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM_JSON_PARSE_FAILED")
    return json.loads(text[start : end + 1])


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def resolve_llm_settings(config: dict[str, Any]) -> dict[str, Any]:
    load_dotenv_if_available()
    llm = config.get("llm", {})
    settings = {
        "api_key": llm.get("api_key") or os.getenv("OPENAI_API_KEY", ""),
        "base_url": llm.get("base_url") or os.getenv("OPENAI_BASE_URL", ""),
        "model": llm.get("model") or os.getenv("OPENAI_MODEL", ""),
        "temperature": llm.get("temperature", 0.4),
        "max_tokens": llm.get("max_tokens", 1200),
    }
    if not settings["api_key"] or not settings["model"]:
        raise RuntimeError("LLM_NOT_CONFIGURED")
    return settings


def has_llm_settings(config: dict[str, Any]) -> bool:
    try:
        resolve_llm_settings(config)
        return True
    except RuntimeError:
        return False


def get_llm_client(config: dict[str, Any]):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai is not installed. Run: pip install -r requirements.txt") from exc

    settings = resolve_llm_settings(config)
    if settings["base_url"]:
        return OpenAI(api_key=settings["api_key"], base_url=settings["base_url"])
    return OpenAI(api_key=settings["api_key"])


def llm_score_job(job: dict[str, Any], profile: str, config: dict[str, Any]) -> dict[str, Any]:
    settings = resolve_llm_settings(config)
    client = get_llm_client(config)
    prompt = f"""
你是求職適配度評估器。請根據求職者 profile 與職缺內容，輸出嚴格 JSON。

限制：
- 不要捏造經歷。
- 若職缺偏純工程、資料科學、模型訓練、C++、韌體、資安，應降低分數或 apply=false。
- score 為 0 到 100 的整數。

JSON schema：
{{
  "apply": true,
  "score": 86,
  "reason": "繁體中文，2 到 4 句",
  "cover_letter_angle": "推薦信應強調的角度"
}}

求職者 profile：
{profile}

職缺：
公司：{job.get("company_name", "")}
職缺：{job.get("job_title", "")}
地點：{job.get("location", "")}
薪資：{job.get("salary_text", "")}
內容：
{job.get("full_text") or make_full_text(job)}
""".strip()
    response = client.chat.completions.create(
        model=settings["model"],
        temperature=settings["temperature"],
        max_tokens=settings["max_tokens"],
        messages=[
            {"role": "system", "content": "你只輸出可解析的 JSON，不輸出 markdown。"},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or ""
    result = extract_json(content)
    result["score"] = int(result.get("score", 0))
    result["apply"] = bool(result.get("apply", False))
    result["reason"] = safe_text(result.get("reason"))
    result["cover_letter_angle"] = safe_text(result.get("cover_letter_angle"))
    return result


def llm_write_cover_letter(
    job: dict[str, Any],
    profile: str,
    match: dict[str, Any],
    config: dict[str, Any],
) -> str:
    settings = resolve_llm_settings(config)
    client = get_llm_client(config)
    letter_config = config.get("letter", {})
    required_sentence = letter_config.get("required_sentence", "")
    prompt = f"""
請寫一封繁體中文自我推薦信。

硬性限制：
- 真誠、直接、不油膩、不像罐頭信。
- 必須對應該職缺需求。
- 不誇大能力、不捏造經歷。
- 不自稱純工程師、資料科學家、AI 研究員。
- 不聲稱具備深度模型訓練能力。
- 字數目標 {letter_config.get("target_chars_min", 350)} 到 {letter_config.get("target_chars_max", 550)} 字。
- 必須自然包含這一句：{required_sentence}

求職者 profile：
{profile}

職缺：
公司：{job.get("company_name", "")}
職缺：{job.get("job_title", "")}
內容：
{job.get("full_text") or make_full_text(job)}

適配判斷：
分數：{match.get("score")}
原因：{match.get("reason")}
推薦信角度：{match.get("cover_letter_angle")}
""".strip()
    response = client.chat.completions.create(
        model=settings["model"],
        temperature=settings["temperature"],
        max_tokens=settings["max_tokens"],
        messages=[
            {"role": "system", "content": "你只輸出推薦信正文，不要輸出標題或 markdown。"},
            {"role": "user", "content": prompt},
        ],
    )
    return (response.choices[0].message.content or "").strip()


def validate_cover_letter(letter: str, config: dict[str, Any]) -> tuple[bool, str]:
    letter_config = config.get("letter", {})
    letter = safe_text(letter).strip()
    min_chars = int(letter_config.get("min_chars", 0))
    max_chars = int(letter_config.get("max_chars", 99999))
    required_sentence = letter_config.get("required_sentence", "")

    if required_sentence and required_sentence not in letter:
        return False, "INVALID_COVER_LETTER_REQUIRED_SENTENCE"
    if len(letter) < min_chars:
        return False, "INVALID_COVER_LETTER_TOO_SHORT"
    if len(letter) > max_chars:
        return False, "INVALID_COVER_LETTER_TOO_LONG"
    for phrase in letter_config.get("forbidden_phrases", []):
        if phrase and phrase in letter:
            return False, "INVALID_COVER_LETTER_FORBIDDEN_PHRASE"
    return True, ""


def sanitize_filename(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\r\n]+', "_", safe_text(value))
    value = re.sub(r"\s+", "_", value).strip("._ ")
    return value[:80] or "unknown"


def save_letter(job: dict[str, Any], letter: str, base_dir: Path = LETTER_DIR) -> str:
    base_dir.mkdir(parents=True, exist_ok=True)
    company = sanitize_filename(job.get("company_name", "company"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = base_dir / f"{sanitize_filename(job.get('job_id', 'job'))}_{company}_{timestamp}.txt"
    content = "\n".join(
        [
            f"公司：{job.get('company_name', '')}",
            f"職缺：{job.get('job_title', '')}",
            f"網址：{job.get('job_url', '')}",
            f"分數：{job.get('score', '')}",
            f"原因：{job.get('reason', '')}",
            "",
            "推薦信：",
            letter,
        ]
    )
    path.write_text(content, encoding="utf-8")
    return str(path)


def pass_policy(
    job: dict[str, Any],
    config: dict[str, Any],
    applied_this_run: int,
    companies_applied_this_run: set[str],
    db_path: Path | str | None = None,
) -> tuple[bool, str]:
    mode = config.get("mode", {})
    limits = config.get("limits", {})
    dry_run = bool(mode.get("dry_run", True))

    if not job.get("job_id"):
        return False, "MISSING_JOB_ID"
    if not job.get("job_url"):
        return False, "MISSING_JOB_URL"
    if not dry_run and not bool(mode.get("auto_apply_enabled", False)):
        return False, "AUTO_APPLY_DISABLED"

    score = int(job.get("score") or 0)
    if score < int(limits.get("score_threshold", 0)):
        return False, "SCORE_BELOW_THRESHOLD"

    valid, reason = validate_cover_letter(job.get("cover_letter", ""), config)
    if not valid:
        return False, reason

    existing = db_get_job(job["job_id"], db_path)
    if existing and existing.get("status") in {"applied", "already_applied"}:
        return False, "ALREADY_APPLIED"

    existing_url = db_get_job_by_url(job["job_url"], db_path)
    if existing_url and existing_url.get("job_id") != job["job_id"]:
        return False, "ALREADY_APPLIED"

    if not dry_run and applied_this_run >= int(limits.get("max_apply_per_run", 1)):
        return False, "RUN_LIMIT_REACHED"
    if not dry_run and db_count_applied_today(db_path) >= int(limits.get("max_apply_per_day", 1)):
        return False, "DAILY_LIMIT_REACHED"

    company_name = safe_text(job.get("company_name"))
    if company_name in companies_applied_this_run:
        return False, "COMPANY_RUN_LIMIT_REACHED"
    if company_name and db_company_applied_today(company_name, db_path) >= int(
        limits.get("max_apply_per_company_per_day", 1)
    ):
        return False, "COMPANY_DAILY_LIMIT_REACHED"

    return True, ""


def build_headers(referer: str = "https://www.104.com.tw/") -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


def normalize_search_order(value: Any) -> str:
    key = safe_text(value or "relevance").lower()
    return SEARCH_ORDER_CODES.get(key, key if key.isdigit() else SEARCH_ORDER_CODES["relevance"])


def extract_104_search_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", [])
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("list", [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def fetch_104_jobs(keyword: str, page: int, config: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests is not installed. Run: pip install -r requirements.txt") from exc

    search = config.get("search", {})
    area_codes = search.get("area_codes", [])
    params = {
        "ro": "0",
        "kwop": "7",
        "keyword": keyword,
        "expansionType": "area,spec,com,job,wf,wktm",
        "order": normalize_search_order(search.get("order", "relevance")),
        "asc": "0",
        "page": str(page),
        "pagesize": str(search.get("pagesize", 20)),
        "mode": "s",
        "jobsource": "joblist_search",
    }
    if area_codes:
        params["area"] = ",".join(safe_text(area) for area in area_codes if safe_text(area))
    if search.get("isnew_days"):
        params["isnew"] = str(search.get("isnew_days"))
    referer = f"https://www.104.com.tw/jobs/search/?keyword={quote(keyword)}"

    with requests.Session() as session:
        session.headers.update(build_headers(referer))
        response = session.get(SEARCH_API_URL, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()

    return extract_104_search_items(payload)


def search_item_to_job(item: dict[str, Any], keyword: str) -> dict[str, Any]:
    link = item.get("link") if isinstance(item.get("link"), dict) else {}
    raw_url = link.get("job") or item.get("jobUrl") or item.get("job_url") or item.get("jobNo") or ""
    job_url = normalize_job_url(raw_url)
    job_id = extract_job_id(job_url or safe_text(item.get("jobNo")))
    return {
        "job_id": job_id,
        "company_name": item.get("custName") or item.get("companyName") or "",
        "job_title": item.get("jobName") or item.get("jobTitle") or "",
        "job_url": normalize_job_url(job_id or job_url),
        "keyword": keyword,
        "location": item.get("jobAddrNoDesc") or item.get("location") or "",
        "salary_text": item.get("salaryDesc") or "",
        "description": strip_html(safe_text(item.get("description"))),
        "requirement": "",
        "skills": "",
        "status": "found",
        "error": "",
    }


def fetch_104_job_detail(job_id: str, job_url: str) -> dict[str, Any]:
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("httpx is not installed. Run: pip install -r requirements.txt") from exc

    url = f"https://www.104.com.tw/job/ajax/content/{job_id}"
    with httpx.Client(timeout=20, headers=build_headers(job_url)) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()

    data = payload.get("data", {})
    header = data.get("header", {})
    detail = data.get("jobDetail", {})
    condition = data.get("condition", {})
    specialty = condition.get("specialty", [])
    if isinstance(specialty, list):
        skills = "、".join(
            safe_text(item.get("description") or item.get("specialty")) if isinstance(item, dict) else safe_text(item)
            for item in specialty
        )
    else:
        skills = safe_text(specialty)

    requirement_parts = [
        condition.get("workExp"),
        condition.get("edu"),
        condition.get("major"),
        condition.get("language"),
        condition.get("other"),
    ]
    job = {
        "company_name": header.get("custName") or "",
        "job_title": header.get("jobName") or "",
        "location": detail.get("addressRegion") or detail.get("addressArea") or "",
        "salary_text": detail.get("salary") or "",
        "description": strip_html(safe_text(detail.get("jobDescription"))),
        "requirement": strip_html(" ".join(safe_text(part) for part in requirement_parts if safe_text(part))),
        "skills": skills,
    }
    job["full_text"] = make_full_text(job)
    return job


def command_collect(args: argparse.Namespace) -> int:
    ensure_dirs()
    ensure_db()
    config = load_config()
    search = config.get("search", {})
    keywords = search.get("keywords", [])
    pages_per_keyword = int(search.get("pages_per_keyword", 1))
    max_jobs_per_keyword = int(search.get("max_jobs_per_keyword", 20))
    fetch_details = bool(search.get("fetch_details", False))
    delay = float(config.get("limits", {}).get("request_delay_seconds", 1.5))

    inserted = 0
    skipped = 0
    for keyword in keywords:
        keyword_count = 0
        for page in range(1, pages_per_keyword + 1):
            if keyword_count >= max_jobs_per_keyword:
                break
            try:
                items = fetch_104_jobs(keyword, page, config)
            except Exception as exc:
                print(f"[collect] {keyword} page {page}: FETCH_SEARCH_FAILED {exc}")
                continue

            for item in items:
                if keyword_count >= max_jobs_per_keyword:
                    break
                job = search_item_to_job(item, keyword)
                if not job.get("job_id"):
                    skipped += 1
                    continue
                if db_get_job(job["job_id"]) or db_get_job_by_url(job["job_url"]):
                    skipped += 1
                    continue
                if fetch_details:
                    try:
                        detail = fetch_104_job_detail(job["job_id"], job["job_url"])
                        job.update({key: value for key, value in detail.items() if value})
                    except Exception as exc:
                        job["error"] = f"FETCH_DETAIL_FAILED: {exc}"
                job["full_text"] = make_full_text(job)
                db_upsert_job(job)
                inserted += 1
                keyword_count += 1
                time.sleep(delay)

    print(f"collect completed: inserted={inserted}, skipped={skipped}")
    return 0


def command_score(args: argparse.Namespace) -> int:
    ensure_dirs()
    ensure_db()
    config = load_config()
    profile = load_profile()
    jobs = db_get_jobs_by_status("found")
    scored = 0
    skipped = 0
    review_needed = 0
    llm_ready = has_llm_settings(config)

    warned_no_llm = False
    for job in jobs:
        job["full_text"] = job.get("full_text") or make_full_text(job)
        allowed, reason = rule_filter(job, config)
        if not allowed:
            db_update_job(job["job_id"], status="skipped", error=reason)
            skipped += 1
            continue

        if not llm_ready:
            if not warned_no_llm:
                print("LLM_NOT_CONFIGURED: set config.yaml llm values or .env before scoring matching jobs.")
                warned_no_llm = True
            continue

        try:
            match = llm_score_job(job, profile, config)
        except ValueError as exc:
            db_update_job(job["job_id"], status="review_needed", error=str(exc))
            review_needed += 1
            continue
        except Exception as exc:
            db_update_job(job["job_id"], status="review_needed", error=f"LLM_SCORE_FAILED: {exc}")
            review_needed += 1
            continue

        threshold = int(config.get("limits", {}).get("score_threshold", 0))
        if not match.get("apply") or int(match.get("score", 0)) < threshold:
            db_update_job(
                job["job_id"],
                status="skipped",
                score=match.get("score"),
                reason=match.get("reason"),
                cover_letter_angle=match.get("cover_letter_angle"),
                error="SCORE_BELOW_THRESHOLD",
            )
            skipped += 1
            continue

        try:
            letter = llm_write_cover_letter(job, profile, match, config)
        except Exception as exc:
            db_update_job(
                job["job_id"],
                status="review_needed",
                score=match.get("score"),
                reason=match.get("reason"),
                cover_letter_angle=match.get("cover_letter_angle"),
                error=f"LLM_LETTER_FAILED: {exc}",
            )
            review_needed += 1
            continue

        letter_job = {**job, **match}
        letter_path = save_letter(letter_job, letter)
        valid, validation_error = validate_cover_letter(letter, config)
        if not valid:
            db_update_job(
                job["job_id"],
                status="review_needed",
                score=match.get("score"),
                reason=match.get("reason"),
                cover_letter_angle=match.get("cover_letter_angle"),
                cover_letter=letter,
                letter_path=letter_path,
                error=validation_error,
            )
            review_needed += 1
            continue

        db_update_job(
            job["job_id"],
            status="letter_ready",
            score=match.get("score"),
            reason=match.get("reason"),
            cover_letter_angle=match.get("cover_letter_angle"),
            cover_letter=letter,
            letter_path=letter_path,
            error="",
        )
        scored += 1

    print(f"score completed: letter_ready={scored}, skipped={skipped}, review_needed={review_needed}")
    return 0


def save_screenshot(page: Any, job_id: str, label: str) -> str:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOT_DIR / f"{sanitize_filename(job_id)}_{sanitize_filename(label)}_{timestamp}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def page_contains_any(page: Any, texts: list[str]) -> bool:
    try:
        body_text = page.locator("body").inner_text(timeout=3000)
    except Exception:
        return False
    return contains_any(body_text, texts)


def click_first_visible_text(page: Any, texts: list[str]) -> bool:
    for text in texts:
        locators = [
            page.get_by_role("button", name=re.compile(re.escape(text))),
            page.get_by_role("link", name=re.compile(re.escape(text))),
            page.get_by_text(text, exact=False),
        ]
        for locator in locators:
            try:
                count = min(locator.count(), 5)
                for index in range(count):
                    item = locator.nth(index)
                    if item.is_visible(timeout=1000):
                        item.click(timeout=5000)
                        return True
            except Exception:
                continue
    return False


def fill_cover_letter(page: Any, letter: str) -> tuple[bool, str]:
    candidates = []
    for selector in TEXTAREA_SELECTORS:
        try:
            locator = page.locator(selector)
            for index in range(locator.count()):
                item = locator.nth(index)
                if item.is_visible(timeout=1000):
                    candidates.append(item)
        except Exception:
            continue

    if not candidates:
        return False, "COVER_LETTER_INPUT_NOT_FOUND"
    if len(candidates) > 1:
        return False, "MULTIPLE_TEXTAREA_UNCLEAR"

    candidates[0].fill(letter, timeout=5000)
    return True, ""


def apply_with_playwright(job: dict[str, Any], config: dict[str, Any]) -> tuple[str, str, str | None]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return "failed", f"PLAYWRIGHT_NOT_INSTALLED: {exc}", None

    if not auth_ready(config):
        return "failed", "AUTH_STATE_NOT_FOUND", None

    page = None
    context = None
    browser = None
    screenshot_path = None
    mode = config.get("mode", {})
    dry_run = bool(mode.get("dry_run", True))

    try:
        with sync_playwright() as p:
            context, browser = open_browser_context(p, config)
            page = context.new_page()
            page.goto(job["job_url"], wait_until="domcontentloaded", timeout=30000)

            if "login" in page.url.lower() or page_contains_any(page, LOGIN_REQUIRED_TEXTS):
                screenshot_path = save_screenshot(page, job["job_id"], "login_required")
                close_browser_context(context, browser)
                return "failed", "LOGIN_REQUIRED", screenshot_path
            if page_contains_any(page, ["二階段驗證", "簡訊驗證"]):
                screenshot_path = save_screenshot(page, job["job_id"], "two_fa")
                close_browser_context(context, browser)
                return "failed", "TWO_FA_REQUIRED", screenshot_path
            if page_contains_any(page, BLOCKING_TEXTS):
                screenshot_path = save_screenshot(page, job["job_id"], "captcha")
                close_browser_context(context, browser)
                return "failed", "CAPTCHA_DETECTED", screenshot_path
            if page_contains_any(page, ALREADY_APPLIED_TEXTS):
                screenshot_path = save_screenshot(page, job["job_id"], "already_applied")
                close_browser_context(context, browser)
                return "already_applied", "ALREADY_APPLIED", screenshot_path

            if not click_first_visible_text(page, APPLY_BUTTON_TEXTS):
                screenshot_path = save_screenshot(page, job["job_id"], "error_apply_button")
                close_browser_context(context, browser)
                return "review_needed", "APPLY_BUTTON_NOT_FOUND", screenshot_path

            page.wait_for_timeout(1500)
            if page_contains_any(page, BLOCKING_TEXTS):
                screenshot_path = save_screenshot(page, job["job_id"], "captcha_after_click")
                close_browser_context(context, browser)
                return "failed", "CAPTCHA_DETECTED", screenshot_path
            if page_contains_any(page, QUESTION_TEXTS):
                screenshot_path = save_screenshot(page, job["job_id"], "question_form")
                close_browser_context(context, browser)
                return "review_needed", "UNKNOWN_MODAL", screenshot_path

            filled, fill_error = fill_cover_letter(page, job.get("cover_letter", ""))
            if not filled:
                screenshot_path = save_screenshot(page, job["job_id"], "error_no_textarea")
                close_browser_context(context, browser)
                return "review_needed", fill_error, screenshot_path

            screenshot_path = save_screenshot(page, job["job_id"], "dry_run" if dry_run else "before_submit")

            if dry_run:
                if not bool(mode.get("headless", False)):
                    input("dry_run 已填入推薦信但尚未送出。請檢查瀏覽器畫面，回到 terminal 按 Enter 關閉瀏覽器...")
                close_browser_context(context, browser)
                return "apply_ready", "", screenshot_path

            if not click_first_visible_text(page, SUBMIT_BUTTON_TEXTS):
                screenshot_path = save_screenshot(page, job["job_id"], "error_no_submit")
                close_browser_context(context, browser)
                return "review_needed", "SUBMIT_BUTTON_NOT_FOUND", screenshot_path

            page.wait_for_timeout(3000)
            screenshot_path = save_screenshot(page, job["job_id"], "submitted")
            if page_contains_any(page, SUCCESS_TEXTS):
                close_browser_context(context, browser)
                return "applied", "", screenshot_path

            close_browser_context(context, browser)
            return "review_needed", "SUBMIT_RESULT_UNKNOWN", screenshot_path
    except PlaywrightTimeoutError:
        if page is not None:
            try:
                screenshot_path = save_screenshot(page, job["job_id"], "playwright_timeout")
            except Exception:
                screenshot_path = None
        return "failed", "PLAYWRIGHT_TIMEOUT", screenshot_path
    except Exception as exc:
        if page is not None:
            try:
                screenshot_path = save_screenshot(page, job["job_id"], "failed_unknown")
            except Exception:
                screenshot_path = None
        return "failed", f"FAILED_UNKNOWN: {exc}", screenshot_path


def command_login(args: argparse.Namespace) -> int:
    ensure_dirs()
    config = load_config()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Run: pip install -r requirements.txt")
        return 1

    mode = config.get("mode", {})
    with sync_playwright() as p:
        context, browser = open_browser_context(p, config, for_login=True)
        page = context.new_page()
        page.goto("https://www.104.com.tw/", wait_until="domcontentloaded")
        input("請在瀏覽器完成 104 登入。完成後回到 terminal 按 Enter 保存登入狀態...")
        context.storage_state(path=str(AUTH_STATE_PATH))
        close_browser_context(context, browser)
    print("已保存登入狀態到 auth/auth_104.json。此檔案包含敏感 cookie，請勿提交 Git。")
    return 0


def command_apply(args: argparse.Namespace) -> int:
    ensure_dirs()
    ensure_db()
    config = load_config()
    if not auth_ready(config):
        print("找不到 auth/auth_104.json，請先執行 python main.py login")
        return 1

    dry_run = bool(config.get("mode", {}).get("dry_run", True))
    statuses_to_process = ["letter_ready"] if dry_run else ["letter_ready", "apply_ready"]
    ready_jobs: list[dict[str, Any]] = []
    seen_job_ids: set[str] = set()
    for status_name in statuses_to_process:
        for job in db_get_jobs_by_status(status_name):
            if job["job_id"] in seen_job_ids:
                continue
            seen_job_ids.add(job["job_id"])
            ready_jobs.append(job)
    applied_this_run = 0
    processed_this_run = 0
    companies_applied_this_run: set[str] = set()
    max_per_run = int(config.get("limits", {}).get("max_apply_per_run", 1))

    for job in ready_jobs:
        if dry_run and processed_this_run >= max_per_run:
            break

        allowed, reason = pass_policy(
            job,
            config,
            applied_this_run=applied_this_run,
            companies_applied_this_run=companies_applied_this_run,
        )
        if not allowed:
            db_update_job(job["job_id"], status="skipped", error=reason)
            continue

        db_update_job(job["job_id"], status="applying", error="")
        status, error, screenshot_path = apply_with_playwright(job, config)
        update_fields: dict[str, Any] = {
            "status": status,
            "error": error,
            "screenshot_path": screenshot_path,
        }
        if status == "applied":
            update_fields["applied_at"] = get_now_iso()
            applied_this_run += 1
            companies_applied_this_run.add(job.get("company_name", ""))
        if status == "apply_ready":
            processed_this_run += 1
        db_update_job(job["job_id"], **update_fields)

        if error in STOP_APPLY_ERRORS:
            print(f"apply stopped: {error}")
            break
        if applied_this_run >= max_per_run:
            break

    print(f"apply completed: applied={applied_this_run}, dry_run_processed={processed_this_run}")
    return 0


def fixed_letter(config: dict[str, Any]) -> str:
    required = config.get("letter", {}).get("required_sentence", "")
    return (
        "您好，我想應徵這個職缺。我的背景偏向 AI 工具導入、流程自動化、營運與專案管理，"
        "會用務實的方式協助團隊把需求拆成可執行、可追蹤的流程。"
        f"{required}"
        "這封訊息是 dry_run 測試用內容，目的是確認推薦信欄位填寫位置正確。"
    )


def command_apply_one(args: argparse.Namespace) -> int:
    ensure_dirs()
    ensure_db()
    config = load_config()
    job_id = extract_job_id(args.url)
    job_url = normalize_job_url(args.url)
    if not job_id:
        print("無法從 URL 解析 job_id")
        return 1

    job = {
        "job_id": job_id,
        "job_url": job_url,
        "company_name": "",
        "job_title": "",
        "keyword": "apply-one",
        "location": "",
        "salary_text": "",
        "description": "",
        "requirement": "",
        "skills": "",
        "status": "letter_ready",
        "score": 100,
        "reason": "apply-one fixed-letter test" if args.fixed_letter else "",
        "cover_letter_angle": "",
        "cover_letter": fixed_letter(config) if args.fixed_letter else "",
        "error": "",
    }
    try:
        detail = fetch_104_job_detail(job_id, job_url)
        job.update({key: value for key, value in detail.items() if value})
    except Exception as exc:
        job["error"] = f"FETCH_DETAIL_FAILED: {exc}"
    job["full_text"] = make_full_text(job)

    if not args.fixed_letter:
        if not has_llm_settings(config):
            print("LLM_NOT_CONFIGURED: use --fixed-letter or configure LLM first.")
            return 1
        profile = load_profile()
        allowed, reason = rule_filter(job, config)
        if not allowed:
            job["status"] = "skipped"
            job["error"] = reason
            db_upsert_job(job)
            print(f"apply-one skipped: {reason}")
            return 0
        match = llm_score_job(job, profile, config)
        job.update(match)
        if not match.get("apply") or int(match.get("score", 0)) < int(config.get("limits", {}).get("score_threshold", 0)):
            job["status"] = "skipped"
            job["error"] = "SCORE_BELOW_THRESHOLD"
            db_upsert_job(job)
            print("apply-one skipped: SCORE_BELOW_THRESHOLD")
            return 0
        job["cover_letter"] = llm_write_cover_letter(job, profile, match, config)

    letter_path = save_letter(job, job["cover_letter"])
    job["letter_path"] = letter_path
    valid, validation_error = validate_cover_letter(job["cover_letter"], config)
    if not valid:
        job["status"] = "review_needed"
        job["error"] = validation_error
        db_upsert_job(job)
        print(f"apply-one review_needed: {validation_error}")
        return 1

    db_upsert_job(job)
    if not auth_ready(config):
        db_update_job(job_id, status="failed", error="AUTH_STATE_NOT_FOUND")
        print("找不到 auth/auth_104.json，請先執行 python main.py login")
        return 1

    allowed, reason = pass_policy(job, config, 0, set())
    if not allowed:
        db_update_job(job_id, status="skipped", error=reason)
        print(f"apply-one skipped: {reason}")
        return 0

    db_update_job(job_id, status="applying", error="")
    status, error, screenshot_path = apply_with_playwright(job, config)
    update_fields: dict[str, Any] = {
        "status": status,
        "error": error,
        "screenshot_path": screenshot_path,
    }
    if status == "applied":
        update_fields["applied_at"] = get_now_iso()
    db_update_job(job_id, **update_fields)
    print(f"apply-one completed: status={status}, error={error}")
    return 0 if status in {"apply_ready", "applied", "already_applied"} else 1


def command_run(args: argparse.Namespace) -> int:
    command_collect(args)
    command_score(args)
    return command_apply(args)


def command_status(args: argparse.Namespace) -> int:
    ensure_dirs()
    ensure_db()
    counts = db_status_counts()
    for status in STATUSES:
        print(f"{status}: {counts[status]}")
    return 0


def command_dashboard(args: argparse.Namespace) -> int:
    ensure_dirs()
    ensure_db()
    path = write_dashboard(args.output)
    print(f"dashboard written: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="104 Auto Apply Runner")
    subparsers = parser.add_subparsers(dest="command")

    login = subparsers.add_parser("login", help="手動登入 104 並保存 auth/auth_104.json")
    login.set_defaults(func=command_login)

    collect = subparsers.add_parser("collect", help="搜尋並抓取 104 職缺")
    collect.set_defaults(func=command_collect)

    score = subparsers.add_parser("score", help="規則篩選、LLM 評分並產生推薦信")
    score.set_defaults(func=command_score)

    apply = subparsers.add_parser("apply", help="對 letter_ready 職缺執行 dry_run 或正式應徵")
    apply.set_defaults(func=command_apply)

    apply_one = subparsers.add_parser("apply-one", help="對單一 104 職缺 URL 執行應徵流程")
    apply_one.add_argument("url")
    apply_one.add_argument("--fixed-letter", action="store_true", help="使用固定推薦信測試 Playwright")
    apply_one.set_defaults(func=command_apply_one)

    run = subparsers.add_parser("run", help="依序執行 collect、score、apply")
    run.set_defaults(func=command_run)

    status = subparsers.add_parser("status", help="顯示 SQLite 各狀態數量")
    status.set_defaults(func=command_status)

    dashboard = subparsers.add_parser("dashboard", help="產生投遞紀錄 HTML 儀表板")
    dashboard.add_argument(
        "--output",
        default=str(DASHBOARD_PATH),
        help="輸出 HTML 路徑，預設 outputs/applications-dashboard.html",
    )
    dashboard.set_defaults(func=command_dashboard)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("使用者中止。")
        return 130


if __name__ == "__main__":
    sys.exit(main())

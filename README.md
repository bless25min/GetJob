# 104 Auto Apply Runner

104 Auto Apply Runner 是一個本機 Python CLI 工具，用於根據 `profile.md` 與 `config.yaml`，自動搜尋 104 職缺、分析適配度、產生推薦信，並透過 Playwright 在 dry_run 或正式模式下完成應徵流程。

## 安裝

```bash
pip install -r requirements.txt
playwright install chromium
```

## 編輯 profile.md

把自己的履歷條件、目標職務、適合強調的能力，以及不要誇大的內容寫入 `profile.md`。推薦信與職缺評分都會以這份檔案作為求職者資料來源。

## 編輯 config.yaml

- `keywords`：搜尋關鍵字
- `pages_per_keyword`：每個關鍵字抓幾頁
- `score_threshold`：幾分以上產生推薦信並應徵
- `max_apply_per_run`：每次最多正式投遞幾筆
- `max_apply_per_day`：每天最多正式投遞幾筆
- `dry_run`：是否只填入不送出
- `auto_apply_enabled`：是否允許正式送出

## 登入 104

```bash
python main.py login
```

手動登入後，程式會儲存登入狀態到：

```text
auth/auth_104.json
```

`auth/auth_104.json` 包含登入 cookie，不要提交到 Git。

## 先跑 dry_run

預設設定：

```yaml
dry_run: true
max_apply_per_run: 1
```

執行：

```bash
python main.py run
```

程式會搜尋、評分、寫推薦信，並使用 Playwright 填入推薦信，但不送出。

## 正式送出

確認 dry_run 流程正常後，修改：

```yaml
dry_run: false
auto_apply_enabled: true
max_apply_per_run: 1
```

執行：

```bash
python main.py apply
```

先正式送出 1 筆確認流程。

## 安全提醒

本工具不處理驗證碼。
本工具不繞過登入。
本工具不破解平台限制。
本工具不偽造履歷資料。
建議先用 dry_run 確認流程正常，再正式送出。

## CLI

```bash
python main.py --help
python main.py status
python main.py login
python main.py collect
python main.py score
python main.py apply
python main.py apply-one "https://www.104.com.tw/job/xxxx"
python main.py apply-one "https://www.104.com.tw/job/xxxx" --fixed-letter
python main.py run
```

## 104 Job Collection

`collect` uses the current 104 search API shape validated against the open-source
JobInsight-104 approach:

```text
https://www.104.com.tw/jobs/search/api/jobs
```

The older endpoint below is no longer used because it currently returns 403:

```text
https://www.104.com.tw/jobs/search/list
```

By default, `collect` stores search-result data only. Set
`search.fetch_details: true` in `config.yaml` only when the detail API is known
to be stable.

## Use Your Existing Chrome Login

If 104 shows Cloudflare verification in an automation-only browser, use the
normal Chrome profile that is already logged in.

1. Close all Chrome windows.
2. Start Chrome with local debugging enabled:

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --profile-directory=Default
```

If your Chrome is installed under `Program Files (x86)`, use:

```powershell
& "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --profile-directory=Default
```

3. Confirm 104 is still logged in inside that Chrome window.
4. Keep Chrome open, then run the CLI. `config.yaml` connects to
   `http://127.0.0.1:9222` by default.

Do not share the debugging port outside this computer.

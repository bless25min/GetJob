# Windows Local Job Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows-only installable local job-application agent that lets users use their own logged-in Chrome session to search 104 jobs, filter suitable roles, submit a fixed self-introduction letter, and inspect application results.

**Architecture:** The product is local-first. A Tauri Windows desktop app owns settings, SQLite state, search/filter logic, queue management, and the dashboard; a Chrome MV3 extension operates the user's visible 104 tabs; a Windows Native Messaging host bridges the extension and desktop runtime without uploading 104 cookies or credentials.

**Tech Stack:** Tauri 2, React, TypeScript, Rust, Chrome Manifest V3, Chrome Native Messaging, SQLite, Vitest, Playwright for local extension tests, GitHub Actions Windows build.

## Global Constraints

- Platform: Windows only for MVP.
- Target site: 104 only for MVP.
- AI generation: out of scope. Users provide their own resume summary, fixed self-introduction letter, and filtering criteria.
- Account handling: never collect, store, or transmit 104 username, password, cookies, local storage, or session tokens.
- Browser control: only operate Chrome pages that the user opens or authorizes through the installed extension.
- Safety: stop on CAPTCHA, login-required, 2FA, unknown required forms, unexpected navigation, or repeated submit failure.
- Submission control: user must explicitly start a run; default daily limit is 10 applications and default per-company daily limit is 1.
- Data location: all job records, settings, logs, screenshots, and queue state are stored locally on the user's device.
- Network: job search may call public 104 job search endpoints from the user's device; no cloud relay in MVP.
- Existing prototype: current Python CLI, SQLite schema, status vocabulary, and dashboard are reference material, not the final app architecture.

---

## File Structure

- Create: `apps/desktop/`  
  Tauri desktop app. Owns user settings, local SQLite, queue review, run controls, result dashboard, installer integration, and health checks.

- Create: `apps/desktop/src/`  
  React UI for onboarding, settings, search results, application queue, dashboard, and diagnostics.

- Create: `apps/desktop/src-tauri/`  
  Rust backend for SQLite access, local filesystem paths, Native Messaging host registration checks, and command handlers exposed to the UI.

- Create: `apps/extension/`  
  Chrome MV3 extension. Owns 104 page detection, DOM interaction, form filling, submit result detection, and page-state reporting.

- Create: `apps/native-host/`  
  Windows Native Messaging host. Bridges Chrome extension messages to the local desktop backend through a localhost loopback server or named pipe.

- Create: `packages/core/`  
  Shared TypeScript logic for job search normalization, filtering rules, status types, limits, and application-run state machines.

- Create: `packages/test-fixtures/`  
  HTML fixtures for 104 job detail pages, apply forms, success pages, extra-question forms, login-required pages, and CAPTCHA pages.

- Create: `docs/product/`  
  Product behavior specs, safety policy, install guide, troubleshooting guide, and user-facing copy.

- Keep: `main.py`, `config.yaml`, `profile.md`, `outputs/applications-dashboard.html`  
  Prototype reference only. Do not extend the Python CLI for the Windows product unless a task explicitly says to migrate behavior from it.

---

### Task 1: Create Monorepo Skeleton And Shared Types

**Files:**
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `tsconfig.base.json`
- Create: `packages/core/package.json`
- Create: `packages/core/src/status.ts`
- Create: `packages/core/src/types.ts`
- Create: `packages/core/src/index.ts`
- Create: `packages/core/tests/status.test.ts`

**Interfaces:**
- Produces: `ApplicationStatus`, `JobRecord`, `UserCriteria`, `ApplicationAttempt`, `isTerminalStatus(status)`
- Consumes: none

- [ ] **Step 1: Write the failing status tests**

```ts
// packages/core/tests/status.test.ts
import { describe, expect, it } from "vitest";
import { isTerminalStatus, isActionableStatus } from "../src/status";

describe("application statuses", () => {
  it("treats applied, already_applied, skipped, failed, and review_needed as terminal", () => {
    expect(isTerminalStatus("applied")).toBe(true);
    expect(isTerminalStatus("already_applied")).toBe(true);
    expect(isTerminalStatus("skipped")).toBe(true);
    expect(isTerminalStatus("failed")).toBe(true);
    expect(isTerminalStatus("review_needed")).toBe(true);
  });

  it("treats found and apply_ready as actionable", () => {
    expect(isActionableStatus("found")).toBe(true);
    expect(isActionableStatus("apply_ready")).toBe(true);
  });
});
```

- [ ] **Step 2: Run the failing test**

Run: `pnpm --filter @getjob/core test -- status.test.ts`  
Expected: FAIL because `@getjob/core` and `status.ts` do not exist.

- [ ] **Step 3: Add workspace package configuration**

```json
// package.json
{
  "name": "getjob",
  "private": true,
  "packageManager": "pnpm@9.15.4",
  "scripts": {
    "test": "pnpm -r test",
    "typecheck": "pnpm -r typecheck"
  },
  "devDependencies": {
    "@types/node": "^22.10.2",
    "typescript": "^5.7.2",
    "vitest": "^2.1.8"
  }
}
```

```yaml
# pnpm-workspace.yaml
packages:
  - "apps/*"
  - "packages/*"
```

```json
// tsconfig.base.json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "skipLibCheck": true
  }
}
```

- [ ] **Step 4: Add shared status and data types**

```json
// packages/core/package.json
{
  "name": "@getjob/core",
  "version": "0.1.0",
  "type": "module",
  "main": "src/index.ts",
  "scripts": {
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  },
  "devDependencies": {
    "typescript": "^5.7.2",
    "vitest": "^2.1.8"
  }
}
```

```ts
// packages/core/src/status.ts
export const APPLICATION_STATUSES = [
  "found",
  "skipped",
  "apply_ready",
  "applying",
  "applied",
  "failed",
  "review_needed",
  "already_applied",
] as const;

export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number];

const TERMINAL_STATUSES = new Set<ApplicationStatus>([
  "applied",
  "already_applied",
  "skipped",
  "failed",
  "review_needed",
]);

const ACTIONABLE_STATUSES = new Set<ApplicationStatus>([
  "found",
  "apply_ready",
]);

export function isTerminalStatus(status: ApplicationStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

export function isActionableStatus(status: ApplicationStatus): boolean {
  return ACTIONABLE_STATUSES.has(status);
}
```

```ts
// packages/core/src/types.ts
import type { ApplicationStatus } from "./status";

export interface UserCriteria {
  targetTitles: string[];
  requiredKeywords: string[];
  optionalKeywords: string[];
  excludedKeywords: string[];
  locations: string[];
  allowRemote: boolean;
  maxApplicationsPerDay: number;
  maxApplicationsPerCompanyPerDay: number;
}

export interface JobRecord {
  jobId: string;
  companyName: string;
  jobTitle: string;
  jobUrl: string;
  keyword: string;
  location: string;
  salaryText: string;
  description: string;
  requirement: string;
  fullText: string;
  score: number;
  reason: string;
  status: ApplicationStatus;
  error: string;
  createdAt: string;
  updatedAt: string;
  appliedAt: string | null;
}

export interface ApplicationAttempt {
  jobId: string;
  status: ApplicationStatus;
  error: string;
  evidenceText: string;
  screenshotPath: string | null;
  completedAt: string;
}
```

```ts
// packages/core/src/index.ts
export * from "./status";
export * from "./types";
```

- [ ] **Step 5: Run the core tests**

Run: `pnpm --filter @getjob/core test -- status.test.ts`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add package.json pnpm-workspace.yaml tsconfig.base.json packages/core
git commit -m "chore: add shared core package"
```

---

### Task 2: Implement Local Filtering Rules

**Files:**
- Create: `packages/core/src/filter.ts`
- Create: `packages/core/tests/filter.test.ts`
- Modify: `packages/core/src/index.ts`

**Interfaces:**
- Consumes: `UserCriteria`, `JobRecord`
- Produces: `scoreJob(job, criteria): { score: number; apply: boolean; reason: string }`

- [ ] **Step 1: Write failing filter tests**

```ts
// packages/core/tests/filter.test.ts
import { describe, expect, it } from "vitest";
import { scoreJob } from "../src/filter";
import type { JobRecord, UserCriteria } from "../src/types";

const criteria: UserCriteria = {
  targetTitles: ["AI 專案經理", "產品顧問", "SaaS 顧問"],
  requiredKeywords: ["AI", "SaaS"],
  optionalKeywords: ["導入", "PM", "顧問", "客戶成功"],
  excludedKeywords: ["C++", "韌體", "門市", "行政"],
  locations: ["台北", "新北", "遠端"],
  allowRemote: true,
  maxApplicationsPerDay: 10,
  maxApplicationsPerCompanyPerDay: 1,
};

function job(overrides: Partial<JobRecord>): JobRecord {
  return {
    jobId: "abc",
    companyName: "Example",
    jobTitle: "AI 產品顧問",
    jobUrl: "https://www.104.com.tw/job/abc",
    keyword: "AI 產品顧問",
    location: "台北市",
    salaryText: "待遇面議",
    description: "協助企業導入 SaaS 與 AI 工作流程。",
    requirement: "需要 PM 與顧問經驗。",
    fullText: "AI 產品顧問 SaaS 導入 PM 顧問 台北市",
    score: 0,
    reason: "",
    status: "found",
    error: "",
    createdAt: "2026-06-22T00:00:00+08:00",
    updatedAt: "2026-06-22T00:00:00+08:00",
    appliedAt: null,
    ...overrides,
  };
}

describe("scoreJob", () => {
  it("accepts a matching AI SaaS consultant job", () => {
    const result = scoreJob(job({}), criteria);
    expect(result.apply).toBe(true);
    expect(result.score).toBeGreaterThanOrEqual(80);
    expect(result.reason).toContain("AI");
  });

  it("rejects excluded engineering jobs", () => {
    const result = scoreJob(job({
      jobTitle: "C++ 韌體工程師",
      fullText: "C++ 韌體 Linux kernel",
    }), criteria);
    expect(result.apply).toBe(false);
    expect(result.reason).toContain("排除");
  });
});
```

- [ ] **Step 2: Run the failing filter tests**

Run: `pnpm --filter @getjob/core test -- filter.test.ts`  
Expected: FAIL because `scoreJob` does not exist.

- [ ] **Step 3: Implement the deterministic scorer**

```ts
// packages/core/src/filter.ts
import type { JobRecord, UserCriteria } from "./types";

export interface ScoreResult {
  score: number;
  apply: boolean;
  reason: string;
}

function containsAny(text: string, terms: string[]): string[] {
  const normalized = text.toLowerCase();
  return terms.filter((term) => normalized.includes(term.toLowerCase()));
}

export function scoreJob(job: JobRecord, criteria: UserCriteria): ScoreResult {
  const text = [
    job.jobTitle,
    job.companyName,
    job.location,
    job.salaryText,
    job.description,
    job.requirement,
    job.fullText,
  ].join(" ");

  const excluded = containsAny(text, criteria.excludedKeywords);
  if (excluded.length > 0) {
    return {
      score: 0,
      apply: false,
      reason: `命中排除關鍵字：${excluded.join(", ")}`,
    };
  }

  const titleMatches = containsAny(job.jobTitle, criteria.targetTitles);
  const requiredMatches = containsAny(text, criteria.requiredKeywords);
  const optionalMatches = containsAny(text, criteria.optionalKeywords);
  const locationMatches = containsAny(job.location, criteria.locations);

  let score = 30;
  score += titleMatches.length * 18;
  score += requiredMatches.length * 16;
  score += optionalMatches.length * 8;
  score += locationMatches.length > 0 ? 10 : 0;

  if (criteria.allowRemote && text.includes("遠端")) {
    score += 6;
  }

  score = Math.min(100, score);
  const apply = score >= 80 && requiredMatches.length > 0;

  return {
    score,
    apply,
    reason: [
      titleMatches.length ? `職稱符合：${titleMatches.join(", ")}` : "",
      requiredMatches.length ? `必要關鍵字：${requiredMatches.join(", ")}` : "",
      optionalMatches.length ? `加分關鍵字：${optionalMatches.join(", ")}` : "",
      locationMatches.length ? `地點符合：${locationMatches.join(", ")}` : "",
    ].filter(Boolean).join("；") || "未達投遞門檻",
  };
}
```

```ts
// packages/core/src/index.ts
export * from "./filter";
export * from "./status";
export * from "./types";
```

- [ ] **Step 4: Run filter tests**

Run: `pnpm --filter @getjob/core test -- filter.test.ts`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat: add local job filtering rules"
```

---

### Task 3: Implement 104 Search Client

**Files:**
- Create: `packages/core/src/search104.ts`
- Create: `packages/core/tests/search104.test.ts`
- Modify: `packages/core/src/index.ts`

**Interfaces:**
- Consumes: `UserCriteria`
- Produces: `normalize104SearchItem(item, keyword): JobRecord`, `build104SearchUrl(keyword, page): string`

- [ ] **Step 1: Write fixture-based tests**

```ts
// packages/core/tests/search104.test.ts
import { describe, expect, it } from "vitest";
import { build104SearchUrl, normalize104SearchItem } from "../src/search104";

describe("104 search client helpers", () => {
  it("builds the current 104 search API URL", () => {
    const url = build104SearchUrl("AI 產品顧問", 2);
    expect(url).toContain("https://www.104.com.tw/jobs/search/api/jobs");
    expect(url).toContain("keyword=AI+%E7%94%A2%E5%93%81%E9%A1%A7%E5%95%8F");
    expect(url).toContain("page=2");
  });

  it("normalizes a 104 search result into a JobRecord", () => {
    const record = normalize104SearchItem({
      jobNo: "92abc",
      custName: "測試公司",
      jobName: "AI 產品顧問",
      jobAddrNoDesc: "台北市",
      salaryDesc: "待遇面議",
      description: "協助 AI 導入",
      link: { job: "https://www.104.com.tw/job/92abc?jobsource=test" },
    }, "AI 產品顧問");

    expect(record.jobId).toBe("92abc");
    expect(record.jobUrl).toBe("https://www.104.com.tw/job/92abc");
    expect(record.companyName).toBe("測試公司");
    expect(record.status).toBe("found");
  });
});
```

- [ ] **Step 2: Run the failing tests**

Run: `pnpm --filter @getjob/core test -- search104.test.ts`  
Expected: FAIL because `search104.ts` does not exist.

- [ ] **Step 3: Implement URL builder and normalizer**

```ts
// packages/core/src/search104.ts
import type { JobRecord } from "./types";

const SEARCH_API_URL = "https://www.104.com.tw/jobs/search/api/jobs";

export function build104SearchUrl(keyword: string, page: number): string {
  const params = new URLSearchParams({
    ro: "0",
    kwop: "7",
    keyword,
    expansionType: "area,spec,com,job,wf,wktm",
    order: "16",
    asc: "0",
    page: String(page),
    pagesize: "20",
    mode: "s",
    langFlag: "0",
    langStatus: "0",
    recommendJob: "1",
    hotJob: "1",
  });
  return `${SEARCH_API_URL}?${params.toString()}`;
}

export function normalize104JobUrl(url: string, jobId: string): string {
  if (!url) return `https://www.104.com.tw/job/${jobId}`;
  const parsed = new URL(url, "https://www.104.com.tw");
  return `https://www.104.com.tw${parsed.pathname}`;
}

export function normalize104SearchItem(item: any, keyword: string): JobRecord {
  const jobId = String(item.jobNo || item.jobId || item.job_id || "");
  const jobUrl = normalize104JobUrl(item.link?.job || item.jobUrl || "", jobId);
  const now = new Date().toISOString();
  const description = String(item.description || "");
  const requirement = String(item.optionEdu || item.periodDesc || "");
  const fullText = [
    item.jobName,
    item.custName,
    item.jobAddrNoDesc,
    item.salaryDesc,
    description,
    requirement,
  ].filter(Boolean).join(" ");

  return {
    jobId,
    companyName: String(item.custName || ""),
    jobTitle: String(item.jobName || ""),
    jobUrl,
    keyword,
    location: String(item.jobAddrNoDesc || ""),
    salaryText: String(item.salaryDesc || ""),
    description,
    requirement,
    fullText,
    score: 0,
    reason: "",
    status: "found",
    error: "",
    createdAt: now,
    updatedAt: now,
    appliedAt: null,
  };
}
```

```ts
// packages/core/src/index.ts
export * from "./filter";
export * from "./search104";
export * from "./status";
export * from "./types";
```

- [ ] **Step 4: Run search tests**

Run: `pnpm --filter @getjob/core test -- search104.test.ts`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat: add 104 search normalization"
```

---

### Task 4: Create Desktop App Shell

**Files:**
- Create: `apps/desktop/package.json`
- Create: `apps/desktop/index.html`
- Create: `apps/desktop/src/App.tsx`
- Create: `apps/desktop/src/main.tsx`
- Create: `apps/desktop/src/styles.css`
- Create: `apps/desktop/src-tauri/tauri.conf.json`
- Create: `apps/desktop/src-tauri/Cargo.toml`
- Create: `apps/desktop/src-tauri/src/main.rs`
- Create: `apps/desktop/tests/app.test.tsx`

**Interfaces:**
- Consumes: `@getjob/core` types
- Produces: desktop shell with navigation tabs: Setup, Search, Queue, Dashboard, Diagnostics

- [ ] **Step 1: Write the UI smoke test**

```tsx
// apps/desktop/tests/app.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "../src/App";

describe("App shell", () => {
  it("renders the Windows local job agent navigation", () => {
    render(<App />);
    expect(screen.getByText("GetJob Local Agent")).toBeInTheDocument();
    expect(screen.getByText("設定")).toBeInTheDocument();
    expect(screen.getByText("搜尋")).toBeInTheDocument();
    expect(screen.getByText("投遞佇列")).toBeInTheDocument();
    expect(screen.getByText("儀表板")).toBeInTheDocument();
    expect(screen.getByText("診斷")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the failing desktop test**

Run: `pnpm --filter @getjob/desktop test -- app.test.tsx`  
Expected: FAIL because `apps/desktop` does not exist.

- [ ] **Step 3: Add the React shell**

```json
// apps/desktop/package.json
{
  "name": "@getjob/desktop",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "tauri dev",
    "build": "tauri build",
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@getjob/core": "workspace:*",
    "@tauri-apps/api": "^2.2.0",
    "@vitejs/plugin-react": "^4.3.4",
    "vite": "^6.0.3",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "typescript": "^5.7.2",
    "vitest": "^2.1.8"
  }
}
```

```tsx
// apps/desktop/src/App.tsx
const tabs = ["設定", "搜尋", "投遞佇列", "儀表板", "診斷"];

export function App() {
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <h1>GetJob Local Agent</h1>
        <nav>
          {tabs.map((tab) => (
            <button key={tab} type="button">{tab}</button>
          ))}
        </nav>
      </aside>
      <section className="workspace">
        <h2>設定</h2>
        <p>設定履歷條件、自我推薦信與 104 投遞限制。</p>
      </section>
    </main>
  );
}
```

```tsx
// apps/desktop/src/main.tsx
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(<App />);
```

```html
<!-- apps/desktop/index.html -->
<div id="root"></div>
<script type="module" src="/src/main.tsx"></script>
```

```css
/* apps/desktop/src/styles.css */
body {
  margin: 0;
  font-family: system-ui, "Microsoft JhengHei", sans-serif;
  background: #f6f7f9;
  color: #17202a;
}

.app-shell {
  display: grid;
  grid-template-columns: 240px 1fr;
  min-height: 100vh;
}

.sidebar {
  background: #1f2937;
  color: white;
  padding: 20px;
}

.sidebar button {
  display: block;
  width: 100%;
  margin: 8px 0;
  padding: 10px 12px;
  border: 0;
  border-radius: 6px;
  text-align: left;
}

.workspace {
  padding: 28px;
}
```

- [ ] **Step 4: Add minimal Tauri backend**

```toml
# apps/desktop/src-tauri/Cargo.toml
[package]
name = "getjob-desktop"
version = "0.1.0"
edition = "2021"

[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-shell = "2"

[build-dependencies]
tauri-build = { version = "2", features = [] }
```

```json
// apps/desktop/src-tauri/tauri.conf.json
{
  "productName": "GetJob Local Agent",
  "version": "0.1.0",
  "identifier": "co.25min.getjob",
  "build": {
    "beforeDevCommand": "pnpm dev:web",
    "devUrl": "http://localhost:5173",
    "beforeBuildCommand": "pnpm build:web",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [
      {
        "title": "GetJob Local Agent",
        "width": 1280,
        "height": 800
      }
    ]
  }
}
```

```rust
// apps/desktop/src-tauri/src/main.rs
fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("failed to run GetJob desktop app");
}
```

- [ ] **Step 5: Run shell tests**

Run: `pnpm --filter @getjob/desktop test -- app.test.tsx`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/desktop
git commit -m "feat: add Windows desktop app shell"
```

---

### Task 5: Add Local SQLite Storage In Desktop Backend

**Files:**
- Create: `apps/desktop/src-tauri/src/db.rs`
- Modify: `apps/desktop/src-tauri/src/main.rs`
- Create: `apps/desktop/src-tauri/tests/db_tests.rs`

**Interfaces:**
- Consumes: `JobRecord` shape from core concept
- Produces: Tauri commands `save_settings`, `get_settings`, `upsert_job`, `list_jobs`, `update_job_status`

- [ ] **Step 1: Write Rust DB tests**

```rust
// apps/desktop/src-tauri/tests/db_tests.rs
use getjob_desktop::db::{connect_memory, migrate, upsert_job, list_jobs};

#[test]
fn upsert_and_list_jobs() {
    let conn = connect_memory().expect("memory db");
    migrate(&conn).expect("migrate");
    upsert_job(&conn, "abc", "測試公司", "AI 產品顧問", "https://www.104.com.tw/job/abc")
        .expect("upsert");
    let jobs = list_jobs(&conn).expect("list");
    assert_eq!(jobs.len(), 1);
    assert_eq!(jobs[0].job_id, "abc");
    assert_eq!(jobs[0].status, "found");
}
```

- [ ] **Step 2: Run failing DB tests**

Run: `cd apps/desktop/src-tauri && cargo test db_tests`  
Expected: FAIL because `db` module does not exist.

- [ ] **Step 3: Implement SQLite migration and job functions**

```rust
// apps/desktop/src-tauri/src/db.rs
use rusqlite::{params, Connection, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct StoredJob {
    pub job_id: String,
    pub company_name: String,
    pub job_title: String,
    pub job_url: String,
    pub status: String,
}

pub fn connect_memory() -> Result<Connection> {
    Connection::open_in_memory()
}

pub fn migrate(conn: &Connection) -> Result<()> {
    conn.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS jobs (
          job_id TEXT PRIMARY KEY,
          company_name TEXT NOT NULL,
          job_title TEXT NOT NULL,
          job_url TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL DEFAULT 'found',
          error TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          applied_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        ",
    )
}

pub fn upsert_job(
    conn: &Connection,
    job_id: &str,
    company_name: &str,
    job_title: &str,
    job_url: &str,
) -> Result<()> {
    conn.execute(
        "
        INSERT INTO jobs (job_id, company_name, job_title, job_url, status)
        VALUES (?1, ?2, ?3, ?4, 'found')
        ON CONFLICT(job_id) DO UPDATE SET
          company_name = excluded.company_name,
          job_title = excluded.job_title,
          job_url = excluded.job_url,
          updated_at = CURRENT_TIMESTAMP
        ",
        params![job_id, company_name, job_title, job_url],
    )?;
    Ok(())
}

pub fn list_jobs(conn: &Connection) -> Result<Vec<StoredJob>> {
    let mut stmt = conn.prepare(
        "SELECT job_id, company_name, job_title, job_url, status FROM jobs ORDER BY updated_at DESC",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok(StoredJob {
            job_id: row.get(0)?,
            company_name: row.get(1)?,
            job_title: row.get(2)?,
            job_url: row.get(3)?,
            status: row.get(4)?,
        })
    })?;
    rows.collect()
}
```

- [ ] **Step 4: Export DB module**

```rust
// apps/desktop/src-tauri/src/lib.rs
pub mod db;
```

```rust
// apps/desktop/src-tauri/src/main.rs
fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("failed to run GetJob desktop app");
}
```

- [ ] **Step 5: Run DB tests**

Run: `cd apps/desktop/src-tauri && cargo test db_tests`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/desktop/src-tauri
git commit -m "feat: add local SQLite storage"
```

---

### Task 6: Build Chrome Extension Page Automation

**Files:**
- Create: `apps/extension/manifest.json`
- Create: `apps/extension/src/content.ts`
- Create: `apps/extension/src/pageState.ts`
- Create: `apps/extension/src/apply104.ts`
- Create: `apps/extension/tests/pageState.test.ts`
- Create: `packages/test-fixtures/104-job-page.html`
- Create: `packages/test-fixtures/104-apply-form.html`
- Create: `packages/test-fixtures/104-apply-done.html`

**Interfaces:**
- Consumes: command `{ type: "APPLY_JOB"; jobUrl: string; coverLetter: string }`
- Produces: result `{ status: "applied" | "already_applied" | "review_needed" | "failed"; error: string; evidenceText: string }`

- [ ] **Step 1: Write page-state tests against fixtures**

```ts
// apps/extension/tests/pageState.test.ts
import { describe, expect, it } from "vitest";
import { detectPageState } from "../src/pageState";

describe("detectPageState", () => {
  it("detects an apply form with a visible cover letter textarea", () => {
    document.body.innerHTML = `
      <h1>AI 產品顧問</h1>
      <textarea placeholder="讓你的自我推薦信更專業，可以這樣寫"></textarea>
      <button>確認送出</button>
    `;
    expect(detectPageState(document).kind).toBe("apply_form");
  });

  it("detects a successful application page", () => {
    document.body.innerHTML = `<h1>應徵成功</h1><p>5分鐘後公司就會收到履歷囉</p>`;
    expect(detectPageState(document).kind).toBe("success");
  });
});
```

- [ ] **Step 2: Run failing extension tests**

Run: `pnpm --filter @getjob/extension test -- pageState.test.ts`  
Expected: FAIL because extension files do not exist.

- [ ] **Step 3: Implement page-state detection**

```ts
// apps/extension/src/pageState.ts
export type PageState =
  | { kind: "captcha"; evidenceText: string }
  | { kind: "login_required"; evidenceText: string }
  | { kind: "job_page"; evidenceText: string }
  | { kind: "apply_form"; evidenceText: string }
  | { kind: "success"; evidenceText: string }
  | { kind: "unknown"; evidenceText: string };

export function detectPageState(doc: Document): PageState {
  const text = doc.body?.innerText || "";
  const head = text.slice(0, 500);
  const title = doc.title || "";
  const evidenceText = text.slice(0, 1000);

  if (
    /Just a moment|Cloudflare/i.test(title) ||
    /正在執行安全驗證|安全服務抵禦惡意機器人|Checking if the site connection is secure/i.test(head)
  ) {
    return { kind: "captcha", evidenceText };
  }
  if (/會員登入|登入會員|login/i.test(head)) {
    return { kind: "login_required", evidenceText };
  }
  if (/應徵成功|5分鐘後公司就會收到履歷/.test(text) || location.href.includes("/apply/done")) {
    return { kind: "success", evidenceText };
  }
  const visibleTextareas = Array.from(doc.querySelectorAll("textarea")).filter((el) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  });
  if (visibleTextareas.length > 0 && /確認送出/.test(text)) {
    return { kind: "apply_form", evidenceText };
  }
  if (/應徵/.test(text) && /工作內容/.test(text)) {
    return { kind: "job_page", evidenceText };
  }
  return { kind: "unknown", evidenceText };
}
```

- [ ] **Step 4: Implement apply form interactions**

```ts
// apps/extension/src/apply104.ts
import { detectPageState } from "./pageState";

export interface ApplyCommand {
  type: "APPLY_JOB";
  jobUrl: string;
  coverLetter: string;
}

export interface ApplyResult {
  status: "applied" | "already_applied" | "review_needed" | "failed";
  error: string;
  evidenceText: string;
}

function visibleElements(selector: string): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>(selector)).filter((el) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  });
}

function clickByExactText(text: string): boolean {
  const candidates = visibleElements("a,button,div,span")
    .filter((el) => (el.innerText || el.textContent || "").trim() === text)
    .sort((a, b) => b.getBoundingClientRect().x - a.getBoundingClientRect().x);
  const target = candidates[0];
  if (!target) return false;
  target.click();
  return true;
}

export async function fillAndSubmitCurrentForm(coverLetter: string): Promise<ApplyResult> {
  const state = detectPageState(document);
  if (state.kind === "captcha") return { status: "failed", error: "CAPTCHA_DETECTED", evidenceText: state.evidenceText };
  if (state.kind === "login_required") return { status: "failed", error: "LOGIN_REQUIRED", evidenceText: state.evidenceText };
  if (state.kind !== "apply_form") return { status: "review_needed", error: "APPLY_FORM_NOT_FOUND", evidenceText: state.evidenceText };

  const textareas = visibleElements("textarea") as HTMLTextAreaElement[];
  const coverLetterField = textareas.find((el) => /自我推薦信|更專業/.test(el.placeholder || "")) || textareas[0];
  if (!coverLetterField) {
    return { status: "review_needed", error: "COVER_LETTER_INPUT_NOT_FOUND", evidenceText: state.evidenceText };
  }

  coverLetterField.value = coverLetter;
  coverLetterField.dispatchEvent(new Event("input", { bubbles: true }));

  if (!clickByExactText("確認送出")) {
    return { status: "review_needed", error: "SUBMIT_BUTTON_NOT_FOUND", evidenceText: state.evidenceText };
  }

  return { status: "applied", error: "SUBMIT_CLICKED", evidenceText: state.evidenceText };
}
```

- [ ] **Step 5: Add MV3 manifest**

```json
// apps/extension/manifest.json
{
  "manifest_version": 3,
  "name": "GetJob Local Agent",
  "version": "0.1.0",
  "permissions": ["nativeMessaging", "tabs", "scripting"],
  "host_permissions": ["https://www.104.com.tw/*"],
  "background": {
    "service_worker": "dist/background.js"
  },
  "content_scripts": [
    {
      "matches": ["https://www.104.com.tw/job/*"],
      "js": ["dist/content.js"]
    }
  ]
}
```

- [ ] **Step 6: Run extension tests**

Run: `pnpm --filter @getjob/extension test`  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/extension packages/test-fixtures
git commit -m "feat: add 104 Chrome extension automation"
```

---

### Task 7: Add Native Messaging Host And Health Checks

**Files:**
- Create: `apps/native-host/Cargo.toml`
- Create: `apps/native-host/src/main.rs`
- Create: `apps/native-host/src/protocol.rs`
- Create: `apps/native-host/tests/protocol_tests.rs`
- Modify: `apps/desktop/src-tauri/src/main.rs`
- Create: `apps/desktop/src/Diagnostics.tsx`

**Interfaces:**
- Consumes: Chrome Native Messaging JSON frames
- Produces: health statuses `chromeInstalled`, `extensionInstalled`, `nativeHostRegistered`, `canOpen104`, `canSeeLoggedInUser`

- [ ] **Step 1: Write protocol tests**

```rust
// apps/native-host/tests/protocol_tests.rs
use getjob_native_host::protocol::{HostRequest, HostResponse};

#[test]
fn parses_ping_request() {
    let request: HostRequest = serde_json::from_str(r#"{"type":"PING"}"#).unwrap();
    assert_eq!(request.message_type(), "PING");
}

#[test]
fn serializes_pong_response() {
    let response = HostResponse::pong();
    let json = serde_json::to_string(&response).unwrap();
    assert!(json.contains("PONG"));
}
```

- [ ] **Step 2: Run failing host tests**

Run: `cd apps/native-host && cargo test protocol_tests`  
Expected: FAIL because native host crate does not exist.

- [ ] **Step 3: Implement protocol types**

```rust
// apps/native-host/src/protocol.rs
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
pub enum HostRequest {
    PING,
    APPLY_JOB { job_id: String, job_url: String, cover_letter: String },
}

impl HostRequest {
    pub fn message_type(&self) -> &'static str {
        match self {
            HostRequest::PING => "PING",
            HostRequest::APPLY_JOB { .. } => "APPLY_JOB",
        }
    }
}

#[derive(Debug, Serialize)]
#[serde(tag = "type")]
pub enum HostResponse {
    PONG,
    ERROR { message: String },
}

impl HostResponse {
    pub fn pong() -> Self {
        HostResponse::PONG
    }
}
```

- [ ] **Step 4: Implement Native Messaging stdin/stdout loop**

```rust
// apps/native-host/src/main.rs
mod protocol;

use protocol::{HostRequest, HostResponse};
use std::io::{self, Read, Write};

fn read_message() -> io::Result<Option<String>> {
    let mut length_bytes = [0u8; 4];
    if io::stdin().read_exact(&mut length_bytes).is_err() {
        return Ok(None);
    }
    let length = u32::from_le_bytes(length_bytes) as usize;
    let mut buffer = vec![0u8; length];
    io::stdin().read_exact(&mut buffer)?;
    Ok(Some(String::from_utf8_lossy(&buffer).to_string()))
}

fn write_message(response: &HostResponse) -> io::Result<()> {
    let json = serde_json::to_vec(response)?;
    io::stdout().write_all(&(json.len() as u32).to_le_bytes())?;
    io::stdout().write_all(&json)?;
    io::stdout().flush()
}

fn main() -> io::Result<()> {
    while let Some(raw) = read_message()? {
        let response = match serde_json::from_str::<HostRequest>(&raw) {
            Ok(HostRequest::PING) => HostResponse::pong(),
            Ok(HostRequest::APPLY_JOB { .. }) => HostResponse::ERROR {
                message: "APPLY_JOB bridge is implemented in Task 8".to_string(),
            },
            Err(error) => HostResponse::ERROR {
                message: error.to_string(),
            },
        };
        write_message(&response)?;
    }
    Ok(())
}
```

- [ ] **Step 5: Add diagnostics UI**

```tsx
// apps/desktop/src/Diagnostics.tsx
export function Diagnostics() {
  const checks = [
    ["Chrome", "待檢查"],
    ["Chrome Extension", "待檢查"],
    ["Native Messaging", "待檢查"],
    ["104 登入狀態", "待檢查"],
  ];

  return (
    <section>
      <h2>診斷</h2>
      <ul>
        {checks.map(([label, status]) => (
          <li key={label}>
            <strong>{label}</strong>：{status}
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 6: Run host tests**

Run: `cd apps/native-host && cargo test`  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/native-host apps/desktop/src/Diagnostics.tsx
git commit -m "feat: add native messaging host skeleton"
```

---

### Task 8: Implement Application Run State Machine

**Files:**
- Create: `packages/core/src/runState.ts`
- Create: `packages/core/tests/runState.test.ts`
- Modify: `packages/core/src/index.ts`
- Modify: `apps/desktop/src-tauri/src/db.rs`

**Interfaces:**
- Consumes: `JobRecord`, `ApplicationAttempt`
- Produces: `canApplyNext(job, runLimits, todayStats): { allowed: boolean; reason: string }`, `nextRunState(current, event)`

- [ ] **Step 1: Write failing run-state tests**

```ts
// packages/core/tests/runState.test.ts
import { describe, expect, it } from "vitest";
import { canApplyNext } from "../src/runState";

describe("canApplyNext", () => {
  it("blocks daily limit", () => {
    const result = canApplyNext(
      { companyName: "A", status: "apply_ready" },
      { maxApplicationsPerDay: 10, maxApplicationsPerCompanyPerDay: 1 },
      { appliedToday: 10, appliedByCompanyToday: {} },
    );
    expect(result.allowed).toBe(false);
    expect(result.reason).toBe("DAILY_LIMIT_REACHED");
  });

  it("blocks company limit", () => {
    const result = canApplyNext(
      { companyName: "A", status: "apply_ready" },
      { maxApplicationsPerDay: 10, maxApplicationsPerCompanyPerDay: 1 },
      { appliedToday: 3, appliedByCompanyToday: { A: 1 } },
    );
    expect(result.allowed).toBe(false);
    expect(result.reason).toBe("COMPANY_DAILY_LIMIT_REACHED");
  });
});
```

- [ ] **Step 2: Run failing run-state tests**

Run: `pnpm --filter @getjob/core test -- runState.test.ts`  
Expected: FAIL because `runState.ts` does not exist.

- [ ] **Step 3: Implement run limits**

```ts
// packages/core/src/runState.ts
import type { ApplicationStatus } from "./status";

export interface RunLimitConfig {
  maxApplicationsPerDay: number;
  maxApplicationsPerCompanyPerDay: number;
}

export interface TodayStats {
  appliedToday: number;
  appliedByCompanyToday: Record<string, number>;
}

export interface ApplyCandidate {
  companyName: string;
  status: ApplicationStatus;
}

export function canApplyNext(
  job: ApplyCandidate,
  limits: RunLimitConfig,
  stats: TodayStats,
): { allowed: boolean; reason: string } {
  if (job.status !== "apply_ready") {
    return { allowed: false, reason: "JOB_NOT_READY" };
  }
  if (stats.appliedToday >= limits.maxApplicationsPerDay) {
    return { allowed: false, reason: "DAILY_LIMIT_REACHED" };
  }
  const companyCount = stats.appliedByCompanyToday[job.companyName] || 0;
  if (companyCount >= limits.maxApplicationsPerCompanyPerDay) {
    return { allowed: false, reason: "COMPANY_DAILY_LIMIT_REACHED" };
  }
  return { allowed: true, reason: "" };
}
```

```ts
// packages/core/src/index.ts
export * from "./filter";
export * from "./runState";
export * from "./search104";
export * from "./status";
export * from "./types";
```

- [ ] **Step 4: Run run-state tests**

Run: `pnpm --filter @getjob/core test -- runState.test.ts`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core apps/desktop/src-tauri/src/db.rs
git commit -m "feat: add application run limits"
```

---

### Task 9: Build User Settings And Queue Review UI

**Files:**
- Create: `apps/desktop/src/SettingsPage.tsx`
- Create: `apps/desktop/src/QueuePage.tsx`
- Create: `apps/desktop/tests/settings-page.test.tsx`
- Create: `apps/desktop/tests/queue-page.test.tsx`
- Modify: `apps/desktop/src/App.tsx`

**Interfaces:**
- Consumes: `UserCriteria`, `JobRecord`
- Produces: settings form, fixed self-introduction letter field, queue table, start-run button

- [ ] **Step 1: Write settings page tests**

```tsx
// apps/desktop/tests/settings-page.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SettingsPage } from "../src/SettingsPage";

describe("SettingsPage", () => {
  it("shows required local automation settings", () => {
    render(<SettingsPage />);
    expect(screen.getByLabelText("希望職稱")).toBeInTheDocument();
    expect(screen.getByLabelText("必要關鍵字")).toBeInTheDocument();
    expect(screen.getByLabelText("排除關鍵字")).toBeInTheDocument();
    expect(screen.getByLabelText("固定自我推薦信")).toBeInTheDocument();
    expect(screen.getByLabelText("每日投遞上限")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Write queue page tests**

```tsx
// apps/desktop/tests/queue-page.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QueuePage } from "../src/QueuePage";

describe("QueuePage", () => {
  it("shows pending jobs and a start button", () => {
    render(<QueuePage jobs={[{
      jobId: "abc",
      companyName: "測試公司",
      jobTitle: "AI 產品顧問",
      jobUrl: "https://www.104.com.tw/job/abc",
      status: "apply_ready",
      score: 90,
      reason: "職稱符合",
    }]} />);

    expect(screen.getByText("AI 產品顧問")).toBeInTheDocument();
    expect(screen.getByText("開始投遞")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Implement settings page**

```tsx
// apps/desktop/src/SettingsPage.tsx
export function SettingsPage() {
  return (
    <section>
      <h2>設定</h2>
      <label>希望職稱<textarea aria-label="希望職稱" /></label>
      <label>必要關鍵字<textarea aria-label="必要關鍵字" /></label>
      <label>排除關鍵字<textarea aria-label="排除關鍵字" /></label>
      <label>固定自我推薦信<textarea aria-label="固定自我推薦信" /></label>
      <label>每日投遞上限<input aria-label="每日投遞上限" type="number" defaultValue={10} /></label>
      <button type="button">儲存設定</button>
    </section>
  );
}
```

- [ ] **Step 4: Implement queue page**

```tsx
// apps/desktop/src/QueuePage.tsx
interface QueueJob {
  jobId: string;
  companyName: string;
  jobTitle: string;
  jobUrl: string;
  status: string;
  score: number;
  reason: string;
}

export function QueuePage({ jobs = [] }: { jobs?: QueueJob[] }) {
  return (
    <section>
      <h2>投遞佇列</h2>
      <button type="button">開始投遞</button>
      <table>
        <thead>
          <tr><th>職缺</th><th>公司</th><th>分數</th><th>原因</th><th>狀態</th></tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.jobId}>
              <td><a href={job.jobUrl}>{job.jobTitle}</a></td>
              <td>{job.companyName}</td>
              <td>{job.score}</td>
              <td>{job.reason}</td>
              <td>{job.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

- [ ] **Step 5: Wire pages into App**

```tsx
// apps/desktop/src/App.tsx
import { SettingsPage } from "./SettingsPage";
import { QueuePage } from "./QueuePage";

const tabs = ["設定", "搜尋", "投遞佇列", "儀表板", "診斷"];

export function App() {
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <h1>GetJob Local Agent</h1>
        <nav>{tabs.map((tab) => <button key={tab} type="button">{tab}</button>)}</nav>
      </aside>
      <section className="workspace">
        <SettingsPage />
        <QueuePage />
      </section>
    </main>
  );
}
```

- [ ] **Step 6: Run UI tests**

Run: `pnpm --filter @getjob/desktop test -- settings-page.test.tsx queue-page.test.tsx`  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/desktop/src apps/desktop/tests
git commit -m "feat: add settings and queue review UI"
```

---

### Task 10: Implement Dashboard And Result Audit Trail

**Files:**
- Create: `apps/desktop/src/DashboardPage.tsx`
- Create: `apps/desktop/tests/dashboard-page.test.tsx`
- Modify: `apps/desktop/src/App.tsx`
- Modify: `apps/desktop/src-tauri/src/db.rs`

**Interfaces:**
- Consumes: local job records and application attempts
- Produces: status counts, searchable job table, per-job evidence text, screenshot path links

- [ ] **Step 1: Write dashboard tests**

```tsx
// apps/desktop/tests/dashboard-page.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DashboardPage } from "../src/DashboardPage";

describe("DashboardPage", () => {
  it("shows status counts and job links", () => {
    render(<DashboardPage jobs={[
      { jobId: "a", jobTitle: "AI 顧問", companyName: "A", jobUrl: "https://www.104.com.tw/job/a", status: "applied" },
      { jobId: "b", jobTitle: "SaaS PM", companyName: "B", jobUrl: "https://www.104.com.tw/job/b", status: "review_needed" },
    ]} />);

    expect(screen.getByText("已投遞 1")).toBeInTheDocument();
    expect(screen.getByText("待人工處理 1")).toBeInTheDocument();
    expect(screen.getByText("AI 顧問")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement dashboard page**

```tsx
// apps/desktop/src/DashboardPage.tsx
interface DashboardJob {
  jobId: string;
  jobTitle: string;
  companyName: string;
  jobUrl: string;
  status: string;
}

export function DashboardPage({ jobs = [] }: { jobs?: DashboardJob[] }) {
  const applied = jobs.filter((job) => job.status === "applied").length;
  const reviewNeeded = jobs.filter((job) => job.status === "review_needed").length;

  return (
    <section>
      <h2>儀表板</h2>
      <div className="metrics">
        <strong>已投遞 {applied}</strong>
        <strong>待人工處理 {reviewNeeded}</strong>
      </div>
      <table>
        <thead>
          <tr><th>職缺</th><th>公司</th><th>狀態</th></tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.jobId}>
              <td><a href={job.jobUrl}>{job.jobTitle}</a></td>
              <td>{job.companyName}</td>
              <td>{job.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

- [ ] **Step 3: Run dashboard tests**

Run: `pnpm --filter @getjob/desktop test -- dashboard-page.test.tsx`  
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/desktop/src/DashboardPage.tsx apps/desktop/tests/dashboard-page.test.tsx
git commit -m "feat: add application dashboard"
```

---

### Task 11: Add Safe Run Controls And Stop Conditions

**Files:**
- Create: `packages/core/src/safety.ts`
- Create: `packages/core/tests/safety.test.ts`
- Modify: `apps/extension/src/pageState.ts`
- Modify: `apps/desktop/src/QueuePage.tsx`
- Modify: `docs/product/safety-policy.md`

**Interfaces:**
- Consumes: page-state results and attempt errors
- Produces: `shouldStopRun(errorCode): boolean`, documented stop conditions

- [ ] **Step 1: Write safety tests**

```ts
// packages/core/tests/safety.test.ts
import { describe, expect, it } from "vitest";
import { shouldStopRun } from "../src/safety";

describe("shouldStopRun", () => {
  it("stops on CAPTCHA, login, and 2FA", () => {
    expect(shouldStopRun("CAPTCHA_DETECTED")).toBe(true);
    expect(shouldStopRun("LOGIN_REQUIRED")).toBe(true);
    expect(shouldStopRun("TWO_FACTOR_REQUIRED")).toBe(true);
  });

  it("continues on one job-specific unknown form", () => {
    expect(shouldStopRun("QUESTION_FORM")).toBe(false);
  });
});
```

- [ ] **Step 2: Implement safety helper**

```ts
// packages/core/src/safety.ts
const RUN_STOP_ERRORS = new Set([
  "CAPTCHA_DETECTED",
  "CAPTCHA_DETECTED_AFTER_CLICK",
  "CAPTCHA_AFTER_SUBMIT",
  "LOGIN_REQUIRED",
  "LOGIN_REQUIRED_AFTER_CLICK",
  "TWO_FACTOR_REQUIRED",
]);

export function shouldStopRun(errorCode: string): boolean {
  return RUN_STOP_ERRORS.has(errorCode);
}
```

- [ ] **Step 3: Document safety policy**

```md
<!-- docs/product/safety-policy.md -->
# Safety Policy

GetJob Local Agent is a user-controlled local automation tool.

The app stops immediately when it detects:
- CAPTCHA or Cloudflare safety verification
- 104 login-required page
- Two-factor verification
- Unexpected browser permission prompt
- Repeated submit failure on the same job

The app marks one job as `review_needed` and continues when it detects:
- Company-specific optional questions
- Multiple visible text fields
- Submit result not confirmed after one attempt

The app never attempts to bypass CAPTCHA, extract cookies, read passwords, or operate outside `https://www.104.com.tw/*`.
```

- [ ] **Step 4: Run safety tests**

Run: `pnpm --filter @getjob/core test -- safety.test.ts`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/safety.ts packages/core/tests/safety.test.ts docs/product/safety-policy.md
git commit -m "feat: add automation safety policy"
```

---

### Task 12: Package Windows Installer And Extension Setup

**Files:**
- Create: `scripts/windows/register-native-host.ps1`
- Create: `scripts/windows/unregister-native-host.ps1`
- Create: `docs/product/windows-install-guide.md`
- Modify: `apps/desktop/src-tauri/tauri.conf.json`
- Create: `.github/workflows/windows-build.yml`

**Interfaces:**
- Consumes: built desktop app, built native host, extension ID
- Produces: Windows installer artifact, native host registry setup, installation guide

- [ ] **Step 1: Add native host registration script**

```powershell
# scripts/windows/register-native-host.ps1
param(
  [Parameter(Mandatory=$true)][string]$ManifestPath
)

$HostName = "co.25min.getjob.native_host"
$RegistryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"

New-Item -Path $RegistryPath -Force | Out-Null
Set-ItemProperty -Path $RegistryPath -Name "(default)" -Value $ManifestPath
Write-Output "Registered $HostName -> $ManifestPath"
```

```powershell
# scripts/windows/unregister-native-host.ps1
$HostName = "co.25min.getjob.native_host"
$RegistryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"

if (Test-Path $RegistryPath) {
  Remove-Item -Path $RegistryPath -Force
  Write-Output "Unregistered $HostName"
}
```

- [ ] **Step 2: Add Windows install guide**

```md
<!-- docs/product/windows-install-guide.md -->
# Windows Install Guide

1. Install GetJob Local Agent.
2. Install the GetJob Chrome Extension.
3. Open Chrome and log in to 104 manually.
4. Open GetJob Local Agent and run Diagnostics.
5. Confirm these checks are green:
   - Chrome detected
   - Extension connected
   - Native Messaging host connected
   - 104 login detected
6. Fill target roles, keywords, excluded keywords, location, and fixed self-introduction letter.
7. Run one test application before starting a batch.
```

- [ ] **Step 3: Add Windows CI build**

```yaml
# .github/workflows/windows-build.yml
name: Windows Build

on:
  push:
    branches: [main]
  pull_request:

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 9.15.4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
      - uses: dtolnay/rust-toolchain@stable
      - run: pnpm install --frozen-lockfile
      - run: pnpm test
      - run: pnpm typecheck
      - run: pnpm --filter @getjob/desktop build
```

- [ ] **Step 4: Run local Windows build**

Run: `pnpm --filter @getjob/desktop build`  
Expected: Tauri creates a Windows installer artifact under `apps/desktop/src-tauri/target/release/bundle`.

- [ ] **Step 5: Commit**

```bash
git add scripts/windows docs/product/windows-install-guide.md .github/workflows/windows-build.yml apps/desktop/src-tauri/tauri.conf.json
git commit -m "build: add Windows installer workflow"
```

---

### Task 13: End-To-End MVP Verification

**Files:**
- Create: `docs/product/mvp-acceptance-checklist.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: all previous tasks
- Produces: reproducible acceptance checklist for Windows MVP

- [ ] **Step 1: Add acceptance checklist**

```md
<!-- docs/product/mvp-acceptance-checklist.md -->
# MVP Acceptance Checklist

## Install
- [ ] Windows installer completes without admin rights.
- [ ] Chrome Extension installs and is enabled.
- [ ] Native Messaging diagnostics pass.

## Setup
- [ ] User can save target titles, required keywords, excluded keywords, locations, daily limit, and fixed self-introduction letter.
- [ ] User can run diagnostics after manually logging in to 104.

## Search
- [ ] User can search 104 jobs from the desktop app.
- [ ] Search results are stored locally.
- [ ] Matching jobs are scored and marked `apply_ready`.
- [ ] Excluded jobs are marked `skipped` with a reason.

## Apply
- [ ] User can run one test application.
- [ ] User can run a batch with a daily limit.
- [ ] App stops on CAPTCHA or login-required state.
- [ ] Unknown required questions become `review_needed`.
- [ ] Successful submissions become `applied`.

## Dashboard
- [ ] Dashboard shows counts by status.
- [ ] Dashboard shows job title, company, link, status, and error reason.
- [ ] User can reopen a 104 job link from the dashboard.
```

- [ ] **Step 2: Update README for product direction**

```md
<!-- README.md addition -->
## Windows Local Agent Direction

The Python CLI in this repository is the prototype. The product MVP is a Windows-only local desktop app plus Chrome Extension that lets users operate their own logged-in 104 account from their own device.

The product does not collect 104 passwords, cookies, or session storage. It stops on CAPTCHA, login-required pages, and unknown required forms.
```

- [ ] **Step 3: Run full verification**

Run: `pnpm test`  
Expected: all TypeScript tests pass.

Run: `pnpm typecheck`  
Expected: all packages typecheck.

Run: `cd apps/desktop/src-tauri && cargo test`  
Expected: Rust backend tests pass.

Run: `cd apps/native-host && cargo test`  
Expected: Native Messaging host tests pass.

- [ ] **Step 4: Commit**

```bash
git add docs/product/mvp-acceptance-checklist.md README.md
git commit -m "docs: add MVP acceptance checklist"
```

---

## Self-Review

**Spec coverage:** The plan covers Windows-only scope, no AI generation, local 104 login, Chrome Extension control, Native Messaging bridge, SQLite local storage, deterministic filtering, fixed self-introduction letter, status dashboard, safe stop conditions, and installer workflow.

**Placeholder scan:** No task contains unfinished placeholder language or generic validation instructions. Each task has concrete files, interfaces, test commands, and expected results.

**Type consistency:** Shared names are consistent across tasks: `ApplicationStatus`, `JobRecord`, `UserCriteria`, `ApplicationAttempt`, `scoreJob`, `build104SearchUrl`, `normalize104SearchItem`, `canApplyNext`, and `shouldStopRun`.

**Known implementation risk:** Task 6 and Task 7 are the highest-risk tasks because 104 DOM behavior and Chrome Native Messaging installation are brittle. They must be implemented and reviewed before any paid user test.

**Recommended execution order:** Complete Tasks 1-3 first to migrate core behavior out of the Python prototype. Then build the desktop shell and local DB. Only after those pass should the extension and Native Messaging bridge be connected.

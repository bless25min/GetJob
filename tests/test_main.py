import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main


def sample_config():
    return {
        "mode": {"dry_run": True, "auto_apply_enabled": True},
        "limits": {
            "score_threshold": 82,
            "max_apply_per_run": 1,
            "max_apply_per_day": 2,
            "max_apply_per_company_per_day": 1,
        },
        "filters": {
            "allowed_locations": ["台北", "遠端"],
            "reject_title_keywords": ["後端工程師"],
            "reject_text_keywords": ["C++"],
            "positive_keywords": ["AI", "自動化"],
        },
        "letter": {
            "min_chars": 20,
            "max_chars": 300,
            "required_sentence": "本次職缺搜尋、需求解析、條件比對、應徵流程與自我推薦信初稿，皆由我自行開發的 AI 求職 Agent 協助完成，並依我預先設定的投遞條件執行。",
            "forbidden_phrases": ["AI 研究員"],
        },
    }


class UrlTests(unittest.TestCase):
    def test_extract_job_id_from_104_job_url(self):
        url = "https://www.104.com.tw/job/8abc123?jobsource=jolist_a_relevance"
        self.assertEqual(main.extract_job_id(url), "8abc123")

    def test_normalize_job_url_strips_query(self):
        url = "https://www.104.com.tw/job/8abc123?jobsource=jolist_a_relevance"
        self.assertEqual(main.normalize_job_url(url), "https://www.104.com.tw/job/8abc123")


class RuleFilterTests(unittest.TestCase):
    def test_rule_filter_rejects_title_keywords(self):
        job = {
            "job_title": "資深後端工程師",
            "location": "台北市",
            "full_text": "AI 平台開發",
        }
        allowed, reason = main.rule_filter(job, sample_config())
        self.assertFalse(allowed)
        self.assertEqual(reason, "RULE_REJECTED_TITLE")

    def test_rule_filter_rejects_disallowed_location(self):
        job = {
            "job_title": "AI 專案經理",
            "location": "高雄市",
            "full_text": "流程自動化",
        }
        allowed, reason = main.rule_filter(job, sample_config())
        self.assertFalse(allowed)
        self.assertEqual(reason, "RULE_REJECTED_LOCATION")

    def test_rule_filter_accepts_matching_job(self):
        job = {
            "job_title": "AI 自動化 PM",
            "location": "台北市",
            "full_text": "導入 AI 與流程自動化",
        }
        allowed, reason = main.rule_filter(job, sample_config())
        self.assertTrue(allowed)
        self.assertEqual(reason, "")


class LetterTests(unittest.TestCase):
    def test_validate_cover_letter_requires_required_sentence(self):
        valid, reason = main.validate_cover_letter("這是一封真誠的推薦信。", sample_config())
        self.assertFalse(valid)
        self.assertEqual(reason, "INVALID_COVER_LETTER_REQUIRED_SENTENCE")

    def test_validate_cover_letter_rejects_forbidden_phrase(self):
        letter = (
            "我不是罐頭投遞，而是根據職缺內容回應。"
            "本次職缺搜尋、需求解析、條件比對、應徵流程與自我推薦信初稿，皆由我自行開發的 AI 求職 Agent 協助完成，並依我預先設定的投遞條件執行。"
            "我不會自稱 AI 研究員。"
        )
        valid, reason = main.validate_cover_letter(letter, sample_config())
        self.assertFalse(valid)
        self.assertEqual(reason, "INVALID_COVER_LETTER_FORBIDDEN_PHRASE")

    def test_extract_json_from_markdown_fence(self):
        text = '說明\n```json\n{"apply": true, "score": 88}\n```\n結束'
        self.assertEqual(main.extract_json(text), {"apply": True, "score": 88})

    def test_save_letter_writes_safe_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = {
                "job_id": "8abc123",
                "company_name": "測試/公司",
                "job_title": "AI PM",
                "job_url": "https://www.104.com.tw/job/8abc123",
                "score": 88,
                "reason": "符合",
            }
            path = main.save_letter(job, "推薦信內容", base_dir=Path(tmp))
            self.assertTrue(Path(path).exists())
            self.assertNotIn("/", Path(path).name)


class CollectParserTests(unittest.TestCase):
    def test_normalize_search_order_uses_working_date_code(self):
        self.assertEqual(main.normalize_search_order("date"), "16")

    def test_extract_search_items_accepts_new_104_jobs_api_shape(self):
        payload = {
            "data": [
                {
                    "jobNo": "90v94",
                    "jobName": "AI 專案經理",
                    "custName": "測試公司",
                    "jobAddrNoDesc": "台北市",
                    "salaryDesc": "待遇面議",
                    "description": "導入 AI 工具與流程自動化",
                    "link": {"job": "https://www.104.com.tw/job/90v94"},
                }
            ],
            "metadata": {"pagination": {"total": 1, "lastPage": 1}},
        }

        items = main.extract_104_search_items(payload)
        job = main.search_item_to_job(items[0], "AI 專案經理")

        self.assertEqual(len(items), 1)
        self.assertEqual(job["job_id"], "90v94")
        self.assertEqual(job["company_name"], "測試公司")
        self.assertEqual(job["job_title"], "AI 專案經理")
        self.assertEqual(job["job_url"], "https://www.104.com.tw/job/90v94")
        self.assertIn("AI 工具", job["description"])


class DatabasePolicyTests(unittest.TestCase):
    def test_status_counts_include_zeroes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite"
            main.ensure_db(db_path)
            counts = main.db_status_counts(db_path)
            self.assertEqual(counts["found"], 0)
            self.assertEqual(counts["applied"], 0)

    def test_policy_rejects_same_company_already_applied_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite"
            main.ensure_db(db_path)
            main.db_upsert_job(
                {
                    "job_id": "oldjob",
                    "job_url": "https://www.104.com.tw/job/oldjob",
                    "company_name": "同公司",
                    "job_title": "AI PM",
                    "status": "applied",
                    "applied_at": main.get_now_iso(),
                },
                db_path,
            )
            job = {
                "job_id": "newjob",
                "job_url": "https://www.104.com.tw/job/newjob",
                "company_name": "同公司",
                "score": 90,
                "cover_letter": sample_config()["letter"]["required_sentence"] + " 我會以流程自動化協助團隊。",
            }
            allowed, reason = main.pass_policy(
                job,
                sample_config(),
                applied_this_run=0,
                companies_applied_this_run=set(),
                db_path=db_path,
            )
            self.assertFalse(allowed)
            self.assertEqual(reason, "COMPANY_DAILY_LIMIT_REACHED")

    def test_db_upsert_job_updates_existing_job_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite"
            main.ensure_db(db_path)
            first = {
                "job_id": "oldjob",
                "job_url": "https://www.104.com.tw/job/same",
                "company_name": "A公司",
                "job_title": "AI PM",
                "status": "found",
            }
            second = {
                "job_id": "newjob",
                "job_url": "https://www.104.com.tw/job/same",
                "company_name": "B公司",
                "job_title": "AI 自動化 PM",
                "status": "found",
            }
            self.assertTrue(main.db_upsert_job(first, db_path))
            self.assertTrue(main.db_upsert_job(second, db_path))
            row = main.db_get_job("newjob", db_path)
            self.assertIsNotNone(row)
            self.assertEqual(row["company_name"], "B公司")
            self.assertIsNone(main.db_get_job("oldjob", db_path))


class DashboardTests(unittest.TestCase):
    def test_dashboard_rows_and_summary_prepare_application_status_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite"
            main.ensure_db(db_path)
            main.db_upsert_job(
                {
                    "job_id": "applied1",
                    "job_url": "https://www.104.com.tw/job/applied1",
                    "company_name": "A <Company>",
                    "job_title": "AI PM",
                    "keyword": "AI PM",
                    "location": "Taipei",
                    "status": "applied",
                    "error": "browser_submit_success",
                    "applied_at": "2026-06-21T20:00:00",
                },
                db_path,
            )
            main.db_upsert_job(
                {
                    "job_id": "review1",
                    "job_url": "https://www.104.com.tw/job/review1",
                    "company_name": "B Company",
                    "job_title": "Digital Consultant",
                    "keyword": "digital",
                    "location": "New Taipei",
                    "status": "review_needed",
                    "error": "cloudflare_or_security_challenge",
                },
                db_path,
            )

            rows = main.dashboard_job_rows(db_path)
            summary = main.dashboard_summary(rows)

            self.assertEqual([row["job_id"] for row in rows], ["applied1", "review1"])
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["statuses"]["applied"], 1)
            self.assertEqual(summary["statuses"]["review_needed"], 1)

    def test_render_dashboard_html_embeds_escaped_rows_and_filters(self):
        rows = [
            {
                "job_id": "applied1",
                "company_name": "A <Company>",
                "job_title": "AI PM",
                "job_url": "https://www.104.com.tw/job/applied1",
                "status": "applied",
                "keyword": "AI PM",
                "location": "Taipei",
                "salary_text": "",
                "error": "",
                "score": None,
                "applied_at": "2026-06-21T20:00:00",
                "updated_at": "2026-06-21T20:01:00",
            }
        ]
        html = main.render_dashboard_html(
            rows,
            main.dashboard_summary(rows),
            generated_at="2026-06-21T20:02:00",
        )

        self.assertIn("applicationsData", html)
        self.assertIn("status-filter", html)
        self.assertIn("https://www.104.com.tw/job/applied1", html)
        self.assertIn("A \\u003cCompany\\u003e", html)
        self.assertNotIn("A <Company>", html)


class CommandFlowTests(unittest.TestCase):
    def test_auth_ready_accepts_persistent_browser_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = sample_config()
            config["browser"] = {
                "use_persistent_context": True,
                "channel": "chrome",
                "user_data_dir": "auth/chrome-profile",
            }
            with mock.patch.object(main, "AUTH_STATE_PATH", Path(tmp) / "missing.json"):
                self.assertTrue(main.auth_ready(config))

    def test_auth_ready_accepts_cdp_browser_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = sample_config()
            config["browser"] = {"cdp_endpoint": "http://127.0.0.1:9222"}
            with mock.patch.object(main, "AUTH_STATE_PATH", Path(tmp) / "missing.json"):
                self.assertTrue(main.auth_ready(config))
                self.assertTrue(main.browser_uses_cdp(config))
                self.assertFalse(main.browser_uses_persistent_context(config))

    def test_collect_can_skip_detail_fetch_and_store_search_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite"
            config = sample_config()
            config["search"] = {
                "keywords": ["AI 專案經理"],
                "pages_per_keyword": 1,
                "max_jobs_per_keyword": 1,
                "fetch_details": False,
            }
            config["limits"] = {"request_delay_seconds": 0}
            item = {
                "jobNo": "90v94",
                "jobName": "AI 專案經理",
                "custName": "測試公司",
                "jobAddrNoDesc": "台北市",
                "salaryDesc": "待遇面議",
                "description": "導入 AI 工具與流程自動化",
                "link": {"job": "https://www.104.com.tw/job/90v94"},
            }

            with mock.patch.object(main, "DB_PATH", db_path), \
                mock.patch.object(main, "load_config", return_value=config), \
                mock.patch.object(main, "fetch_104_jobs", return_value=[item]), \
                mock.patch.object(main, "fetch_104_job_detail") as mocked_detail:
                main.command_collect(mock.Mock())

            mocked_detail.assert_not_called()
            row = main.db_get_job("90v94", db_path)
            self.assertIsNotNone(row)
            self.assertEqual(row["company_name"], "測試公司")
            self.assertEqual(row["job_title"], "AI 專案經理")
            self.assertIn("流程自動化", row["full_text"])

    def test_score_without_llm_processes_all_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite"
            main.ensure_db(db_path)
            job_rows = [
                {
                    "job_id": "reject1",
                    "job_url": "https://www.104.com.tw/job/reject1",
                    "company_name": "A公司",
                    "job_title": "後端工程師",
                    "location": "台北",
                    "full_text": "C++",
                    "status": "found",
                },
                {
                    "job_id": "allow1",
                    "job_url": "https://www.104.com.tw/job/allow1",
                    "company_name": "B公司",
                    "job_title": "AI 自動化 PM",
                    "location": "台北",
                    "full_text": "AI 自動化",
                    "status": "found",
                },
                {
                    "job_id": "reject2",
                    "job_url": "https://www.104.com.tw/job/reject2",
                    "company_name": "C公司",
                    "job_title": "後端工程師",
                    "location": "台北",
                    "full_text": "C++",
                    "status": "found",
                },
            ]
            for row in job_rows:
                main.db_upsert_job(row, db_path)

            config = sample_config()
            config["llm"] = {"api_key": "", "base_url": "", "model": ""}
            with mock.patch.object(main, "DB_PATH", db_path), \
                mock.patch.object(main, "load_config", return_value=config), \
                mock.patch.object(main, "load_profile", return_value="profile"):
                main.command_score(mock.Mock())

            self.assertEqual(main.db_get_job("reject1", db_path)["status"], "skipped")
            self.assertEqual(main.db_get_job("allow1", db_path)["status"], "found")
            self.assertEqual(main.db_get_job("reject2", db_path)["status"], "skipped")

    def test_apply_processes_apply_ready_in_formal_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite"
            auth_path = Path(tmp) / "auth.json"
            auth_path.write_text("{}", encoding="utf-8")
            main.ensure_db(db_path)
            main.db_upsert_job(
                {
                    "job_id": "job1",
                    "job_url": "https://www.104.com.tw/job/job1",
                    "company_name": "A公司",
                    "job_title": "AI 自動化 PM",
                    "location": "台北",
                    "score": 95,
                    "reason": "ok",
                    "cover_letter": sample_config()["letter"]["required_sentence"] + " 我會持續優化流程。",
                    "status": "apply_ready",
                },
                db_path,
            )
            config = sample_config()
            config["mode"]["dry_run"] = False
            config["llm"] = {"api_key": "", "base_url": "", "model": ""}
            with mock.patch.object(main, "DB_PATH", db_path), \
                mock.patch.object(main, "AUTH_STATE_PATH", auth_path), \
                mock.patch.object(main, "load_config", return_value=config), \
                mock.patch.object(main, "apply_with_playwright", return_value=("applied", "", "shot.png")) as mocked_apply:
                main.command_apply(mock.Mock())

            self.assertEqual(mocked_apply.call_count, 1)
            self.assertEqual(main.db_get_job("job1", db_path)["status"], "applied")


if __name__ == "__main__":
    unittest.main()

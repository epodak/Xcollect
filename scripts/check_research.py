#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究闭环合同测试：中文问题、FTS5、类型化裁决、LLM 引证与 CLI 导出。"""
import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research import (
    topic_from_question, recall_bookmarks, judgement, finalize_report, run_research
)
from src.research_cloud import research_with_workers_ai
from src.research_direct import research_direct
from src.research_index import fts_query
from src.decision import make_request
from xcollect_cli import build_parser, save_research_bundle


BOOKMARKS = [
    {"id": "a", "title": "Opus 5.5 架构观察", "body_raw": "模型发布后提供 API 测试方法和比较。",
     "url": "https://x.com/sample/status/100", "created_at": "2026-10-01T00:00:00Z"},
    {"id": "b", "title": "Opus 5.5 买买买", "body_raw": "立即购买独家折扣，机会难得！",
     "url": "https://x.com/sample/status/200"},
    {"id": "c", "title": "完全无关的园艺", "body_raw": "今天的玫瑰花开了。"},
]


def verdict(topical=0.93, promotional=0.03):
    return {"model_id": "@cf/cloudflare/clef-flash", "answers": {
        "on_topic": {"type": "noul", "noul": topical},
        "promotional": {"type": "noul", "noul": promotional},
    }}


class ResearchTests(unittest.TestCase):
    def test_d1_fts_migration_tracks_updates_and_removals(self):
        migration = (ROOT / "scripts/migrations/0002_bookmarks_fts5.sql").read_text(encoding="utf-8")
        db = sqlite3.connect(":memory:")
        try:
            db.execute("CREATE TABLE tweets(id TEXT PRIMARY KEY, title TEXT, body_raw TEXT)")
            db.executescript(migration)
            db.execute("INSERT INTO tweets(id,title,body_raw) VALUES ('7','Jev','structured model')")
            self.assertEqual(db.execute(
                "SELECT count(*) FROM bookmark_fts WHERE bookmark_fts MATCH 'jev'"
            ).fetchone()[0], 1)
            db.execute("UPDATE tweets SET title='Clef' WHERE id='7'")
            self.assertEqual(db.execute(
                "SELECT count(*) FROM bookmark_fts WHERE bookmark_fts MATCH 'jev'"
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT count(*) FROM bookmark_fts WHERE bookmark_fts MATCH 'clef'"
            ).fetchone()[0], 1)
            db.execute("DELETE FROM tweets WHERE id='7'")
            self.assertEqual(db.execute(
                "SELECT count(*) FROM bookmark_fts WHERE bookmark_fts MATCH 'clef'"
            ).fetchone()[0], 0)
            self.assertNotIn("OR 1=1", fts_query('jev OR 1=1'))
        finally:
            db.close()

    def test_natural_language_recall(self):
        self.assertEqual(topic_from_question("我想了解 Opus 5.5"), "opus 5.5")
        self.assertEqual(topic_from_question("最近 Grok Bot 怎么样"), "grok bot")
        self.assertEqual(topic_from_question("帮我研究 jev"), "jev")
        items = recall_bookmarks(BOOKMARKS, "我想了解 Opus 5.5", 20)
        self.assertEqual({x["item"]["id"] for x in items}, {"a", "b"})
        self.assertEqual({x["item"]["id"] for x in recall_bookmarks(
            BOOKMARKS, "Opus 5.5", 20, use_fts=False)}, {"a", "b"})

    def test_judgment_applies_probabilities_not_quota(self):
        self.assertEqual(judgement(verdict(0.99, 0.95)), (False, "promotion"))
        self.assertEqual(judgement(verdict(0.08, 0.02)), (False, "off_topic"))
        self.assertEqual(judgement(verdict(0.89, 0.03)), (True, "accepted"))
        with self.assertRaises(ValueError):
            judgement({"answers": {"on_topic": {"noul": 0.8}}})

    def test_hallucinated_citation_fails_closed(self):
        with self.assertRaises(ValueError):
            finalize_report("Opus", "这是未经引用的结论。", [BOOKMARKS[0]])
        with self.assertRaises(ValueError):
            finalize_report("Opus", "虚构证据 [S999]", [BOOKMARKS[0]])
        text = finalize_report("Opus", "已有具体分析 [S1]", [BOOKMARKS[0]])
        self.assertIn("https://x.com/sample/status/100", text)

    def test_model_receives_question_as_typed_state(self):
        _, payload = make_request(BOOKMARKS[0], "clef-flash", "我想了解 Opus 5.5")
        self.assertEqual(payload["state"]["research_question"], "我想了解 Opus 5.5")
        self.assertIn("on_topic", payload["questions"])
        self.assertIn("promotional", payload["questions"])

    def test_cli_has_real_ask_research_commands(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["ask", "我想了解 Opus 5.5"]).command, "ask")
        self.assertEqual(parser.parse_args(["research", "Jev", "--out", "notes"]).command, "research")


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_route_research_auth_and_local_sources(self):
        sys.path.insert(0, str(ROOT / "src"))
        import entry as edge

        class Req:
            method = "POST"
            url = "https://x.daduiot.com/api/v1/research"
            headers = {"Authorization": "Bearer test-secret"}
            async def text(self):
                return json.dumps({"query": "Opus 5.5", "sources": [BOOKMARKS[0]],
                                   "max_candidates": 1}, ensure_ascii=False)

        class Env:
            XCOLLECT_API_TOKEN = "test-secret"

        async def fake_pipeline(env, question, candidates, **kwargs):
            self.assertEqual(question, "Opus 5.5")
            self.assertEqual(candidates[0]["item"]["id"], "a")
            return {"success": True, "report": "可信证据 [S1]",
                    "sources": [BOOKMARKS[0]], "decisions": [], "stats": {}}

        with patch.object(edge, "json_resp",
                          side_effect=lambda payload, status=200, cache_seconds=0: (status, payload)):
            with patch.object(edge, "research_with_workers_ai", fake_pipeline):
                code, result = await edge.on_fetch(Req(), Env())
                self.assertEqual(code, 200)
                self.assertEqual(result["retrieval_backend"], "client_candidate_recall")
                self.assertEqual(result["sources"][0]["id"], "a")
                class Denied:
                    XCOLLECT_API_TOKEN = ""
                code, result = await edge.on_fetch(Req(), Denied())
                self.assertEqual(code, 503)

    async def test_full_pipeline_filters_then_generates_report(self):
        called = {"judged": [], "generated": 0}

        async def judge(item, question):
            called["judged"].append((item["id"], question))
            return verdict(promotional=0.95 if item["id"] == "b" else 0.03)

        async def generate(messages):
            called["generated"] += 1
            self.assertEqual(messages[1]["role"], "user")
            evidence = json.loads(messages[1]["content"])["sources"]
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0]["id"], "a")
            return "模型架构值得研究 [S1]；尚无更多验证。"

        selected = recall_bookmarks(BOOKMARKS, "我想了解 Opus 5.5", 20)
        result = await run_research("我想了解 Opus 5.5", selected, judge, generate,
                                    model_name="fake-llm")
        self.assertEqual(result["stats"]["recalled"], 2)
        self.assertEqual(result["stats"]["judged"], 2)
        self.assertEqual(result["stats"]["accepted"], 1)
        self.assertEqual(called["generated"], 1)
        self.assertEqual([x["id"] for x in result["sources"]], ["a"])
        self.assertIn("[S1]", result["report"])
        self.assertEqual(next(x for x in result["decisions"] if x["source_id"] == "b")["reason"],
                         "promotion")
        with tempfile.TemporaryDirectory() as folder:
            save_research_bundle(result, folder)
            dest = Path(folder)
            self.assertIn("[S1]", (dest / "report.md").read_text(encoding="utf-8"))
            self.assertEqual(len((dest / "decisions.jsonl").read_text().splitlines()), 2)
            self.assertEqual(json.loads((dest / "sources.jsonl").read_text().splitlines()[0])["id"], "a")
            self.assertEqual(json.loads((dest / "research.json").read_text())["generation_model"],
                             "fake-llm")

    async def test_no_hits_and_no_acceptance_never_call_llm(self):
        async def judge(item, question):
            return verdict(topical=0.01)
        async def generate(messages):
            self.fail("无证据时不准生成综述")
        result = await run_research("Jev", [{"item": BOOKMARKS[0]}], judge, generate,
                                    model_name="fake-llm")
        self.assertEqual(result["stats"]["accepted"], 0)
        self.assertIsNone(result["generation_model"])

    async def test_real_adapter_joins_judge_and_generation(self):
        class FakeAI:
            def __init__(self):
                self.calls = []
            async def run(self, model, payload):
                self.calls.append(model)
                if model == "@cf/cloudflare/clef-flash":
                    return {"answers": verdict()["answers"]}
                return {"response": "来源描述了一个方法 [S1]，仍待验证。"}
        class Env:
            AI = FakeAI()
        env = Env()
        result = await research_with_workers_ai(
            env, "Opus 5.5", [{"item": BOOKMARKS[0]}],
            decision_model="clef-flash", generation_model="fake-generator",
        )
        self.assertEqual(env.AI.calls, ["@cf/cloudflare/clef-flash", "fake-generator"])
        self.assertEqual(result["stats"]["accepted"], 1)

    async def test_direct_provider_runs_decision_and_generation(self):
        received = []
        def fake_post(url, token, payload):
            received.append((url, payload))
            if "clef-flash" in url:
                return {"answers": verdict()["answers"]}
            return {"response": "这是技术分析的来源 [S1]"}
        with patch("src.research_direct._post_json", fake_post):
            result = await research_direct(
                "Opus 5.5", [{"item": BOOKMARKS[0]}],
                judge_model="clef-flash", generation_model="test-generator",
                max_candidates=1, account_id="exampleaccount",
                cloudflare_token="do-not-disclose", generator="workers",
            )
        self.assertEqual(len(received), 2)
        self.assertIn("/ai/run/@cf/cloudflare/clef-flash", received[0][0])
        self.assertIn("/ai/run/test-generator", received[1][0])
        self.assertEqual(result["stats"]["accepted"], 1)
        with self.assertRaises(ValueError):
            await research_direct(
                "Jev", [{"item": BOOKMARKS[0]}], judge_model="jev",
                generation_model="x", max_candidates=1,
                account_id="exampleaccount", cloudflare_token="secret",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

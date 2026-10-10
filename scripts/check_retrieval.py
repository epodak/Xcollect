#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Executable acceptance gate for the read-only retrieval/decision vertical slice."""
import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
import threading
from http.server import HTTPServer
from urllib.parse import urlencode
from urllib.request import urlopen
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.retrieval import export_bundle, query_terms, render_markdown, search_items
from src.decision import MODELS, make_request, evaluate_bookmark, parse_result


EXAMPLE = [
    {"id": "101", "title": "Claude Opus 5.5 coding benchmark", "body_raw": "Full technical analysis of Claude Opus 5.5.",
     "snippet": "Preview only", "author": "Alice", "url": "https://x.com/example/status/101",
     "created_at": "2026-10-03T10:00:00Z", "bookmark_position": 0},
    {"id": "102", "title": "Typesafe Jev", "body_raw": "Jev decision model and score.",
     "url": "https://x.com/example/status/102", "bookmark_position": 1},
    {"id": "../unsafe", "title": "Grok Bot", "body_raw": "Example text for Grok Bot",
     "url": "https://x.com/example/status/103", "bookmark_position": 2},
]


class RetrievalTests(unittest.TestCase):
    def test_alias_and_mixed_case(self):
        self.assertEqual(search_items(EXAMPLE, "OPUS-5.5")[0]["item"]["id"], "101")
        self.assertEqual(search_items(EXAMPLE, "jev")[0]["item"]["id"], "102")
        self.assertEqual(search_items(EXAMPLE, "Grok Bot")[0]["item"]["id"], "../unsafe")

    def test_no_broad_fake_semantic_matches(self):
        self.assertEqual(search_items(EXAMPLE, "unrelated semantic topic"), [])
        self.assertRaises(ValueError, search_items, EXAMPLE, "")
        self.assertRaises(ValueError, query_terms, "a" * 201)

    def test_source_is_not_mutated(self):
        before = json.dumps(EXAMPLE, sort_keys=True)
        found = search_items(EXAMPLE, "opus")
        self.assertEqual(before, json.dumps(EXAMPLE, sort_keys=True))
        self.assertEqual(found[0]["item"]["body_raw"], "Full technical analysis of Claude Opus 5.5.")

    def test_canonical_full_text(self):
        rendered = render_markdown(EXAMPLE[0])
        self.assertIn("Full technical analysis", rendered)
        self.assertNotIn("Preview only", rendered)
        self.assertIn("content_origin: body_raw", rendered)
        self.assertIn("https://x.com/example/status/101", rendered)

    def test_export_is_portable_and_traversal_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "bundle"
            manifest = export_bundle(EXAMPLE, "Grok Bot", dest)
            self.assertEqual(manifest["source_count"], 3)
            self.assertTrue((dest / "manifest.json").is_file())
            self.assertTrue((dest / "sources.jsonl").is_file())
            names = list((dest / "posts").glob("*.md"))
            self.assertEqual(len(names), 3)
            self.assertTrue(all(x.resolve().is_relative_to(dest.resolve()) for x in names))
            rows = [json.loads(line) for line in (dest / "sources.jsonl").read_text().splitlines()]
            self.assertEqual(rows[0]["body_raw"], EXAMPLE[0]["body_raw"])
            self.assertEqual((dest / "manifest.json").read_text().count("bookmarks_only"), 1)

    def test_cli_resolves_data_from_checkout_and_redacts_secrets(self):
        # Runs xcollect_cli.py by absolute path from arbitrary shell CWD.
        with tempfile.TemporaryDirectory() as folder:
            environment = dict(__import__("os").environ)
            environment["XCOLLECT_API_BASE"] = "https://private.example"
            environment["XCOLLECT_API_TOKEN"] = "SENTINEL_SECRET_NOT_IN_OUTPUT"
            environment.pop("XCOLLECT_DATA", None)
            run = subprocess.run(
                [sys.executable, str(ROOT / "xcollect_cli.py"), "doctor", "--json"],
                cwd=folder, env=environment, capture_output=True, text=True, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            diagnostic = json.loads(run.stdout)
            self.assertEqual(Path(diagnostic["data_path"]), ROOT / "data" / "xcollect.json")
            self.assertTrue(diagnostic["cloud_api_configured"])
            self.assertNotIn("SENTINEL_SECRET_NOT_IN_OUTPUT", run.stdout)
            override = str(Path(folder) / "private-bookmarks.json")
            environment["XCOLLECT_DATA"] = override
            rerun = subprocess.run(
                [sys.executable, str(ROOT / "xcollect_cli.py"), "doctor", "--json"],
                cwd=folder, env=environment, capture_output=True, text=True, check=False,
            )
            self.assertEqual(json.loads(rerun.stdout)["data_path"], override)

    def test_cli_with_local_json(self):
        with tempfile.TemporaryDirectory() as folder:
            data_file = Path(folder) / "xcollect.json"
            data_file.write_text(json.dumps(EXAMPLE, ensure_ascii=False), encoding="utf-8")
            run = subprocess.run(
                [sys.executable, "-m", "xcollect_cli", "--source", "local", "--data", str(data_file),
                 "search", "jev", "--json"], cwd=ROOT, capture_output=True, text=True, check=False
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["results"][0]["item"]["id"], "102")
            export = subprocess.run(
                [sys.executable, "-m", "xcollect_cli", "--data", str(data_file), "export",
                 "Opus 5.5", "--out", str(Path(folder) / "out")],
                cwd=ROOT, capture_output=True, text=True, check=False
            )
            self.assertEqual(export.returncode, 0, export.stderr)
            self.assertEqual(json.loads(export.stdout)["source_count"], 1)

    def test_cli_missing_source_never_creates_fake_bookmarks(self):
        with tempfile.TemporaryDirectory() as folder:
            nonexistent = Path(folder) / "nothing.json"
            run = subprocess.run(
                [sys.executable, "-m", "xcollect_cli", "--data", str(nonexistent), "search", "jev"],
                cwd=ROOT, capture_output=True, text=True, check=False
            )
            self.assertEqual(run.returncode, 2)
            self.assertFalse(nonexistent.exists())

    def test_model_payload_and_allowlist(self):
        model_id, req = make_request(EXAMPLE[0], "clef-flash")
        self.assertEqual(model_id, "@cf/cloudflare/clef-flash")
        self.assertEqual(req["model"], "clef-flash")
        self.assertEqual(set(req["questions"]), {"technical_content", "research_value", "content_type"})
        self.assertEqual(make_request(EXAMPLE[0], "jev")[0], "typesafe/jev")
        self.assertNotIn("model", make_request(EXAMPLE[0], "jev")[1])
        self.assertRaises(ValueError, make_request, EXAMPLE[0], "unknown")
        self.assertRaises(RuntimeError, parse_result, {"response": "made-up narrative"})


class LocalHttpTests(unittest.TestCase):
    def test_local_api_is_bookmarks_only(self):
        import local_server
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "bookmarks.json"
            db.write_text(json.dumps(EXAMPLE), encoding="utf-8")
            with patch.object(local_server, "DB_FILE", str(db)):
                server = HTTPServer(("127.0.0.1", 0), local_server.CuratedPortalHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    root = f"http://127.0.0.1:{server.server_port}"
                    with urlopen(root + "/api/v1/search?" + urlencode({"q": "jev"}), timeout=3) as response:
                        payload = json.load(response)
                    self.assertEqual(payload["scope"], "bookmarks_only")
                    self.assertEqual(payload["results"][0]["item"]["id"], "102")
                    with urlopen(root + "/api/v1/items/101", timeout=3) as response:
                        item = json.load(response)["item"]
                    self.assertEqual(item["body_raw"], EXAMPLE[0]["body_raw"])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)


class CloudHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_gate_before_bookmark_read(self):
        sys.path.insert(0, str(ROOT / "src"))
        import entry as edge
        class Request:
            method = "GET"
            url = "https://private.example/api/v1/search?q=jev"
            def __init__(self, auth=""):
                self.headers = {"Authorization": auth}
        class Env:
            XCOLLECT_API_TOKEN = "test-secret"
        class NoSecret:
            pass
        async def read_back(env):
            return {"success": True, "data": EXAMPLE}
        with patch.object(edge, "json_resp", side_effect=lambda data, status=200, cache_seconds=0: (status, data)):
            with patch.object(edge, "load_tweets", read_back):
                missing = await edge.on_fetch(Request("Bearer test-secret"), NoSecret())
                denied = await edge.on_fetch(Request("Bearer wrong"), Env())
                allowed = await edge.on_fetch(Request("Bearer test-secret"), Env())
        self.assertEqual(missing[0], 503)
        self.assertEqual(denied[0], 401)
        self.assertEqual(allowed[0], 200)
        self.assertEqual(allowed[1]["results"][0]["item"]["id"], "102")


class DecisionAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_inference_and_missing_binding(self):
        class FakeAI:
            async def run(self, name, payload):
                self.called = name
                return {"model": "fake", "answers": {"technical_content": {"type": "noul", "noul": 0.7}}}
        class Env:
            AI = FakeAI()
        env = Env()
        result = await evaluate_bookmark(env, EXAMPLE[0], "clef")
        self.assertEqual(env.AI.called, "@cf/cloudflare/clef")
        self.assertEqual(result["source_id"], "101")
        self.assertEqual(result["answers"]["technical_content"]["noul"], 0.7)
        with self.assertRaises(RuntimeError):
            await evaluate_bookmark(object(), EXAMPLE[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)

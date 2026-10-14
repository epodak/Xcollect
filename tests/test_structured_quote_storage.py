#!/usr/bin/env python3
"""Offline D1 regression: nullable quoted_tweet JSON is upgraded and round-tripped."""
import asyncio
import json
import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from storage import (
    _ensure_quoted_tweet_column, _json_quote, invalidate_cache,
    load_tweets, save_tweets,
)


class Statement:
    def __init__(self, connection, sql):
        self.connection = connection
        self.sql = sql
        self.args = ()

    def bind(self, *args):
        self.args = args
        return self

    async def run(self):
        self.connection.execute(self.sql, self.args)
        self.connection.commit()
        return SimpleNamespace(success=True)

    async def all(self):
        result = self.connection.execute(self.sql, self.args)
        return SimpleNamespace(results=[dict(row) for row in result.fetchall()])


class D1:
    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        return Statement(self.connection, sql)


class QuoteStorageTests(unittest.TestCase):
    def test_upgrade_is_idempotent(self):
        async def case():
            db = sqlite3.connect(":memory:")
            db.row_factory = sqlite3.Row
            db.execute("CREATE TABLE tweets (id TEXT PRIMARY KEY)")
            env = SimpleNamespace(DB=D1(db))
            await _ensure_quoted_tweet_column(env)
            await _ensure_quoted_tweet_column(env)
            columns = {row[1] for row in db.execute("PRAGMA table_info(tweets)")}
            self.assertIn("quoted_tweet", columns)
            db.close()
        asyncio.run(case())

    def test_read_legacy_and_round_trip_new_source(self):
        async def case():
            db = sqlite3.connect(":memory:")
            db.row_factory = sqlite3.Row
            schema = (ROOT / "scripts/schema.sql").read_text(encoding="utf-8")
            # Simulate an existing production D1 schema predating quote structures.
            schema = schema.replace(
                "    quoted_tweet TEXT, -- JSON object; independent of primary body_raw\n", ""
            )
            db.executescript(schema)
            env = SimpleNamespace(DB=D1(db))
            q = {
                "id": "123", "author": "Finn", "username": "finn",
                "url": "https://x.com/finn/status/123",
                "avatar": "", "created_at": "",
                "body_raw": "Quoted A\n\nQuoted B",
                "images": ["https://pbs.twimg.com/img.jpg"],
                "videos": [],
            }
            item = {
                "id": "200", "author": "Main", "username": "main",
                "body_raw": "Only main text",
                "quoted_tweet": q, "title": "Only main text",
            }
            success, reason, _ = await save_tweets(env, [item], refresh_existing=True)
            self.assertTrue(success, reason)
            raw = db.execute("SELECT body_raw, quoted_tweet FROM tweets WHERE id = '200'").fetchone()
            self.assertEqual(raw["body_raw"], "Only main text")
            self.assertEqual(json.loads(raw["quoted_tweet"]), q)
            invalidate_cache()
            loaded = await load_tweets(env, bypass_cache=True)
            self.assertTrue(loaded["success"], loaded)
            found = next(x for x in loaded["data"] if x["id"] == "200")
            self.assertEqual(found["body_raw"], "Only main text")
            self.assertEqual(found["quoted_tweet"], q)

            # Fresh non-quote source replaces stale relation on full reconciliation.
            item["quoted_tweet"] = None
            success, reason, _ = await save_tweets(env, [item], refresh_existing=True)
            self.assertTrue(success, reason)
            invalidate_cache()
            loaded = await load_tweets(env, bypass_cache=True)
            found = next(x for x in loaded["data"] if x["id"] == "200")
            self.assertIsNone(found["quoted_tweet"])
            self.assertIsNone(_json_quote("invalid json"))
            db.close()
        asyncio.run(case())


if __name__ == "__main__":
    unittest.main()

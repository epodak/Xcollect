#!/usr/bin/env python3
"""Regression: Topic Watch polls independently and batches D1 matches."""
import asyncio
import json
import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from watch import (
    ensure_watch_schema, watch_poll_due, record_watch_poll, watch_status,
    save_matches, _quarter_hour_slot,
)


class D1Query:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()

    def bind(self, *args):
        self.args = args
        return self

    async def run(self):
        self.db.statements.append(self.sql)
        self.db.conn.execute(self.sql, self.args)
        self.db.conn.commit()
        return SimpleNamespace(success=True)

    async def all(self):
        self.db.statements.append(self.sql)
        return SimpleNamespace(
            results=[dict(row) for row in self.db.conn.execute(self.sql, self.args).fetchall()]
        )


class D1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.statements = []
        self.conn.execute("CREATE TABLE meta_kv(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
        self.conn.commit()

    def prepare(self, sql):
        return D1Query(self, sql)


class TopicWatchRuntimeTests(unittest.TestCase):
    def test_cron_slot_due_independent_of_global(self):
        async def case():
            db = D1()
            env = SimpleNamespace(DB=db)
            await ensure_watch_schema(env)
            dt = datetime(2026, 10, 10, 20, 1, tzinfo=timezone.utc)
            self.assertEqual(_quarter_hour_slot(dt), "2026-10-10T20:00:00+00:00")
            self.assertFalse(await watch_poll_due(env, now=dt))  # no active watch
            db.conn.execute(
                "INSERT INTO watch_topics "
                "(id,title,intent,directions_json,state,created_at,updated_at) "
                "VALUES ('a','Opus 5.5','Find examples','[]','active','x','x')"
            )
            db.conn.commit()
            self.assertTrue(await watch_poll_due(env, now=dt))
            await record_watch_poll(
                env, [{"query": '"Opus 5.5"', "pulled_count": 0}], 0, now=dt
            )
            self.assertFalse(await watch_poll_due(
                env, now=datetime(2026, 10, 10, 20, 14, tzinfo=timezone.utc)
            ))
            self.assertTrue(await watch_poll_due(
                env, now=datetime(2026, 10, 10, 20, 15, tzinfo=timezone.utc)
            ))
            status = await watch_status(env)
            self.assertEqual(status["summary"]["state"], "success")
            self.assertEqual(status["summary"]["accepted_count"], 0)
        asyncio.run(case())

    def test_bulk_insert_bounds_sql_count(self):
        async def case():
            db = D1()
            env = SimpleNamespace(DB=db)
            await ensure_watch_schema(env)
            rows = [("topic1", str(i), "opus") for i in range(205)]
            before = len(db.statements)
            self.assertEqual(await save_matches(env, rows), 205)
            sqls = db.statements[before:]
            inserts = [q for q in sqls if "INSERT OR IGNORE INTO watch_candidate_matches" in q]
            self.assertEqual(len(inserts), 3)  # 100 + 100 + 5
            count = db.conn.execute("SELECT COUNT(*) FROM watch_candidate_matches").fetchone()[0]
            self.assertEqual(count, 205)
            await save_matches(env, rows)
            self.assertEqual(db.conn.execute(
                "SELECT COUNT(*) FROM watch_candidate_matches"
            ).fetchone()[0], 205)
        asyncio.run(case())

    def test_failure_and_empty_are_not_confused(self):
        async def case():
            db = D1()
            env = SimpleNamespace(DB=db)
            await ensure_watch_schema(env)
            dt = datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc)
            err = await record_watch_poll(
                env, [{"query": "opus", "error": "HTTP 403",
                       "pulled_count": 0}], 0, now=dt
            )
            self.assertEqual(err["state"], "failed")
            no_matches = await record_watch_poll(
                env, [{"query": "opus", "pulled_count": 0,
                       "accepted_count": 0}], 0, now=dt
            )
            self.assertEqual(no_matches["state"], "success")
            self.assertEqual((await watch_status(env))["summary"]["state"], "success")
        asyncio.run(case())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Offline D1-like regression for X-confirmed Discovery conversion signals."""
import asyncio
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from discovery import eligible_confirmed_discovery_rows, reconcile_verified_discovery_bookmarks
from storage import record_feedback_event


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
        rows = self.connection.execute(self.sql, self.args).fetchall()
        return SimpleNamespace(results=[dict(row) for row in rows])


class D1:
    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        return Statement(self.connection, sql)


class VerifiedBookmarkTests(unittest.TestCase):
    def test_only_x_returned_and_fresh_candidates_eligible(self):
        now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        fresh = (now - timedelta(hours=2)).isoformat()
        old = (now - timedelta(hours=25)).isoformat()
        rows = [
            {"tweet_id": "1", "state": "selected", "created_at": fresh},
            {"tweet_id": "2", "state": "selected", "created_at": fresh},
            {"tweet_id": "3", "state": "hidden", "created_at": fresh},
            {"tweet_id": "4", "state": "rejected", "created_at": fresh},
            {"tweet_id": "5", "state": "selected", "created_at": old},
            {"tweet_id": "6", "state": "saved_pending", "created_at": old},
        ]
        eligible = eligible_confirmed_discovery_rows(
            rows, {"1", "3", "4", "5", "6"}, now=now
        )
        self.assertEqual([x["tweet_id"] for x in eligible], ["1", "6"])

    def test_verified_conversion_is_idempotent_and_calibrates_original(self):
        async def case():
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            env = SimpleNamespace(DB=D1(connection))
            connection.execute("CREATE TABLE tweets (id TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO tweets (id) VALUES ('101')")
            now = datetime.now(timezone.utc)
            ts = now.isoformat()
            # ensure_discovery_schema establishes the other tables and indexes.
            from discovery import ensure_discovery_schema
            await ensure_discovery_schema(env)
            connection.execute(
                "INSERT INTO discovery_candidates "
                "(tweet_id, first_seen_at, last_seen_at, discovery_date, "
                "created_at, state, category, sub_category, discovery_query) "
                "VALUES ('101',?,?,?,?,?,?,?,?)",
                (ts, ts, now.date().isoformat(), ts, "selected",
                 "technology", "ai", "ai agents"),
            )
            connection.commit()
            ok, _, _ = await record_feedback_event(
                env, "open-original-101", "101", "open_original",
                {"category": "technology", "discovery_query": "ai agents"},
            )
            self.assertTrue(ok)
            missing = await reconcile_verified_discovery_bookmarks(env, ["999"])
            self.assertEqual(missing["confirmed"], 0)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM feedback_events WHERE action='bookmark'"
                ).fetchone()[0], 0,
            )

            first = await reconcile_verified_discovery_bookmarks(env, ["101"])
            self.assertEqual(first["errors"], [])
            self.assertEqual(first["confirmed"], 1)
            self.assertEqual(connection.execute(
                "SELECT state FROM discovery_candidates WHERE tweet_id='101'"
            ).fetchone()[0], "saved")

            again = await reconcile_verified_discovery_bookmarks(env, ["101"])
            self.assertEqual(again["confirmed"], 0)
            self.assertEqual(again["already_recorded"], 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM feedback_events WHERE action='bookmark'"
            ).fetchone()[0], 1)
            stats = connection.execute(
                "SELECT exposures, conversions FROM learning_action_stats "
                "WHERE action='open_original'"
            ).fetchone()
            self.assertIsNotNone(stats)
            self.assertAlmostEqual(stats["exposures"], 1.0, places=2)
            self.assertAlmostEqual(stats["conversions"], 1.0, places=2)
            connection.close()

        asyncio.run(case())


if __name__ == "__main__":
    unittest.main()

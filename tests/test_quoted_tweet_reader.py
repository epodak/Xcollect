#!/usr/bin/env python3
"""Regression: quoted X status stays one portable, attributed Markdown object."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.twitter import normalize_tweet_result, _append_quoted_tweet, extract_quoted_tweet


class QuotedTweetContractTests(unittest.TestCase):
    def fixture(self):
        return {
            "rest_id": "200",
            "core": {
                "user_results": {"result": {
                    "core": {"name": "Main Author", "screen_name": "main_author"}
                }}
            },
            "legacy": {"full_text": "主推文第一段。\n\n主推文第二段。"},
            "quoted_status_result": {"result": {
                "__typename": "TweetWithVisibilityResults",
                "tweet": {
                    "rest_id": "123",
                    "core": {
                        "user_results": {"result": {
                            "core": {"name": "Finn Voorhees", "screen_name": "finnvoorhees"}
                        }}
                    },
                    "legacy": {"full_text": "legacy short"},
                    "note_tweet": {"note_tweet_results": {"result": {
                        "text": "Say goodbye to your Mac mini\n\nYour agent should live in your pocket."
                    }}},
                },
            }},
        }

    def test_quote_is_one_continuous_markdown_block_with_source(self):
        normalized = normalize_tweet_result(self.fixture())
        body = normalized["body_raw"]
        self.assertIn("主推文第一段。\n\n主推文第二段。", body)
        self.assertIn("> **引用推文** · Finn Voorhees", body)
        self.assertIn(
            "[@finnvoorhees](https://x.com/finnvoorhees/status/123)", body)
        self.assertIn(
            "> Say goodbye to your Mac mini\n>\n> Your agent should live in your pocket.",
            body,
        )
        self.assertNotIn("\n---\n", body)

    def test_structured_quote_is_separate_from_primary_content(self):
        normalized = normalize_tweet_result(self.fixture())
        self.assertEqual(normalized["body_raw"], "主推文第一段。\n\n主推文第二段。")
        self.assertNotIn("Finn", normalized["body_raw"])
        quote = normalized["quoted_tweet"]
        self.assertEqual(quote["id"], "123")
        self.assertEqual(quote["author"], "Finn Voorhees")
        self.assertEqual(quote["username"], "finnvoorhees")
        self.assertEqual(quote["url"], "https://x.com/finnvoorhees/status/123")
        self.assertEqual(
            quote["body_raw"],
            "Say goodbye to your Mac mini\n\nYour agent should live in your pocket.",
        )
        self.assertEqual(quote["images"], [])
        self.assertEqual(quote["videos"], [])
        self.assertNotIn("Finn", normalized["snippet"])

    def test_quote_media_and_author_avatar_are_independent(self):
        root = self.fixture()
        quote = root["quoted_status_result"]["result"]["tweet"]
        quote["core"]["user_results"]["result"]["avatar"] = {
            "image_url": "https://pbs.twimg.com/finn_normal.jpg"
        }
        quote["legacy"]["created_at"] = "Mon Oct 12 12:00:00 +0000 2026"
        quote["legacy"]["extended_entities"] = {"media": [
            {"type": "photo", "media_url_https": "https://pbs.twimg.com/quote.jpg"}
        ]}
        normalized = normalize_tweet_result(root)
        self.assertEqual(normalized["quoted_tweet"]["images"], ["https://pbs.twimg.com/quote.jpg"])
        self.assertEqual(normalized["images"], [])
        self.assertIn("_400x400", normalized["quoted_tweet"]["avatar"])
        self.assertEqual(normalized["quoted_tweet"]["created_at"], "Mon Oct 12 12:00:00 +0000 2026")

    def test_missing_quote_returns_none(self):
        root = self.fixture()
        root.pop("quoted_status_result")
        self.assertIsNone(extract_quoted_tweet(root))
        self.assertIsNone(normalize_tweet_result(root)["quoted_tweet"])

    def test_no_quote_has_no_phantom_placeholder(self):
        self.assertEqual(_append_quoted_tweet("Main body", {}), "Main body")
        missing = self.fixture()
        del missing["quoted_status_result"]["result"]["tweet"]["note_tweet"]
        missing["quoted_status_result"]["result"]["tweet"]["legacy"]["full_text"] = ""
        self.assertEqual(_append_quoted_tweet("Main body", missing), "Main body")

    def test_no_nesting_is_inferred(self):
        source = self.fixture()
        embedded = source["quoted_status_result"]["result"]["tweet"]
        embedded["quoted_status_result"] = {"result": {
            "rest_id": "99", "legacy": {"full_text": "UNREQUESTED SECOND NEST"}
        }}
        self.assertNotIn("UNREQUESTED SECOND NEST", normalize_tweet_result(source)["body_raw"])


if __name__ == "__main__":
    unittest.main()

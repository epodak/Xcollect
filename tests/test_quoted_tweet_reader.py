#!/usr/bin/env python3
"""Regression: quoted X status stays one portable, attributed Markdown object."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.twitter import normalize_tweet_result, _append_quoted_tweet


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

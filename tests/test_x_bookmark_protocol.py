#!/usr/bin/env python3
"""Offline regression for the X bookmark GraphQL mutation protocol."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from x_bookmark_protocol import (
    operation_name, query_id_candidates, mutation_payload, interpret_mutation_response,
)

class BookmarkProtocolTests(unittest.TestCase):
    def setUp(self):
        self.id = "aoDbu3RHznuiSkQ9aNM67Q"
        self.delete = "Wlmlj2-xzyS1GN3a6cj-mQ"

    def test_create_payload_contains_required_query_id(self):
        payload = json.loads(mutation_payload("2108632690761314597", self.id))
        self.assertEqual(payload, {"variables": {"tweet_id": "2108632690761314597"}, "queryId": self.id})

    def test_delete_payload_contains_required_query_id(self):
        self.assertEqual(json.loads(mutation_payload("123", self.delete))["queryId"], self.delete)

    def test_registry_id_first_and_legacy_fallback(self):
        registry = {"CreateBookmark": {"queryId": "NEWnew1234567",
                    "@method": "POST", "@path": "/i/api/graphql/NEWnew1234567/CreateBookmark",
                    "variables": {"tweet_id": "1"}}}
        self.assertEqual(query_id_candidates("create", registry, self.id),
                         ["NEWnew1234567", self.id])

    def test_invalid_registry_ignored(self):
        registry = {"CreateBookmark": {"queryId": "fakefake123",
                    "@method": "GET", "@path": "/i/api/graphql/fakefake123/CreateBookmark",
                    "variables": {"tweet_id": "1"}}}
        self.assertEqual(query_id_candidates("create", registry, self.id), [self.id])

    def test_same_id_deduped(self):
        registry = {"CreateBookmark": {"queryId": self.id, "@method": "POST",
                    "@path": f"/i/api/graphql/{self.id}/CreateBookmark",
                    "variables": {"tweet_id": "1"}}}
        self.assertEqual(query_id_candidates("create", registry, self.id), [self.id])

    def test_bad_action_and_tweet_fail_closed(self):
        with self.assertRaises(ValueError):
            operation_name("invalid")
        with self.assertRaises(ValueError):
            mutation_payload("https://x.com/tweet/1", self.id)

    def test_404_is_diagnosed_not_as_json_error(self):
        ok, detail = interpret_mutation_response("create", 404, "", self.id)
        self.assertFalse(ok)
        self.assertIn("x-client-transaction-id", detail)
        self.assertIn("404", detail)

    def test_graphql_errors_fail_closed(self):
        ok, _ = interpret_mutation_response("create", 200, '{"errors":[{"message":"Bad auth"}]}', self.id)
        self.assertFalse(ok)

    def test_200_without_data_does_not_promote_discovery(self):
        for body in ('{}', '{"data":null}', '<html></html>'):
            ok, _ = interpret_mutation_response("create", 200, body, self.id)
            self.assertFalse(ok)

    def test_success_requires_data(self):
        ok, _ = interpret_mutation_response(
            "create", 200, '{"data":{"bookmark_tweet_result":{"result":{}}}}', self.id)
        self.assertTrue(ok)

    def test_rate_limit_and_auth_classification(self):
        for code in (401, 403, 429):
            ok, message = interpret_mutation_response("delete", code, "", self.delete)
            self.assertFalse(ok)
            self.assertIn(str(code), message)

if __name__ == "__main__":
    unittest.main()

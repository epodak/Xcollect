"""Offline contract tests: no GitHub/X network requests and no user credentials."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("watch_x_upstreams", ROOT / "scripts/watch_x_upstreams.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def operation_fixture():
    return {
        name: {
            "queryId": "EXAMPLEid1234_" + name,
            "@path": "/i/api/graphql/EXAMPLEid1234_" + name + "/" + name,
            "@method": method,
            "variables": {key: "sample" for key in required},
        }
        for name, (_, method, required) in watch.OPERATIONS.items()
    }


class WatchContractTests(unittest.TestCase):
    def setUp(self):
        self.registry = operation_fixture()
        self.config = {
            key: self.registry[name]["queryId"]
            for name, (key, _, _) in watch.OPERATIONS.items()
        }
        self.entry = {
            "repo": "sample/example", "branch": "main", "path": "registry.json",
            "role": "graphql_registry", "sha": "a" * 40,
        }
        self.manifest = {"files": [self.entry]}

    def run_evaluation(self, registry=None, sha=None):
        data = json.dumps(registry if registry is not None else self.registry).encode()
        return watch.evaluate(self.manifest, {"twitter": self.config},
                              lambda _: (sha or "a" * 40, data))

    def test_matching_contract_is_clean(self):
        result = self.run_evaluation()
        self.assertFalse(result["needs_review"])
        self.assertFalse(result["alerts"])

    def test_sha_change_is_alerted(self):
        result = self.run_evaluation(sha="b" * 40)
        self.assertTrue(result["needs_review"])
        self.assertIn("Upstream file changed", result["alerts"][0])

    def test_query_id_rotation_is_alerted(self):
        self.registry["CreateBookmark"]["queryId"] = "updatedID1234"
        self.registry["CreateBookmark"]["@path"] = "/i/api/graphql/updatedID1234/CreateBookmark"
        result = self.run_evaluation()
        self.assertIn("config queryId differs", " ".join(result["alerts"]))

    def test_write_method_change_is_alerted(self):
        self.registry["DeleteBookmark"]["@method"] = "GET"
        result = self.run_evaluation()
        self.assertIn("method changed", " ".join(result["alerts"]))

    def test_variable_schema_change_is_alerted(self):
        self.registry["CreateBookmark"]["variables"] = {"new_key": "bad"}
        result = self.run_evaluation()
        self.assertIn("variable keys changed", " ".join(result["alerts"]))

    def test_error_is_never_reported_as_clean(self):
        def unavailable(_):
            raise ValueError("upstream unavailable")
        result = watch.evaluate(self.manifest, {"twitter": self.config}, unavailable)
        self.assertTrue(result["needs_review"])
        self.assertTrue(result["errors"])
        self.assertIn("No working GraphQL registry", result["errors"][-1])

    def test_missing_registry_operation_is_alerted(self):
        del self.registry["DeleteBookmark"]
        result = self.run_evaluation()
        self.assertIn("missing operation", " ".join(result["alerts"]))

    def test_markdown_contains_review_url(self):
        result = self.run_evaluation(sha="b" * 40)
        text = watch.render_markdown(result)
        self.assertIn("https://github.com/sample/example/blob/main/registry.json", text)
        self.assertIn("DRIFT", text)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Read-only upstream X Web GraphQL drift monitor for GitHub Actions.

Never calls x.com, performs writes, uses user cookies, or auto-applies query IDs.
Baseline SHA values are reviewed, not an auto-updated "last seen" cache.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tomllib
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
OPERATIONS = {
    "CreateBookmark": ("query_id_create", "POST", {"tweet_id"}),
    "DeleteBookmark": ("query_id_delete", "POST", {"tweet_id"}),
    "Bookmarks": ("query_id_bookmarks", "GET", {"count"}),
    "SearchTimeline": ("query_id_search", "GET", {"rawQuery", "product"}),
}
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def github_content(source: dict, token: str = "") -> tuple[str, bytes]:
    repo, path, branch = (source[k] for k in ("repo", "path", "branch"))
    uri = (f"https://api.github.com/repos/{repo}/contents/"
           f"{quote(path, safe='/')}?ref={quote(branch, safe='')}")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Xcollect-upstream-watch/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(uri, headers=headers)
    with urlopen(req, timeout=25) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        raise ValueError("GitHub Contents returned an unsupported response")
    raw = base64.b64decode(payload["content"], validate=False)
    expected = "blob " + str(len(raw)) + "\0"
    computed = hashlib.sha1(expected.encode("ascii") + raw).hexdigest()
    if computed != payload.get("sha"):
        raise ValueError("GitHub blob SHA verification failed")
    return computed, raw


def compare_registry(raw: bytes, twitter_config: dict) -> list[str]:
    """Compare operation name, URL, HTTP method and variable keys to local defaults."""
    problems = []
    try:
        registry = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        return ["Registry is not valid JSON: " + str(error)]
    if not isinstance(registry, dict):
        return ["Registry root must be an object"]

    for operation, (config_key, method, variables) in OPERATIONS.items():
        record = registry.get(operation)
        if not isinstance(record, dict):
            problems.append(operation + ": missing operation")
            continue
        query_id = record.get("queryId")
        if not isinstance(query_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", query_id):
            problems.append(operation + ": invalid/missing queryId")
            continue
        declared_path = record.get("@path")
        expected_path = f"/i/api/graphql/{query_id}/{operation}"
        if declared_path != expected_path:
            problems.append(operation + ": GraphQL endpoint path changed: " + str(declared_path))
        current_method = str(record.get("@method") or "").upper()
        if current_method != method:
            problems.append(operation + f": method changed ({method} -> {current_method})")
        supplied = record.get("variables")
        if not isinstance(supplied, dict) or not variables.issubset(supplied):
            problems.append(operation + ": variable keys changed or missing")
        configured_id = str(twitter_config.get(config_key) or "")
        if query_id != configured_id:
            problems.append(operation + f": config queryId differs ({configured_id} -> {query_id})")
    return problems


def evaluate(manifest: dict, config: dict, fetcher) -> dict:
    sources, alerts, errors = [], [], []
    seen = set()
    for entry in manifest.get("files", []):
        repo, path = entry["repo"], entry["path"]
        key = repo + "/" + path
        if key in seen:
            errors.append("Duplicate upstream watch path: " + key)
            continue
        seen.add(key)
        expected = entry["sha"]
        if not SHA_PATTERN.fullmatch(expected):
            errors.append("Invalid reviewed SHA baseline: " + key)
            continue
        link = f"https://github.com/{repo}/blob/{entry['branch']}/{path}"
        item = {"repo": repo, "path": path, "role": entry["role"],
                "baseline_sha": expected, "url": link}
        try:
            actual, raw = fetcher(entry)
            if not SHA_PATTERN.fullmatch(actual):
                raise ValueError("Invalid returned SHA")
            item["observed_sha"] = actual
            item["changed"] = actual != expected
            if item["changed"]:
                alerts.append("Upstream file changed: " + link
                              + f" (reviewed {expected[:12]}, current {actual[:12]})")
            if entry["role"] == "graphql_registry":
                problems = compare_registry(raw, config.get("twitter", {}))
                alerts.extend("Protocol contract: " + text for text in problems)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as error:
            item["error"] = str(error)[:240]
            errors.append("Could not inspect " + link + ": " + item["error"])
        sources.append(item)

    if not any(row["role"] == "graphql_registry" and "observed_sha" in row for row in sources):
        errors.append("No working GraphQL registry: protocol check incomplete")

    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "needs_review": bool(alerts or errors), "alerts": alerts, "errors": errors,
            "sources": sources}


def render_markdown(report: dict) -> str:
    label = "ACTION REQUIRED" if report["needs_review"] else "No upstream drift detected"
    lines = ["## Xcollect upstream X protocol watch — " + label, "",
             "This is a read-only source audit, **not** an authenticated X API smoke test.",
             "No production query IDs or secrets have been changed.", ""]
    for key, caption in (("alerts", "Review"), ("errors", "Fetch/check failures")):
        lines.append("### " + caption)
        rows = report.get(key) or []
        lines.extend("- " + x for x in rows) if rows else lines.append("- None")
        lines.append("")
    lines.extend(["### Watched sources", "",
                  "| Upstream file | Reviewed SHA | Observed SHA | State |",
                  "| --- | --- | --- | --- |"])
    for row in report["sources"]:
        status = "ERROR" if row.get("error") else ("DRIFT" if row.get("changed") else "OK")
        lines.append(f"| [{row['repo']}/{row['path']}]({row['url']}) "
                     f"| `{row['baseline_sha'][:12]}` "
                     f"| `{row.get('observed_sha', 'unknown')[:12]}` | {status} |")
    lines.append("")
    lines.append("Resolution: review the upstream diff, update the adapter and tests if needed, "
                 "then update the reviewed file SHA in scripts/upstream_sources.json. "
                 "Never auto-publish unvalidated X private API definitions.")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(ROOT / "scripts/upstream_sources.json"))
    parser.add_argument("--config", default=str(ROOT / "config.toml"))
    parser.add_argument("--output", default="upstream-watch-report.json")
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    config = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    token = os.environ.get("GITHUB_TOKEN", "")
    report = evaluate(manifest, config, lambda entry: github_content(entry, token))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = render_markdown(report)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as file:
            file.write(summary)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as file:
            file.write("needs_review=" + str(report["needs_review"]).lower() + "\n")
    # Drift is a review signal, not a production deployment failure.
    # Network errors remain explicit in the issue/report rather than being confused with "all clear".
    return 0


if __name__ == "__main__":
    sys.exit(main())

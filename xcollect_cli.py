#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Xcollect local/cloud read-only CLI (Python 3.10+; no third-party packages)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from src.retrieval import export_bundle, search_items


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect must never forward the bearer secret to a different host.
        return None


def api_request(base: str, token: str, path: str, payload: dict | None = None) -> dict:
    if not token:
        raise ValueError("XCOLLECT_API_TOKEN is required for cloud mode")
    base = base.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        raise ValueError("Cloud API must use HTTPS (HTTP permitted for localhost only)")
    if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Invalid --api-base URL")
    url = base + path
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }, method="POST" if body is not None else "GET")
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            data = json.load(response)
    except HTTPError as err:
        raise RuntimeError(f"Cloud API HTTP {err.code}; check authentication and endpoint") from None
    except URLError as err:
        raise RuntimeError(f"Cloud API unavailable: {err.reason}") from None
    if not isinstance(data, dict) or not data.get("success", False):
        raise RuntimeError("Cloud API did not return success")
    return data


def read_local(path: str) -> list[dict]:
    file = Path(path).expanduser()
    if not file.is_file():
        raise FileNotFoundError(f"Bookmark file not found: {file}; synchronize Local Profile first")
    data = json.loads(file.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("Bookmark JSON must be a list")
    return [item for item in data if isinstance(item, dict)]


def get_results(args) -> list[dict]:
    if args.source == "local":
        return search_items(read_local(args.data), args.query, args.limit)
    path = "/api/v1/search?" + urlencode({"q": args.query, "limit": args.limit})
    return api_request(args.api_base, args.token, path)["results"]


def get_item(args) -> dict:
    if args.source == "local":
        matches = [item for item in read_local(args.data) if str(item.get("id")) == args.id]
        if not matches:
            raise LookupError("Bookmark not found")
        return matches[0]
    path = "/api/v1/items/" + quote(args.id, safe="")
    return api_request(args.api_base, args.token, path)["item"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xcollect", description="Read and export Xcollect's durable bookmarks")
    parser.add_argument("--source", choices=("local", "cloud"), default="local")
    parser.add_argument("--data", default="data/xcollect.json", help="Local profile JSON file")
    parser.add_argument("--api-base", default=os.getenv("XCOLLECT_API_BASE", ""), help="HTTPS Worker base URL")
    parser.add_argument("--token", default=os.getenv("XCOLLECT_API_TOKEN", ""), help="Cloud bearer token; prefer environment")
    sub = parser.add_subparsers(dest="command", required=True)
    search = sub.add_parser("search", help="Search existing bookmarks (lexical, no AI)")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--json", action="store_true")
    read = sub.add_parser("read", help="Read the canonical bookmark by source ID")
    read.add_argument("id")
    read.add_argument("--json", action="store_true")
    export = sub.add_parser("export", help="Export search results to Markdown+JSONL bundle")
    export.add_argument("query")
    export.add_argument("--limit", type=int, default=100)
    export.add_argument("--out", required=True)
    decide = sub.add_parser("decide", help="Optional Cloudflare typed evaluation, not text generation")
    decide.add_argument("id", help="ID of an already saved bookmark; only cloud mode")
    decide.add_argument("--model", choices=("clef-flash", "clef", "jev"), default="clef-flash")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "search":
            found = get_results(args)
            if args.json:
                print(json.dumps({"total": len(found), "results": found}, ensure_ascii=False, indent=2))
            else:
                for result in found:
                    item = result["item"]
                    print(f"[{result['score']:>3}] {item.get('id')} {item.get('title') or '(untitled)'}")
                    print(f"      {item.get('url') or ''}")
                if not found:
                    print("No saved bookmarks matched.")
        elif args.command == "read":
            item = get_item(args)
            if args.json:
                print(json.dumps(item, ensure_ascii=False, indent=2))
            else:
                print(item.get("title", "") + "\n")
                print(item.get("body_raw") or item.get("snippet") or "")
                print("\nSource:", item.get("url") or "(not available)")
        elif args.command == "export":
            found = get_results(args)
            manifest = export_bundle((result["item"] for result in found), args.query, args.out)
            print(json.dumps({"directory": str(args.out), **manifest}, ensure_ascii=False, indent=2))
        elif args.command == "decide":
            if args.source != "cloud":
                raise ValueError("Cloudflare decision requires --source cloud and a configured Worker")
            response = api_request(args.api_base, args.token, "/api/v1/decide", {"id": args.id, "model": args.model})
            print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, LookupError, FileNotFoundError, RuntimeError, OSError, json.JSONDecodeError) as err:
        print(f"xcollect: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

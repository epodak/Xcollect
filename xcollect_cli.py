#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Xcollect local/cloud read-only CLI (Python 3.10+; no third-party packages)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from src.retrieval import export_bundle, search_items
from src.research import recall_bookmarks
from src.research_direct import research_direct

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_FILE = str(PROJECT_ROOT / "data" / "xcollect.json")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect must never forward the bearer secret to a different host.
        return None


def api_request(base: str, token: str, path: str, payload: dict | None = None,
                timeout: int = 20) -> dict:
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
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
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
        # 若为默认数据路径且尚未同步，优雅降级为仓库已有种子数据
        if file.resolve() == Path(DEFAULT_DATA_FILE).resolve():
            fallback = PROJECT_ROOT / "scripts" / "seed_data.json"
            if fallback.is_file():
                file = fallback
            else:
                raise FileNotFoundError(f"Bookmark file not found: {file}; synchronize Local Profile first")
        else:
            raise FileNotFoundError(f"Bookmark file not found: {file}")
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


def run_research_request(args) -> dict:
    """CLI 只负责数据源与交付；有鉴权的 Worker 执行真实判决和生成模型。"""
    provider = args.provider
    if provider == "auto":
        provider = ("worker" if args.source == "cloud" or args.token
                    else "direct" if os.getenv("CLOUDFLARE_API_TOKEN") else "worker")
    payload = {
        "query": args.query, "model": args.model, "limit": args.limit,
        "max_candidates": args.max_candidates,
    }
    if args.source == "local":
        items = read_local(args.data)
        found = recall_bookmarks(items, args.query, args.limit)
        data_path = Path(args.data).expanduser()
        demo = (data_path.resolve() == Path(DEFAULT_DATA_FILE).resolve()
                and not data_path.is_file())
        # Worker 仅处理最多 max_candidates 篇原文的有限上下文；
        # 保存一份本机权威原文映射，报告导出时换回完整 body_raw。
        selected_local = [x["item"] for x in found[:args.max_candidates]]
        originals = {str(x["id"]): x for x in selected_local}
        payload["sources"] = [
            {**{k: x.get(k) for k in (
                "id", "url", "title", "author", "created_at", "category",
                "sub_category", "username", "snippet"
            )}, "body_raw": str(x.get("body_raw") or "")[:6000]}
            for x in selected_local
        ]
        payload["profile"] = "demo_seed" if demo else "local_bookmarks"
        if provider == "direct":
            from src.config_loader import CONFIG
            account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
            if not account_id:
                # 项目已知的非敏感账户编号，仍以配置文件为真源。
                try:
                    account_id = json.loads(
                        (PROJECT_ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
                    ).get("account_id", "")
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
            return asyncio.run(research_direct(
                args.query, found, judge_model=args.model,
                generation_model=CONFIG.research_generation_model,
                max_candidates=args.max_candidates, account_id=account_id,
                cloudflare_token=os.getenv("CLOUDFLARE_API_TOKEN", ""),
                generator=args.generator,
                deepseek_key=CONFIG.custom_ai_api_key,
                deepseek_base=CONFIG.custom_ai_base,
                deepseek_model=CONFIG.custom_ai_model,
                allow_jev=args.allow_jev, profile=payload["profile"],
            ))
    elif provider == "direct":
        raise ValueError("直接 Cloudflare AI 模式目前仅支持 --source local")
    if args.generator == "deepseek":
        raise ValueError("--generator deepseek 须与 --provider direct 一起使用")
    if not args.token:
        raise ValueError(
            "研究需要模型连接：配置 XCOLLECT_API_TOKEN（Worker），或设置 "
            "CLOUDFLARE_API_TOKEN 后执行 --provider direct"
        )
    answer = api_request(args.api_base, args.token, "/api/v1/research",
                         payload, timeout=180)
    if args.source == "local":
        answer["sources"] = [
            originals.get(str(item.get("id")), item) for item in answer.get("sources", [])
        ]
    return answer


def save_research_bundle(result: dict, destination: str) -> dict:
    """研究报告与证据分层保存：报告不会覆盖或改写原文。"""
    target = Path(destination).expanduser()
    sources = result.get("sources", [])
    manifest = export_bundle(sources, result["query"], target)
    (target / "report.md").write_text(result.get("report", ""), encoding="utf-8")
    (target / "decisions.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in result.get("decisions", [])),
        encoding="utf-8",
    )
    metadata = {
        "schema": "xcollect.research.v1",
        "query": result["query"], "topic": result.get("topic"),
        "profile": result.get("profile"), "generation_model": result.get("generation_model"),
        "stats": result.get("stats"), "result": "generated" if result.get("analysis") else "no_evidence",
    }
    (target / "research.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xcollect", description="Read and export Xcollect's durable bookmarks")
    parser.add_argument("--source", choices=("local", "cloud"), default="local")
    parser.add_argument("--data", default=os.getenv("XCOLLECT_DATA", DEFAULT_DATA_FILE), help="Local profile JSON (default: <checkout>/data/xcollect.json; override with XCOLLECT_DATA)")
    parser.add_argument("--api-base", default=os.getenv("XCOLLECT_API_BASE", "https://x.daduiot.com"), help="HTTPS Worker base URL")
    parser.add_argument("--token", default=os.getenv("XCOLLECT_API_TOKEN", ""), help="Cloud bearer token; prefer environment")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="Inspect local setup without reading private tokens")
    doctor.add_argument("--json", action="store_true")
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
    for name in ("ask", "research"):
        command = sub.add_parser(name, help="自然语言检索→自动 Clef/Jev 判断→LLM 证据综述")
        command.add_argument("query", help="自然语言研究问题")
        command.add_argument("--limit", type=int, default=20, help="初始召回数量")
        command.add_argument("--max-candidates", type=int, default=8, help="最多调用判断模型的篇数")
        command.add_argument("--model", choices=("clef-flash", "clef", "jev"), default="clef-flash")
        command.add_argument("--provider", choices=("auto", "worker", "direct"), default="auto",
                             help="AI 执行位置：Worker API 或直接 Cloudflare AI")
        command.add_argument("--generator", choices=("workers", "deepseek"), default="workers",
                             help="生成模型来源；DeepSeek 仅支持 direct 模式")
        command.add_argument("--allow-jev", action="store_true",
                             help="明确允许第三方 Jev 按量计费")
        command.add_argument("--out", required=name == "research", help="将报告和完整来源导出到指定目录")
        command.add_argument("--json", action="store_true", help="打印结构化研究结果")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            path = Path(args.data).expanduser()
            diagnostics = {
                "source": args.source,
                "project_root": str(PROJECT_ROOT),
                "python": sys.executable,
                "data_path": str(path.resolve()),
                "local_data_exists": path.is_file(),
                "cloud_api_configured": bool(args.api_base and args.token),
            }
            if args.json:
                print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
            else:
                for key, value in diagnostics.items():
                    print(f"{key}: {value}")
        elif args.command == "search":
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
        elif args.command in ("ask", "research"):
            if args.limit < 1 or args.max_candidates < 1:
                raise ValueError("limit/max-candidates 必须为正整数")
            result = run_research_request(args)
            if args.out:
                save_research_bundle(result, args.out)
                print(f"研究报告已保存：{Path(args.out).expanduser() / 'report.md'}", file=sys.stderr)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                if result.get("profile") == "demo_seed":
                    print("注意：本次使用仓库演示数据，并非已同步的私人收藏。\n")
                print(result.get("report", ""))
        return 0
    except (ValueError, LookupError, FileNotFoundError, RuntimeError, OSError, json.JSONDecodeError) as err:
        print(f"xcollect: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

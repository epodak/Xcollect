# -*- coding: utf-8 -*-
"""Read-only bookmark retrieval and portable exports.

This module never returns Discovery candidates. It consumes *only* the caller's
authoritative Bookmark Plane records, both in Local JSON and Cloud D1.
No network/AI dependencies, and no writes to authoritative data.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# Deliberately conservative: no hallucinated acronym expansions.
ALIASES = {
    "opus 5.5": ("claude opus 5.5", "opus-5.5", "opus5.5"),
    "grok bot": ("grokbot", "grok-bot"),
    "jev": ("typesafe jev",),
}
MAX_QUERY_LENGTH = 200
MAX_RESULTS = 100


def normalized(text: object) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).casefold().strip()


def query_terms(query: str) -> list[str]:
    q = normalized(query)
    if not q or len(q) > MAX_QUERY_LENGTH:
        raise ValueError("Query must contain between 1 and 200 characters")
    terms = [q]
    for key, variants in ALIASES.items():
        names = (key, *variants)
        if q in names:
            terms.extend(names)
            break
    # Do not expand arbitrary acronyms; only explicit synonyms.
    return list(dict.fromkeys(normalized(t) for t in terms if t))


def _relevant_fields(item: dict) -> tuple[str, str, str]:
    return (
        normalized(item.get("title", "")),
        normalized(item.get("body_raw") or item.get("snippet") or ""),
        normalized(" ".join(str(item.get(k) or "") for k in (
            "author", "username", "category", "sub_category"
        ))),
    )


def search_items(items: Iterable[dict], query: str, limit: int = 20) -> list[dict]:
    """Stable, bounded lexical retrieval; not an embeddings/semantic engine."""
    terms = query_terms(query)
    limit = max(1, min(MAX_RESULTS, int(limit)))
    results = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        title, body, metadata = _relevant_fields(item)
        score = 0
        for term in terms:
            if term in title:
                score = max(score, 80 + min(10, title.count(term)))
            if term in body:
                score = max(score, 45 + min(10, body.count(term)))
            if term in metadata:
                score = max(score, 20 + min(10, metadata.count(term)))
        if not score:
            # Broad multi-word fallback (all tokens must occur, not just one).
            tokens = [t for t in re.split(r"\s+", terms[0]) if len(t) > 1]
            if len(tokens) > 1 and all(t in title + " " + body + " " + metadata for t in tokens):
                score = 10
        if score:
            # Do not mutate the canonical record with ranking annotations.
            results.append((score, item))
    def order(entry):
        try:
            position = int(entry[1].get("bookmark_position") or 0)
        except (ValueError, TypeError):
            position = 1_000_000
        return -entry[0], position, str(entry[1]["id"])

    results.sort(key=order)
    return [{"score": score, "item": item} for score, item in results[:limit]]


def _safe_filename(source_id: object) -> str:
    source = str(source_id or "")
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", source).strip("._")
    if not safe:
        safe = "item"
    # Hash always included so different arbitrary/untrusted IDs cannot collide.
    return safe[:55] + "-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:10]


def _frontmatter_value(value: object) -> str:
    # JSON string is valid YAML double-quoted scalar and escapes newlines/quotes.
    return json.dumps(str(value or ""), ensure_ascii=False)


def render_markdown(item: dict) -> str:
    raw = str(item.get("body_raw") or item.get("snippet") or "")
    origin = "body_raw" if item.get("body_raw") else "snippet_fallback"
    title = str(item.get("title") or "Untitled").replace("\r", " ").replace("\n", " ").strip()
    metadata = (
        "---\n"
        f"schema: xcollect.bookmark.v1\n"
        f"id: {_frontmatter_value(item.get('id'))}\n"
        f"url: {_frontmatter_value(item.get('url'))}\n"
        f"author: {_frontmatter_value(item.get('author'))}\n"
        f"created_at: {_frontmatter_value(item.get('created_at'))}\n"
        f"category: {_frontmatter_value(item.get('category'))}\n"
        f"content_origin: {origin}\n"
        "---\n\n"
    )
    return metadata + "# " + title + "\n\n" + raw + "\n"


def export_bundle(items: Iterable[dict], query: str, destination: str | Path) -> dict:
    """Write portable source records and Markdown; no media download or AI claims."""
    query_terms(query)
    dest = Path(destination).expanduser()
    if dest.exists() and dest.is_symlink():
        raise ValueError("Export destination may not be a symlink")
    dest.mkdir(parents=True, exist_ok=True)
    post_dir = dest / "posts"
    if post_dir.is_symlink():
        raise ValueError("Export posts directory may not be a symlink")
    post_dir.mkdir(exist_ok=True)
    for name in ("README.md", "manifest.json", "sources.jsonl"):
        if (dest / name).is_symlink():
            raise ValueError("Export output file may not be a symlink")
    records = [dict(item) for item in items if isinstance(item, dict) and item.get("id")]
    records = list({str(item["id"]): item for item in records}.values())
    lines = []
    links = []
    for item in records:
        name = _safe_filename(item["id"]) + ".md"
        file_path = post_dir / name
        if file_path.is_symlink():
            raise ValueError("Refusing to replace symlink in export directory")
        file_path.write_text(render_markdown(item), encoding="utf-8")
        lines.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
        title = str(item.get("title") or item["id"]).replace("[", "\\[").replace("]", "\\]").replace("\n", " ")
        links.append(f"- [{title}](posts/{name}) — {item.get('url') or 'No source URL'}")
    (dest / "sources.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    manifest = {
        "schema": "xcollect.bundle.v1",
        "query": query,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "scope": "bookmarks_only",
        "source_count": len(records),
        "content_precedence": "body_raw -> snippet",
        "ai_generated": False,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dest / "README.md").write_text(
        "# Xcollect bookmarks: " + query.replace("\n", " ") + "\n\n"
        + "This bundle contains user-saved bookmarks only. Raw content is not AI output.\n\n"
        + "\n".join(links) + "\n", encoding="utf-8")
    return manifest

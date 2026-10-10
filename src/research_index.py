# -*- coding: utf-8 -*-
"""使用 D1 FTS5 的书签召回；旧环境无迁移时回退权威库词法召回。"""
from __future__ import annotations

import re

try:
    from .research import topic_from_question
    from .retrieval import search_items
except ImportError:
    from research import topic_from_question
    from retrieval import search_items


def fts_query(topic: str) -> str:
    """只生成引号包裹的文字项，绝不执行原样传入的 FTS 操作符。"""
    tokens = re.findall(r"[A-Za-z]+|\d+|[\u4e00-\u9fff]+", topic)
    meaningful = [t for t in tokens if len(t) >= 2 and not t.isdigit()]
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in meaningful[:6])


def _get(row, name):
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


async def recall_cloud(env, question, limit, load_all):
    """优先使用 D1 持久 FTS5，索引未初始化则退回现有 Bookmark Plane。"""
    topic = topic_from_question(question)
    if hasattr(env, "DB"):
        expression = fts_query(topic)
        if expression:
            try:
                results = await env.DB.prepare(
                    "SELECT t.id,t.title,t.author,t.username,t.url,t.created_at,"
                    "t.category,t.sub_category,t.body_raw,t.snippet "
                    "FROM bookmark_fts JOIN tweets t ON t.rowid=bookmark_fts.rowid "
                    "WHERE bookmark_fts MATCH ? ORDER BY bm25(bookmark_fts) LIMIT ?"
                ).bind(expression, min(100, max(1, int(limit) * 3))).all()
                rows = [{key: _get(row, key) for key in (
                    "id", "title", "author", "username", "url", "created_at",
                    "category", "sub_category", "body_raw", "snippet",
                )} for row in results.results]
                matched = search_items(rows, topic, limit)
                if matched:
                    return matched, "d1_fts5"
            except Exception:
                # 兼容现有 D1 未应用 FTS5 迁移；对运行时 SQL 错误也降级读取。
                pass
    stored = await load_all(env)
    if not stored.get("success"):
        raise RuntimeError("权威书签库不可用")
    return search_items(stored.get("data", []), topic, limit), "bookmark_lexical_fallback"

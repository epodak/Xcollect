# -*- coding: utf-8 -*-
"""Preference aggregation for the Personal Discovery Engine.

Raw feedback remains append-only. This module derives a small, reproducible
preference field from those events and never mutates the evidence.
"""

import json
import math


def _key(value) -> str:
    return str(value or "").strip()


def _squash(value: float, scale: float) -> float:
    return math.tanh(float(value or 0.0) / max(0.001, float(scale)))


def build_preference_profile(items: list[dict], events: list[dict]) -> dict:
    """Aggregate distinct (tweet, action) evidence into topic/author preferences.

    Repeated clicks on the same action for the same tweet do not compound reward;
    this prevents accidental reopen/copy loops from dominating the profile.
    """
    item_by_id = {
        _key(item.get("id")): item
        for item in (items or [])
        if _key(item.get("id"))
    }

    distinct = {}
    for event in events or []:
        tweet_id = _key(event.get("tweet_id"))
        action = _key(event.get("action"))
        if not tweet_id or not action:
            continue
        try:
            weight = float(event.get("weight") or 0.0)
        except Exception:
            weight = 0.0

        raw_context = event.get("context") or {}
        if isinstance(raw_context, str):
            try:
                parsed_context = json.loads(raw_context)
                context = parsed_context if isinstance(parsed_context, dict) else {}
            except Exception:
                context = {}
        elif isinstance(raw_context, dict):
            context = raw_context
        else:
            context = {}

        distinct[(tweet_id, action)] = {
            "weight": weight,
            "context": context,
        }

    category_raw = {}
    subcategory_raw = {}
    author_raw = {}

    for (tweet_id, _action), evidence in distinct.items():
        weight = float(evidence.get("weight") or 0.0)
        context = evidence.get("context") or {}

        # “误抓/不该进入发现流”属于 Discovery quality feedback，而不是兴趣反馈。
        # 它可以训练 query/source/gate，但绝不能把同一 category/sub-category/author
        # 当成用户“不感兴趣”。旧事件未带 scope 时保持既有 preference 语义。
        if _key(context.get("feedback_scope")) == "discovery_quality":
            continue

        item = item_by_id.get(tweet_id) or {}

        # Context fallback preserves negative learning even after an unbookmark
        # removes the source row from the durable bookmark table.
        category = _key(item.get("category") or context.get("category"))
        subcategory = _key(item.get("sub_category") or context.get("sub_category"))
        author = _key(
            item.get("username")
            or item.get("author")
            or context.get("username")
            or context.get("author")
        ).lower()

        if category:
            category_raw[category] = category_raw.get(category, 0.0) + weight
        if category and subcategory:
            skey = category + "\x1f" + subcategory
            subcategory_raw[skey] = subcategory_raw.get(skey, 0.0) + weight
        if author:
            author_raw[author] = author_raw.get(author, 0.0) + weight

    return {
        "category": {key: _squash(value, 4.0) for key, value in category_raw.items()},
        "subcategory": {key: _squash(value, 3.0) for key, value in subcategory_raw.items()},
        "author": {key: _squash(value, 3.0) for key, value in author_raw.items()},
        "evidence_pairs": len(distinct),
    }


def preference_boost(item: dict, profile: dict) -> float:
    """Map the preference profile into a bounded relevance correction.

    Max absolute correction is intentionally small (~0.22). Semantic relevance
    and quality still dominate, so the system learns taste without collapsing
    into an echo chamber after a few clicks.
    """
    if not profile:
        return 0.0

    category = _key(item.get("category"))
    subcategory = _key(item.get("sub_category"))
    author = _key(item.get("username") or item.get("author")).lower()

    cat_signal = float((profile.get("category") or {}).get(category, 0.0) or 0.0)
    sub_signal = 0.0
    if category and subcategory:
        sub_signal = float(
            (profile.get("subcategory") or {}).get(category + "\x1f" + subcategory, 0.0)
            or 0.0
        )
    author_signal = float((profile.get("author") or {}).get(author, 0.0) or 0.0)

    boost = 0.06 * cat_signal + 0.10 * sub_signal + 0.06 * author_signal
    return max(-0.22, min(0.22, boost))


def apply_preference_profile(items: list[dict], events: list[dict]) -> tuple[list[dict], dict]:
    profile = build_preference_profile(items, events)
    enriched = []
    for item in items or []:
        row = dict(item)
        row["preference_boost"] = round(preference_boost(row, profile), 6)
        enriched.append(row)
    return enriched, profile

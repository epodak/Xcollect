# -*- coding: utf-8 -*-
"""Preference aggregation for the Personal Discovery Engine.

Human policy defines action meaning and ordering. Magnitude is calibrated from
observed behavior (primarily bookmark conversion) rather than hand-written
relative ratios. Raw evidence stays immutable during its retention window; this module
only derives bounded preference fields.
"""

import json

from config_loader import CONFIG

try:
    from learning import estimate_action_utilities, evidence_confidence
except ImportError:
    from src.learning import estimate_action_utilities, evidence_confidence


def _key(value) -> str:
    return str(value or "").strip()


def _context_dict(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _merge_context(target: dict, source: dict):
    for key, value in (source or {}).items():
        if value not in (None, "", [], {}):
            target[key] = value


def _add_signal(bucket: dict, key: str, score: float):
    if not key or score == 0:
        return
    row = bucket.setdefault(key, {"sum": 0.0, "count": 0.0})
    row["sum"] += float(score)
    row["count"] += 1.0


def _finalize_field(raw: dict, scale: float) -> dict:
    out = {}
    for key, row in raw.items():
        count = max(0.0, float(row.get("count", 0.0) or 0.0))
        if count <= 0:
            continue
        mean = float(row.get("sum", 0.0) or 0.0) / count
        confidence = evidence_confidence(count, scale)
        out[key] = max(-1.0, min(1.0, mean * confidence))
    return out


def build_preference_profile(
    items: list[dict],
    events: list[dict],
    action_stats: dict | None = None,
) -> dict:
    """Build category/sub-category/author preference fields.

    Evidence is resolved per tweet, not summed per click. This prevents a normal
    funnel (detail -> original -> bookmark) from counting as three independent
    votes. The strongest surviving semantic action becomes the item-level vote.

    Rules:
    - bookmark is the terminal positive anchor (+1 normalized);
    - open_detail/copy/open_original magnitudes are learned from conversion;
    - unbookmark cancels the bookmark vote rather than becoming dislike;
    - not_interested is terminal semantic negative (-1 normalized);
    - hide_author is author-only negative;
    - reject_candidate / discovery_quality never enter semantic preference.
    """
    item_by_id = {
        _key(item.get("id")): item
        for item in (items or [])
        if _key(item.get("id"))
    }

    grouped = {}
    distinct_pairs = set()
    for event in events or []:
        tweet_id = _key(event.get("tweet_id"))
        action = _key(event.get("action"))
        if not tweet_id or not action:
            continue

        distinct_pairs.add((tweet_id, action))
        bucket = grouped.setdefault(tweet_id, {
            "actions": set(),
            "context": {},
        })
        bucket["actions"].add(action)
        _merge_context(bucket["context"], _context_dict(event.get("context")))

    utilities = estimate_action_utilities(action_stats or {})
    positive_actions = tuple(CONFIG.learning_positive_action_order)

    category_raw = {}
    subcategory_raw = {}
    author_raw = {}
    semantic_items = 0

    for tweet_id, evidence in grouped.items():
        actions = set(evidence.get("actions") or set())
        context = evidence.get("context") or {}

        # False-positive rejection belongs to Discovery Quality only.
        if (
            "reject_candidate" in actions
            or _key(context.get("feedback_scope")) == "discovery_quality"
        ):
            # A tweet could theoretically also carry a positive action before
            # being marked false-positive; reject semantics wins for topic taste.
            continue

        item = item_by_id.get(tweet_id) or {}
        category = _key(item.get("category") or context.get("category"))
        subcategory = _key(item.get("sub_category") or context.get("sub_category"))
        author = _key(
            item.get("username")
            or item.get("author")
            or context.get("username")
            or context.get("author")
        ).lower()

        semantic_score = 0.0

        if "not_interested" in actions:
            semantic_score = -1.0
        else:
            candidates = []
            for action in positive_actions:
                if action not in actions:
                    continue
                # An explicit unbookmark withdraws the bookmark vote. Earlier
                # weaker engagement may still remain valid evidence.
                if action == "bookmark" and "unbookmark" in actions:
                    continue
                candidates.append(float(utilities.get(action, 0.0) or 0.0))
            if candidates:
                semantic_score = max(candidates)

        if semantic_score != 0:
            semantic_items += 1
            _add_signal(category_raw, category, semantic_score)
            if category and subcategory:
                _add_signal(
                    subcategory_raw,
                    category + "\x1f" + subcategory,
                    semantic_score,
                )

        # hide_author is explicit author rejection and does not contaminate the
        # topic fields. Otherwise author receives the same item-level evidence.
        if "hide_author" in actions:
            _add_signal(author_raw, author, -1.0)
        elif semantic_score != 0:
            _add_signal(author_raw, author, semantic_score)

    return {
        "category": _finalize_field(
            category_raw,
            CONFIG.learning_category_evidence_scale,
        ),
        "subcategory": _finalize_field(
            subcategory_raw,
            CONFIG.learning_subcategory_evidence_scale,
        ),
        "author": _finalize_field(
            author_raw,
            CONFIG.learning_author_evidence_scale,
        ),
        "evidence_pairs": len(distinct_pairs),
        "semantic_items": semantic_items,
        "action_utilities": utilities,
    }


def preference_boost(item: dict, profile: dict) -> float:
    """Map bounded preference fields into a small relevance correction."""
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


def apply_preference_profile(
    items: list[dict],
    events: list[dict],
    action_stats: dict | None = None,
) -> tuple[list[dict], dict]:
    profile = build_preference_profile(items, events, action_stats=action_stats)
    enriched = []
    for item in items or []:
        row = dict(item)
        row["preference_boost"] = round(preference_boost(row, profile), 6)
        enriched.append(row)
    return enriched, profile

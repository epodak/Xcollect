#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic acceptance checks for the Discovery Plane."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import CONFIG
from src.discovery import (
    cheap_gate_candidate,
    diversity_select,
    build_discovery_quality_profile,
    _within_retention,
    _parse_judge_array,
    _post_judge_rejection_reason,
)
from src.preferences import apply_preference_profile
from src.learning import estimate_action_utilities
from src.twitter import normalize_tweet_result


def _candidate(idx, **overrides):
    row = {
        "id": str(idx),
        "username": "author_" + str(idx),
        "author": "Author " + str(idx),
        "category": "01_人工智能与Agent",
        "sub_category": "Coding Agent/智能编程",
        "title": "Useful engineering finding",
        "body_raw": "A concrete technical explanation with measurements and implementation details. " * 4,
        "likes": 100 + idx,
        "retweets": 10,
        "views": 10000,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "related_hot_score": 1.0 - idx * 0.001,
    }
    row.update(overrides)
    return row


def main():
    assert CONFIG.discovery_enabled is True
    assert CONFIG.discovery_retention_hours == 24.0
    assert CONFIG.feedback_weights["impression"] == 0.0
    assert CONFIG.feedback_weights["open_detail"] == 1.0
    assert CONFIG.feedback_weights["open_original"] == 1.0
    assert CONFIG.feedback_weights["bookmark"] == 1.0
    assert CONFIG.feedback_weights["reject_candidate"] == -1.0
    assert CONFIG.feedback_weights["not_interested"] == -1.0
    assert 0.0 < CONFIG.learning_exploration_ratio <= 0.25
    assert CONFIG.query_id_search
    assert isinstance(CONFIG.discovery_queries, list) and CONFIG.discovery_queries

    short = _candidate(1, body_raw="tiny")
    ok, reason, _ = cheap_gate_candidate(short)
    assert not ok and reason == "too_short"

    sensitive = _candidate(2, possibly_sensitive=True)
    ok, reason, _ = cheap_gate_candidate(sensitive)
    assert not ok and reason == "possibly_sensitive"

    promo = _candidate(
        3,
        body_raw=("BUY NOW limited offer promo code affiliate shop now discount code " * 12),
    )
    ok, reason, penalty = cheap_gate_candidate(promo)
    assert not ok and reason == "spam_promo_penalty"
    assert penalty >= CONFIG.discovery_cheap_penalty_threshold

    clean = _candidate(4)
    ok, reason, penalty = cheap_gate_candidate(clean)
    assert ok and reason == ""
    assert penalty < CONFIG.discovery_cheap_penalty_threshold

    now = datetime.now(timezone.utc)
    expired = _candidate(5, created_at=(now - timedelta(hours=24, seconds=1)).isoformat())
    ok, reason, _ = cheap_gate_candidate(expired)
    assert not ok and reason == "expired_source"
    assert not _within_retention(expired["created_at"], now=now)

    fresh = _candidate(6, created_at=(now - timedelta(hours=23, minutes=59)).isoformat())
    ok, reason, _ = cheap_gate_candidate(fresh)
    assert ok and reason == ""
    assert _within_retention(fresh["created_at"], now=now)

    unknown_time = _candidate(7, created_at="")
    ok, reason, _ = cheap_gate_candidate(unknown_time)
    assert not ok and reason == "unknown_source_time"

    # Author cap: even a dominant author cannot fill the daily attention budget.
    rows = []
    for i in range(12):
        rows.append(_candidate(i, username="same_author", related_hot_score=1.0 - i * 0.01))
    for i in range(12, 30):
        rows.append(_candidate(i, username="author_" + str(i), related_hot_score=0.8 - i * 0.001))
    selected = diversity_select(rows, limit=20)
    same_author_count = sum(1 for item in selected if item["username"] == "same_author")
    assert same_author_count <= CONFIG.discovery_author_daily_cap

    risky = _candidate(
        99,
        relevance_score=0.9,
        quality_score=0.8,
        related_hot_score=0.8,
        related_hot_features={"relevance": 0.9, "quality": 0.8},
        promo_probability=0.95,
    )
    assert _post_judge_rejection_reason(risky) == "ai_risk"

    weak = _candidate(
        100,
        relevance_score=0.2,
        quality_score=0.8,
        related_hot_score=0.7,
        related_hot_features={"relevance": 0.2, "quality": 0.8},
    )
    assert _post_judge_rejection_reason(weak) == "low_relevance"

    parsed = _parse_judge_array(
        '[{"id":"1","relevance":0.9,"quality":0.8,"novelty":0.7,'
        '"source":0.8,"promo":0.0,"nsfw":0.0,"spam":0.0,"reason":"high signal"}]'
    )
    assert len(parsed) == 1 and parsed[0]["id"] == "1"

    fixture = {
        "rest_id": "1234567890",
        "legacy": {
            "full_text": "A useful long enough discovery candidate about systems architecture.",
            "favorite_count": 123,
            "retweet_count": 14,
            "created_at": "2026-10-04T12:00:00+00:00",
            "lang": "en",
        },
        "core": {
            "user_results": {
                "result": {
                    "core": {
                        "name": "Example Author",
                        "screen_name": "example_author",
                    },
                    "legacy": {
                        "profile_image_url_https": "https://pbs.twimg.com/profile_images/a_normal.jpg"
                    },
                }
            }
        },
        "views": {"count": "4567"},
    }
    normalized = normalize_tweet_result(
        fixture,
        category_hint="02_技术架构与开发",
        sub_category_hint="高性能与系统架构",
    )
    assert normalized["id"] == "1234567890"
    assert normalized["username"] == "example_author"
    assert normalized["likes"] == 123
    assert normalized["views"] == 4567
    assert normalized["category"] == "02_技术架构与开发"
    assert normalized["is_reply"] is False

    reply_fixture = dict(fixture)
    reply_fixture["rest_id"] = "1234567891"
    reply_fixture["legacy"] = dict(fixture["legacy"])
    reply_fixture["legacy"]["in_reply_to_status_id_str"] = "999"
    reply_fixture["legacy"]["in_reply_to_screen_name"] = "dhh"
    reply = normalize_tweet_result(
        reply_fixture,
        category_hint="02_技术架构与开发",
        sub_category_hint="数据库与存储架构",
    )
    assert reply["is_reply"] is True
    assert reply["reply_to_username"] == "dhh"
    ok, reason, _ = cheap_gate_candidate(reply)
    assert not ok and reason == "reply"

    # False-positive feedback must not become topic dislike.
    quality_event = {
        "tweet_id": "q1",
        "action": "reject_candidate",
        "weight": -1.0,
        "context": {
            "feedback_scope": "discovery_quality",
            "discovery_query": "sqlite benchmark",
            "category": "02_技术架构与开发",
            "sub_category": "数据库与存储架构",
            "username": "good_author",
        },
    }
    preferred, profile = apply_preference_profile(
        [_candidate(101, id="q1", category="02_技术架构与开发", sub_category="数据库与存储架构", username="good_author")],
        [quality_event],
    )
    assert preferred[0]["preference_boost"] == 0
    assert not profile["category"]
    assert not profile["subcategory"]
    assert not profile["author"]

    quality_only = build_discovery_quality_profile([quality_event])
    assert quality_only["sqlite benchmark"] > 0
    quality_with_accept = build_discovery_quality_profile([
        quality_event,
        {
            "tweet_id": "q2",
            "action": "open_original",
            "weight": 1.0,
            "context": {"discovery_query": "sqlite benchmark"},
        },
    ])
    assert 0 <= quality_with_accept.get("sqlite benchmark", 0) < quality_only["sqlite benchmark"]

    action_stats = {
        "impression": {"exposures": 100, "conversions": 5},
        "open_detail": {"exposures": 80, "conversions": 8},
        "copy": {"exposures": 50, "conversions": 10},
        "open_original": {"exposures": 30, "conversions": 12},
    }
    learned = estimate_action_utilities(action_stats)
    assert 0 <= learned["open_detail"] <= learned["copy"] <= learned["open_original"] < learned["bookmark"] == 1.0

    bootstrap = estimate_action_utilities({})
    assert bootstrap["open_detail"] < bootstrap["copy"] < bootstrap["open_original"] < bootstrap["bookmark"]

    semantic_items = [
        _candidate(201, id="detail", username="same", category="cat", sub_category="sub"),
        _candidate(202, id="original", username="same2", category="cat2", sub_category="sub2"),
        _candidate(203, id="saved", username="same3", category="cat3", sub_category="sub3"),
        _candidate(204, id="dislike", username="same4", category="cat4", sub_category="sub4"),
    ]
    semantic_events = [
        {"tweet_id": "detail", "action": "open_detail", "weight": 1.0},
        {"tweet_id": "original", "action": "open_detail", "weight": 1.0},
        {"tweet_id": "original", "action": "open_original", "weight": 1.0},
        {"tweet_id": "saved", "action": "open_detail", "weight": 1.0},
        {"tweet_id": "saved", "action": "open_original", "weight": 1.0},
        {"tweet_id": "saved", "action": "bookmark", "weight": 1.0},
        {"tweet_id": "dislike", "action": "not_interested", "weight": -1.0},
    ]
    _, semantic_profile = apply_preference_profile(
        semantic_items,
        semantic_events,
        action_stats=action_stats,
    )
    assert 0 < semantic_profile["category"]["cat"] < semantic_profile["category"]["cat2"] < semantic_profile["category"]["cat3"]
    assert semantic_profile["category"]["cat4"] < 0

    print("discovery acceptance checks: OK")


if __name__ == "__main__":
    main()

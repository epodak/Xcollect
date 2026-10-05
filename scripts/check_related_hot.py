#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic acceptance checks for related-hot ranking."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import CONFIG
from src.ranking import compute_related_hot_score
from src.preferences import apply_preference_profile


def _tweet(**overrides):
    base = {
        "id": "t",
        "title": "A substantive engineering note",
        "body_raw": "Detailed technical explanation " * 30,
        "category": "02_技术架构与开发",
        "sub_category": "全栈工程与系统设计",
        "classify_status": "settled",
        "likes": 300,
        "retweets": 40,
        "views": 18000,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


def main():
    weights = [
        CONFIG.rank_relevance_weight,
        CONFIG.rank_quality_weight,
        CONFIG.rank_novelty_weight,
        CONFIG.rank_velocity_weight,
        CONFIG.rank_source_weight,
        CONFIG.rank_freshness_weight,
    ]
    assert abs(sum(weights) - 1.0) < 1e-9, f"positive ranking weights must sum to 1.0: {sum(weights)}"

    now = datetime.now(timezone.utc)
    recent = _tweet(created_at=(now - timedelta(hours=2)).isoformat())
    old = _tweet(created_at=(now - timedelta(days=14)).isoformat())
    recent_score, recent_features = compute_related_hot_score(recent, now=now)
    old_score, old_features = compute_related_hot_score(old, now=now)
    assert recent_score > old_score, (recent_score, old_score)
    assert recent_features["freshness"] > old_features["freshness"]

    clean = _tweet(body_raw="A careful benchmark with methodology, measurements, caveats and source code. " * 12)
    promo = _tweet(body_raw="BUY NOW limited offer promo code affiliate shop now discount code " * 10)
    clean_score, clean_features = compute_related_hot_score(clean, now=now)
    promo_score, promo_features = compute_related_hot_score(promo, now=now)
    assert promo_features["penalty"] > clean_features["penalty"]
    assert clean_score > promo_score

    enriched = _tweet(
        relevance_score=0.99,
        quality_score=0.95,
        novelty_score=0.92,
        source_score=0.90,
    )
    enriched_score, features = compute_related_hot_score(enriched, now=now)
    assert features["relevance"] == 0.99
    assert features["quality"] == 0.95
    assert 0.0 <= enriched_score <= 1.0

    preference_items = [
        _tweet(id="a", category="01_人工智能与Agent", sub_category="Coding Agent/智能编程", username="author_a"),
        _tweet(id="b", category="01_人工智能与Agent", sub_category="Coding Agent/智能编程", username="author_b"),
        _tweet(id="c", category="04_产品设计与思考", sub_category="产品交互与体验设计", username="author_c"),
        _tweet(id="d", category="05_前沿资讯与研读", sub_category="行业前沿与长文洞察", username="author_d"),
    ]
    feedback = [
        {"tweet_id": "a", "action": "copy", "weight": 1.0},
        {"tweet_id": "a", "action": "copy", "weight": 1.0},  # duplicate action must not compound
        {"tweet_id": "a", "action": "open_detail", "weight": 1.0},
        {"tweet_id": "c", "action": "not_interested", "weight": -1.0},
        {
            "tweet_id": "removed",
            "action": "not_interested",
            "weight": -1.0,
            "context": {
                "category": "05_前沿资讯与研读",
                "sub_category": "行业前沿与长文洞察",
                "username": "removed_author",
            },
        },
    ]
    preferred, profile = apply_preference_profile(preference_items, feedback)
    by_id = {item["id"]: item for item in preferred}
    assert profile["evidence_pairs"] == 4
    assert by_id["b"]["preference_boost"] > 0
    assert by_id["c"]["preference_boost"] < 0
    assert by_id["d"]["preference_boost"] < 0

    assert CONFIG.feedback_weights["bookmark"] > 0
    assert CONFIG.feedback_weights["copy"] > 0
    assert CONFIG.feedback_weights["unbookmark"] < 0
    assert CONFIG.feedback_weights["not_interested"] < 0

    # Unbookmark withdraws the bookmark vote; it is not semantic dislike.
    neutral_items = [_tweet(id="u", category="X", sub_category="Y", username="u")]
    neutral_events = [
        {"tweet_id": "u", "action": "bookmark", "weight": 1.0},
        {"tweet_id": "u", "action": "unbookmark", "weight": -1.0},
    ]
    neutral, _ = apply_preference_profile(neutral_items, neutral_events)
    assert neutral[0]["preference_boost"] == 0

    print("related-hot acceptance checks: OK")


if __name__ == "__main__":
    main()

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

    assert CONFIG.feedback_weights["bookmark"] > 0
    assert CONFIG.feedback_weights["copy"] > 0
    assert CONFIG.feedback_weights["unbookmark"] < 0
    assert CONFIG.feedback_weights["not_interested"] < 0

    print("related-hot acceptance checks: OK")


if __name__ == "__main__":
    main()

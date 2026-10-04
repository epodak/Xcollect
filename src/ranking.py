# -*- coding: utf-8 -*-
"""Related-hot ranking primitives.

This module is deliberately source-agnostic:
- existing X bookmarks can be ranked immediately using deterministic proxies;
- future discovery candidates can provide AI-produced semantic features;
- the frontend only projects the score and never owns recommendation logic.

All feature scores are normalized to [0, 1]. Penalties are also normalized and
subtracted from the weighted positive score.
"""

from datetime import datetime, timezone
import math
import re

from config_loader import CONFIG


RELATED_HOT_VERSION = CONFIG.related_hot_version

_PROMO_TERMS = (
    "sponsored", "ad:", "advertisement", "affiliate", "promo code", "discount code",
    "use my code", "limited offer", "buy now", "shop now", "sale ends",
    "抽奖", "优惠码", "返利", "带货", "推广", "恰饭", "商务合作",
)

_LOW_SIGNAL_TERMS = (
    "gm", "good morning", "follow back", "f4f", "互关", "求关注",
)

_NSFW_TERMS = (
    "onlyfans", "fansly", "nsfw", "18+", "成人视频", "成人视频", "裸照",
)

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _clamp01(value) -> float:
    try:
        value = float(value)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, value))


def _parse_datetime(value):
    if not value:
        return None
    raw = str(value).strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        # X legacy timestamps may use RFC-like strings. Avoid adding a parser
        # dependency here; unknown timestamps simply receive neutral freshness.
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_hours(created_at, now=None) -> float:
    dt = _parse_datetime(created_at)
    if dt is None:
        return 72.0
    now = now or datetime.now(timezone.utc)
    delta = now - dt
    return max(0.0, delta.total_seconds() / 3600.0)


def _bounded_positive(value: float, scale: float) -> float:
    value = max(0.0, float(value or 0.0))
    scale = max(1e-9, float(scale))
    return 1.0 - math.exp(-value / scale)


def _text_for_item(item: dict) -> str:
    return str(
        item.get("body_raw")
        or item.get("snippet")
        or item.get("title")
        or ""
    ).strip()


def _available_score(item: dict, *keys):
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            try:
                return _clamp01(value)
            except Exception:
                continue
    return None


def estimate_spam_penalty(item: dict) -> float:
    """Cheap deterministic gate signal used before expensive AI ranking.

    This is intentionally conservative: it lowers ranking but does not delete
    content. Discovery ingestion can later apply a hard rejection threshold.
    """
    text = _text_for_item(item).lower()
    if not text:
        return 0.22

    promo_hits = sum(1 for term in _PROMO_TERMS if term in text)
    nsfw_hits = sum(1 for term in _NSFW_TERMS if term in text)
    low_signal_hits = sum(1 for term in _LOW_SIGNAL_TERMS if term in text)

    url_count = len(_URL_RE.findall(text))
    text_without_urls = _URL_RE.sub("", text).strip()
    url_heavy = url_count >= 2 and len(text_without_urls) < 90

    penalty = 0.0
    penalty += min(0.46, promo_hits * 0.16)
    penalty += min(0.70, nsfw_hits * 0.35)
    penalty += min(0.22, low_signal_hits * 0.08)
    if url_heavy:
        penalty += 0.14

    # If future AI enrichment already produced explicit probabilities, merge
    # them here rather than creating a second ranking path.
    promo_ai = _available_score(item, "promo_probability", "promo_score")
    nsfw_ai = _available_score(item, "nsfw_probability", "nsfw_score")
    spam_ai = _available_score(item, "spam_probability", "spam_score")
    if promo_ai is not None:
        penalty = max(penalty, promo_ai * 0.55)
    if nsfw_ai is not None:
        penalty = max(penalty, nsfw_ai * 0.80)
    if spam_ai is not None:
        penalty = max(penalty, spam_ai * 0.65)

    return _clamp01(penalty)


def compute_related_hot_features(item: dict, now=None) -> dict:
    """Compute a stable feature vector for related-hot ranking.

    Future discovery candidates may populate semantic fields directly:
    relevance_score, quality_score, novelty_score and source_score.
    Existing bookmarks fall back to deterministic proxies so the UI contract can
    be introduced before the discovery pipeline exists.
    """
    now = now or datetime.now(timezone.utc)
    age_hours = _age_hours(item.get("created_at"), now)

    likes = max(0, int(item.get("likes") or 0))
    retweets = max(0, int(item.get("retweets") or 0))
    views = max(0, int(item.get("views") or 0))

    # Velocity rewards current momentum rather than lifetime popularity.
    engagement = likes + (retweets * 2.2) + (views * 0.012)
    velocity_raw = engagement / ((age_hours + 2.0) ** CONFIG.rank_velocity_age_exponent)
    engagement_velocity = _bounded_positive(velocity_raw, CONFIG.rank_velocity_scale)

    # Configurable half-life. Old evergreen items can still rank through quality
    # and relevance, but they no longer dominate "hot" solely from historical likes.
    freshness = 0.5 ** (age_hours / max(1.0, CONFIG.rank_freshness_half_life_hours))

    text = _text_for_item(item)
    text_len = len(text)
    quality_proxy = 0.28 + 0.64 * _bounded_positive(text_len, 700.0)

    if views > 0:
        # Engagement-rate proxy is only a small correction; views can be noisy.
        reaction_rate = (likes + retweets * 1.6) / max(1.0, float(views))
        quality_proxy += min(0.08, reaction_rate * 5.0)

    has_taxonomy = bool(item.get("category")) and item.get("category") not in (
        "未分类", "00_云端实时书签"
    )
    relevance_proxy = 0.80 if has_taxonomy else 0.60
    if str(item.get("classify_status") or "") == "settled":
        relevance_proxy += 0.05

    relevance = _available_score(item, "relevance_score", "topic_score")
    quality = _available_score(item, "quality_score")
    novelty = _available_score(item, "novelty_score")
    source = _available_score(item, "source_score", "source_trust_score")

    if relevance is None:
        relevance = _clamp01(relevance_proxy)

    try:
        preference_boost = float(item.get("preference_boost") or 0.0)
    except Exception:
        preference_boost = 0.0
    preference_boost = max(-0.22, min(0.22, preference_boost))
    relevance = _clamp01(relevance + preference_boost)

    if quality is None:
        quality = _clamp01(quality_proxy)
    if novelty is None:
        novelty = 0.62
    if source is None:
        source = 0.60

    penalty = estimate_spam_penalty(item)

    return {
        "relevance": round(relevance, 6),
        "preference_boost": round(preference_boost, 6),
        "quality": round(quality, 6),
        "novelty": round(novelty, 6),
        "engagement_velocity": round(_clamp01(engagement_velocity), 6),
        "source": round(source, 6),
        "freshness": round(_clamp01(freshness), 6),
        "penalty": round(penalty, 6),
        "age_hours": round(age_hours, 3),
    }


def compute_related_hot_score(item: dict, now=None) -> tuple[float, dict]:
    features = compute_related_hot_features(item, now=now)

    positive = (
        CONFIG.rank_relevance_weight * features["relevance"]
        + CONFIG.rank_quality_weight * features["quality"]
        + CONFIG.rank_novelty_weight * features["novelty"]
        + CONFIG.rank_velocity_weight * features["engagement_velocity"]
        + CONFIG.rank_source_weight * features["source"]
        + CONFIG.rank_freshness_weight * features["freshness"]
    )
    score = _clamp01(positive - features["penalty"])
    return round(score, 6), features


def enrich_related_hot(item: dict, now=None) -> dict:
    """Return a shallow copy enriched with the ranking contract."""
    out = dict(item)
    score, features = compute_related_hot_score(out, now=now)
    out["related_hot_score"] = score
    out["related_hot_version"] = RELATED_HOT_VERSION
    out["related_hot_features"] = features
    return out


def enrich_related_hot_many(items: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [enrich_related_hot(item, now=now) for item in (items or [])]

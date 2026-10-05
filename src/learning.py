# -*- coding: utf-8 -*-
"""Online calibration primitives for Xcollect behavioral learning.

Human/product policy defines only:
- semantic meaning of each action,
- sign / terminal meaning,
- ordinal ordering of positive actions.

Magnitude is learned from the user's own behavior. Raw Discovery events may
expire, while these aggregate sufficient statistics remain as decayed model
state and contain no tweet IDs or raw content.
"""

from datetime import datetime, timezone
import math

from config_loader import CONFIG


POSITIVE_ACTION_ORDER = ("open_detail", "copy", "open_original", "bookmark")
CALIBRATED_PRECURSOR_ACTIONS = ("impression", "open_detail", "copy", "open_original")
SEMANTIC_NEGATIVE_ACTIONS = ("not_interested",)
AUTHOR_NEGATIVE_ACTIONS = ("hide_author",)


def _row_get(row, key: str, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        value = getattr(row, key)
        return default if value is None else value
    except Exception:
        pass
    try:
        value = row[key]
        return default if value is None else value
    except Exception:
        return default


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _decay_factor(updated_at, now=None) -> float:
    now = now or datetime.now(timezone.utc)
    dt = _parse_dt(updated_at)
    if dt is None:
        return 1.0
    half_life_days = max(1.0, float(CONFIG.learning_calibration_half_life_days))
    age_days = max(0.0, (now - dt).total_seconds() / 86400.0)
    return 0.5 ** (age_days / half_life_days)


async def ensure_learning_schema(env):
    if not hasattr(env, "DB"):
        return
    await env.DB.prepare(
        "CREATE TABLE IF NOT EXISTS learning_action_stats ("
        "action TEXT PRIMARY KEY, exposures REAL NOT NULL DEFAULT 0, "
        "conversions REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)"
    ).run()


async def _increment_stat(env, action: str, exposure_delta=0.0, conversion_delta=0.0):
    if not hasattr(env, "DB"):
        return
    await ensure_learning_schema(env)
    now = datetime.now(timezone.utc)
    res = await env.DB.prepare(
        "SELECT exposures, conversions, updated_at FROM learning_action_stats WHERE action = ?"
    ).bind(str(action)).all()

    exposures = 0.0
    conversions = 0.0
    if res.results:
        row = res.results[0]
        factor = _decay_factor(_row_get(row, "updated_at", ""), now=now)
        exposures = float(_row_get(row, "exposures", 0.0) or 0.0) * factor
        conversions = float(_row_get(row, "conversions", 0.0) or 0.0) * factor

    exposures += float(exposure_delta or 0.0)
    conversions += float(conversion_delta or 0.0)
    conversions = min(conversions, exposures) if exposures > 0 else 0.0

    await env.DB.prepare(
        "INSERT INTO learning_action_stats (action, exposures, conversions, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(action) DO UPDATE SET "
        "exposures = excluded.exposures, conversions = excluded.conversions, "
        "updated_at = excluded.updated_at"
    ).bind(
        str(action),
        exposures,
        conversions,
        now.isoformat(),
    ).run()


async def update_action_calibration(env, tweet_id: str, action: str, first_action: bool):
    """Update aggregate conversion statistics without retaining item identity.

    Opportunity is counted once per (tweet, action), enforced by the caller via
    feedback_events lookup. A first bookmark converts any previously observed
    precursor actions on that tweet.
    """
    if not hasattr(env, "DB") or not first_action:
        return

    action = str(action or "")
    tweet_id = str(tweet_id or "")

    if action in CALIBRATED_PRECURSOR_ACTIONS:
        await _increment_stat(env, action, exposure_delta=1.0)

    if action != "bookmark":
        return

    try:
        res = await env.DB.prepare(
            "SELECT DISTINCT action FROM feedback_events "
            "WHERE tweet_id = ? AND action IN ('impression','open_detail','copy','open_original')"
        ).bind(tweet_id).all()
        seen = {
            str(_row_get(row, "action", "") or "")
            for row in res.results
            if _row_get(row, "action", "")
        }
    except Exception:
        seen = set()

    for precursor in CALIBRATED_PRECURSOR_ACTIONS:
        if precursor in seen:
            await _increment_stat(env, precursor, conversion_delta=1.0)


async def load_action_learning_stats(env) -> dict:
    if not hasattr(env, "DB"):
        return {}
    await ensure_learning_schema(env)
    try:
        res = await env.DB.prepare(
            "SELECT action, exposures, conversions, updated_at FROM learning_action_stats"
        ).all()
    except Exception:
        return {}

    now = datetime.now(timezone.utc)
    out = {}
    for row in res.results:
        action = str(_row_get(row, "action", "") or "")
        if not action:
            continue
        factor = _decay_factor(_row_get(row, "updated_at", ""), now=now)
        out[action] = {
            "exposures": float(_row_get(row, "exposures", 0.0) or 0.0) * factor,
            "conversions": float(_row_get(row, "conversions", 0.0) or 0.0) * factor,
        }
    return out


def _posterior_rate(stats: dict, action: str) -> tuple[float, float]:
    row = (stats or {}).get(action) or {}
    trials = max(0.0, float(row.get("exposures", 0.0) or 0.0))
    successes = max(0.0, min(trials, float(row.get("conversions", 0.0) or 0.0)))
    alpha = max(0.001, float(CONFIG.learning_conversion_prior_success))
    beta = max(0.001, float(CONFIG.learning_conversion_prior_failure))
    return (successes + alpha) / (trials + alpha + beta), trials


def _isotonic_non_decreasing(values: list[float], weights: list[float]) -> list[float]:
    """Small pooled-adjacent-violators implementation."""
    blocks = []
    for idx, value in enumerate(values):
        blocks.append({
            "start": idx,
            "end": idx,
            "weight": max(1e-9, float(weights[idx])),
            "mean": float(value),
        })
        while len(blocks) >= 2 and blocks[-2]["mean"] > blocks[-1]["mean"]:
            b = blocks.pop()
            a = blocks.pop()
            weight = a["weight"] + b["weight"]
            mean = (a["mean"] * a["weight"] + b["mean"] * b["weight"]) / weight
            blocks.append({
                "start": a["start"],
                "end": b["end"],
                "weight": weight,
                "mean": mean,
            })
    out = [0.0] * len(values)
    for block in blocks:
        for idx in range(block["start"], block["end"] + 1):
            out[idx] = block["mean"]
    return out


def estimate_action_utilities(stats: dict | None = None) -> dict:
    """Estimate bounded semantic utilities from bookmark conversion.

    The bootstrap prior uses only ordinal position (equal spacing), not the
    previous hand-written +1/+10/+50 ratios. As samples accumulate, empirical
    bookmark-conversion lift takes over. Monotonic projection preserves the
    product invariant open_detail <= copy <= open_original <= bookmark.
    """
    stats = stats or {}
    baseline_rate, baseline_n = _posterior_rate(stats, "impression")

    nonterminal = list(POSITIVE_ACTION_ORDER[:-1])
    raw = []
    weights = []
    min_samples = max(1.0, float(CONFIG.learning_min_calibration_samples))

    for idx, action in enumerate(nonterminal):
        rate, n = _posterior_rate(stats, action)

        # Convert empirical bookmark probability into normalized lift above the
        # impression baseline. 0 means no evidence beyond exposure; 1 is the
        # terminal bookmark anchor.
        empirical = max(
            0.0,
            min(0.95, (rate - baseline_rate) / max(1e-6, 1.0 - baseline_rate)),
        )

        # Bootstrap only from ordinal rank; confidence smoothly hands control
        # to observed behavior instead of freezing arbitrary ratios.
        ordinal_prior = (idx + 1) / float(len(nonterminal) + 1)
        confidence = n / (n + min_samples)
        blended = (1.0 - confidence) * ordinal_prior + confidence * empirical
        raw.append(blended)
        weights.append(max(1.0, n))

    monotonic = _isotonic_non_decreasing(raw, weights)
    utilities = {"impression": 0.0}
    for action, value in zip(nonterminal, monotonic):
        utilities[action] = round(max(0.0, min(0.95, value)), 6)
    utilities["bookmark"] = 1.0
    utilities["_baseline_bookmark_rate"] = round(baseline_rate, 6)
    utilities["_baseline_samples"] = round(baseline_n, 3)
    return utilities


def evidence_confidence(count: float, half_saturation: float) -> float:
    count = max(0.0, float(count or 0.0))
    half_saturation = max(0.001, float(half_saturation))
    return 1.0 - math.exp(-count / half_saturation)

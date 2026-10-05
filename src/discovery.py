# -*- coding: utf-8 -*-
"""Personal Discovery Engine orchestration.

Separate from bookmark synchronization:
query rotation -> X SearchTimeline -> cheap gate -> AI judge -> ranking ->
diversity-constrained daily feed.
"""

import json
import math
from datetime import datetime, timezone, timedelta

from config_loader import CONFIG

try:
    from ranking import compute_related_hot_score, estimate_spam_penalty
    from preferences import apply_preference_profile
    from twitter import fetch_search_timeline
except ImportError:
    # Local package-style imports used by acceptance tests.
    from src.ranking import compute_related_hot_score, estimate_spam_penalty
    from src.preferences import apply_preference_profile
    from src.twitter import fetch_search_timeline

try:
    from js import JSON as JsJSON
except ImportError:
    JsJSON = None


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


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_obj(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


async def ensure_discovery_schema(env):
    if not hasattr(env, "DB"):
        raise RuntimeError("Discovery Plane 当前要求 Cloudflare D1 绑定")

    statements = [
        (
            "CREATE TABLE IF NOT EXISTS discovery_candidates ("
            "tweet_id TEXT PRIMARY KEY, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, "
            "discovery_date TEXT NOT NULL, discovery_source TEXT, discovery_query TEXT, "
            "author TEXT, username TEXT, url TEXT, created_at TEXT, category TEXT, sub_category TEXT, "
            "title TEXT, snippet TEXT, body_raw TEXT, likes INTEGER DEFAULT 0, retweets INTEGER DEFAULT 0, "
            "views INTEGER DEFAULT 0, relevance_score REAL, quality_score REAL, novelty_score REAL, "
            "engagement_velocity REAL, source_score REAL, freshness_score REAL, penalty_score REAL, "
            "final_score REAL, ai_reason TEXT, ai_model TEXT, rank_version TEXT, "
            "state TEXT DEFAULT 'candidate', payload_json TEXT)"
        ),
        (
            "CREATE TABLE IF NOT EXISTS daily_feed ("
            "feed_date TEXT NOT NULL, tweet_id TEXT NOT NULL, rank INTEGER NOT NULL, "
            "final_score REAL NOT NULL, category TEXT, sub_category TEXT, selected_at TEXT NOT NULL, "
            "PRIMARY KEY (feed_date, tweet_id))"
        ),
        (
            "CREATE TABLE IF NOT EXISTS meta_kv ("
            "key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
        ),
        "CREATE INDEX IF NOT EXISTS idx_discovery_date_score ON discovery_candidates (discovery_date, final_score DESC)",
        "CREATE INDEX IF NOT EXISTS idx_discovery_state ON discovery_candidates (state)",
        "CREATE INDEX IF NOT EXISTS idx_discovery_category ON discovery_candidates (category, sub_category)",
        "CREATE INDEX IF NOT EXISTS idx_daily_feed_rank ON daily_feed (feed_date, rank ASC)",
    ]
    for sql in statements:
        await env.DB.prepare(sql).run()


async def _meta_get(env, key: str, default=""):
    try:
        res = await env.DB.prepare("SELECT value FROM meta_kv WHERE key = ?").bind(key).all()
        if res.results:
            return _row_get(res.results[0], "value", default)
    except Exception:
        pass
    return default


async def _meta_set(env, key: str, value):
    await env.DB.prepare(
        "INSERT INTO meta_kv (key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at"
    ).bind(key, str(value)).run()


def _flatten_query_plan() -> list[dict]:
    plan = []
    for group in CONFIG.discovery_queries or []:
        if not isinstance(group, dict):
            continue
        category = str(group.get("category", "") or "").strip()
        sub_category = str(group.get("sub_category", "") or "").strip()
        for query in group.get("queries", []) or []:
            query = str(query or "").strip()
            if query:
                plan.append({
                    "category": category,
                    "sub_category": sub_category,
                    "query": query,
                })
    return plan


async def select_queries_for_run(env) -> list[dict]:
    plan = _flatten_query_plan()
    if not plan:
        return []

    try:
        cursor = int(await _meta_get(env, "discovery:query_cursor", "0") or 0)
    except Exception:
        cursor = 0

    take = max(1, min(len(plan), int(CONFIG.discovery_queries_per_run)))
    selected = [plan[(cursor + offset) % len(plan)] for offset in range(take)]
    await _meta_set(env, "discovery:query_cursor", (cursor + take) % len(plan))
    return selected


async def discovery_due(env, force: bool = False) -> bool:
    if force:
        return True
    if not CONFIG.discovery_enabled:
        return False

    raw = await _meta_get(env, "discovery:last_run_at", "")
    if not raw:
        return True
    try:
        previous = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
    except Exception:
        return True

    due_at = previous.astimezone(timezone.utc) + timedelta(hours=CONFIG.discovery_interval_hours)
    return datetime.now(timezone.utc) >= due_at


def cheap_gate_candidate(item: dict) -> tuple[bool, str, float]:
    text = str(item.get("body_raw") or item.get("snippet") or "").strip()
    if item.get("possibly_sensitive"):
        return False, "possibly_sensitive", 1.0
    # 查询端已经普遍带 -filter:replies，但 X SearchTimeline 偶尔仍会返回回复。
    # 回复可能技术上很相关，却往往依赖上文才能成立；这属于“发现质量”问题，
    # 不是用户对该技术主题不感兴趣，因此在 cheap gate 单独剔除。
    if item.get("is_reply"):
        return False, "reply", 0.0
    if len(text) < int(CONFIG.discovery_min_text_chars):
        return False, "too_short", 0.0

    penalty = float(estimate_spam_penalty(item))
    if penalty >= float(CONFIG.discovery_cheap_penalty_threshold):
        return False, "spam_promo_penalty", penalty

    return True, "", penalty


async def _load_feedback_events(env) -> list[dict]:
    try:
        res = await env.DB.prepare(
            "SELECT tweet_id, action, MAX(weight) AS weight, MAX(context) AS context, "
            "MAX(created_at) AS created_at "
            "FROM feedback_events GROUP BY tweet_id, action ORDER BY created_at DESC LIMIT 5000"
        ).all()
        out = []
        for row in res.results:
            out.append({
                "tweet_id": str(_row_get(row, "tweet_id", "") or ""),
                "action": str(_row_get(row, "action", "") or ""),
                "weight": float(_row_get(row, "weight", 0.0) or 0.0),
                "context": _row_get(row, "context", "") or "",
                "created_at": _row_get(row, "created_at", "") or "",
            })
        return out
    except Exception:
        return []


def _feedback_context(event: dict) -> dict:
    raw = event.get("context") or {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def build_discovery_quality_profile(events: list[dict]) -> dict:
    """Build a bounded query-level false-positive penalty.

    This field is deliberately orthogonal to topic preference. A user can say
    “this candidate should never have been discovered” without saying
    “I dislike databases / this author / this topic”.
    """
    raw_by_query = {}
    for event in events or []:
        context = _feedback_context(event)
        if str(context.get("feedback_scope", "") or "") != "discovery_quality":
            continue
        query = str(context.get("discovery_query", "") or "").strip()
        if not query:
            continue

        action = str(event.get("action", "") or "")
        # Current false-positive UI records the configured not_interested event
        # with discovery_quality scope. Positive accepted candidates can offset
        # query-level penalty when they carry the same provenance.
        if action == "not_interested":
            raw_by_query[query] = raw_by_query.get(query, 0.0) + 1.0
        elif action == "bookmark":
            raw_by_query[query] = raw_by_query.get(query, 0.0) - 0.50
        elif action == "copy":
            raw_by_query[query] = raw_by_query.get(query, 0.0) - 0.20

    # A single false positive should only nudge a query; repeated rejects can
    # cap the penalty at 0.08 rather than collapsing a useful topic stream.
    return {
        query: round(max(0.0, 0.08 * math.tanh(signal / 3.0)), 6)
        for query, signal in raw_by_query.items()
        if signal > 0
    }


def _score_with_quality_feedback(item: dict, quality_profile: dict) -> tuple[float, dict]:
    score, features = compute_related_hot_score(item)
    query = str(item.get("discovery_query", "") or "")
    penalty = float((quality_profile or {}).get(query, 0.0) or 0.0)
    if penalty > 0:
        score = max(0.0, score - penalty)
    features = dict(features)
    features["discovery_quality_penalty"] = round(penalty, 6)
    return round(score, 6), features


async def _known_bookmark_ids(env) -> set[str]:
    try:
        res = await env.DB.prepare("SELECT id FROM tweets").all()
        return {
            str(_row_get(row, "id", "") or "")
            for row in res.results
            if _row_get(row, "id", "")
        }
    except Exception:
        return set()


async def persist_candidates(env, candidates: list[dict]) -> int:
    if not candidates:
        return 0

    now = _now_iso()
    today = _today()
    normalized = []
    for item in candidates:
        payload = dict(item)
        normalized.append({
            "tweet_id": str(item.get("id", "") or ""),
            "first_seen_at": now,
            "last_seen_at": now,
            "discovery_date": today,
            "discovery_source": str(item.get("discovery_source", "x_search") or "x_search"),
            "discovery_query": str(item.get("discovery_query", "") or ""),
            "author": str(item.get("author", "") or ""),
            "username": str(item.get("username", "") or ""),
            "url": str(item.get("url", "") or ""),
            "created_at": str(item.get("created_at", "") or ""),
            "category": str(item.get("category", "") or ""),
            "sub_category": str(item.get("sub_category", "") or ""),
            "title": str(item.get("title", "") or ""),
            "snippet": str(item.get("snippet", "") or ""),
            "body_raw": str(item.get("body_raw", "") or ""),
            "likes": int(item.get("likes", 0) or 0),
            "retweets": int(item.get("retweets", 0) or 0),
            "views": int(item.get("views", 0) or 0),
            "penalty_score": float(item.get("penalty_score", 0.0) or 0.0),
            "payload_json": json.dumps(payload, ensure_ascii=False),
        })

    sql = """
    INSERT INTO discovery_candidates (
        tweet_id, first_seen_at, last_seen_at, discovery_date, discovery_source, discovery_query,
        author, username, url, created_at, category, sub_category, title, snippet, body_raw,
        likes, retweets, views, penalty_score, state, payload_json
    )
    SELECT
        json_extract(value, '$.tweet_id'),
        json_extract(value, '$.first_seen_at'),
        json_extract(value, '$.last_seen_at'),
        json_extract(value, '$.discovery_date'),
        json_extract(value, '$.discovery_source'),
        json_extract(value, '$.discovery_query'),
        json_extract(value, '$.author'),
        json_extract(value, '$.username'),
        json_extract(value, '$.url'),
        json_extract(value, '$.created_at'),
        json_extract(value, '$.category'),
        json_extract(value, '$.sub_category'),
        json_extract(value, '$.title'),
        json_extract(value, '$.snippet'),
        json_extract(value, '$.body_raw'),
        COALESCE(json_extract(value, '$.likes'), 0),
        COALESCE(json_extract(value, '$.retweets'), 0),
        COALESCE(json_extract(value, '$.views'), 0),
        COALESCE(json_extract(value, '$.penalty_score'), 0),
        'candidate',
        json_extract(value, '$.payload_json')
    FROM json_each(?)
    WHERE json_extract(value, '$.tweet_id') != ''
    ON CONFLICT(tweet_id) DO UPDATE SET
        last_seen_at = excluded.last_seen_at,
        discovery_date = excluded.discovery_date,
        discovery_source = excluded.discovery_source,
        discovery_query = excluded.discovery_query,
        author = excluded.author,
        username = excluded.username,
        url = excluded.url,
        created_at = excluded.created_at,
        category = excluded.category,
        sub_category = excluded.sub_category,
        title = excluded.title,
        snippet = excluded.snippet,
        body_raw = excluded.body_raw,
        likes = excluded.likes,
        retweets = excluded.retweets,
        views = excluded.views,
        penalty_score = excluded.penalty_score,
        payload_json = excluded.payload_json,
        state = CASE
            WHEN discovery_candidates.state IN ('hidden', 'rejected', 'saved_pending', 'saved') THEN discovery_candidates.state
            ELSE 'candidate'
        END
    """
    await env.DB.prepare(sql).bind(json.dumps(normalized, ensure_ascii=False)).run()
    return len(normalized)


def _judge_prompt(batch: list[dict]) -> str:
    compact = []
    for item in batch:
        compact.append({
            "id": str(item.get("id", "")),
            "category": item.get("category", ""),
            "sub_category": item.get("sub_category", ""),
            "author": item.get("username") or item.get("author") or "",
            "text": str(item.get("body_raw") or item.get("snippet") or "")[:1400],
            "likes": int(item.get("likes", 0) or 0),
            "retweets": int(item.get("retweets", 0) or 0),
            "views": int(item.get("views", 0) or 0),
        })

    return (
        "You are the quality judge for a personal technology intelligence feed. "
        "For each X post, score relevance to its supplied taxonomy, content quality, novelty, "
        "source trust, promotion probability, NSFW probability and spam/clickbait probability. "
        "Scores must be numbers in [0,1]. Relevance measures substantive fit, not keyword overlap. "
        "Quality rewards concrete evidence, mechanisms, technical detail, original observation or "
        "high-signal synthesis. Novelty rewards information beyond generic/common knowledge. "
        "Promotion includes affiliate sales, sponsorship, engagement bait and thin self-promotion. "
        "Return ONLY a JSON array. Each object must contain: "
        "id,relevance,quality,novelty,source,promo,nsfw,spam,reason. "
        "Keep reason under 80 characters.\n\nINPUT:\n"
        + json.dumps(compact, ensure_ascii=False)
    )


def _parse_judge_array(raw) -> list[dict]:
    if isinstance(raw, dict):
        raw = raw.get("response", raw.get("result", raw))
    elif hasattr(raw, "response"):
        raw = getattr(raw, "response", "")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]

    text = str(raw or "").strip()
    if not text:
        return []
    fence = chr(96) * 3
    if text.startswith(fence):
        text = text.strip(chr(96))
        if text.lower().startswith("json"):
            text = text[4:].lstrip()

    left = text.find("[")
    right = text.rfind("]")
    if left >= 0 and right > left:
        text = text[left:right + 1]
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _post_judge_rejection_reason(item: dict) -> str:
    features = item.get("related_hot_features") or {}
    relevance = float(item.get("relevance_score", features.get("relevance", 0.0)) or 0.0)
    quality = float(item.get("quality_score", features.get("quality", 0.0)) or 0.0)
    final_score = float(item.get("related_hot_score", 0.0) or 0.0)
    risk = max(
        float(item.get("promo_probability", 0.0) or 0.0),
        float(item.get("nsfw_probability", 0.0) or 0.0),
        float(item.get("spam_probability", 0.0) or 0.0),
    )

    if risk >= CONFIG.discovery_ai_reject_probability:
        return "ai_risk"
    if relevance < CONFIG.discovery_min_relevance:
        return "low_relevance"
    if quality < CONFIG.discovery_min_quality:
        return "low_quality"
    if final_score < CONFIG.discovery_min_final_score:
        return "low_final_score"
    return ""


def _apply_post_judge_gates(items: list[dict]) -> int:
    rejected = 0
    for item in items:
        reason = _post_judge_rejection_reason(item)
        item["discovery_reject_reason"] = reason
        item["discovery_rejected"] = bool(reason)
        if reason:
            rejected += 1
    return rejected


async def judge_candidates(env, candidates: list[dict]) -> tuple[list[dict], dict]:
    if not candidates:
        return [], {"mode": "none", "ai_calls": 0}

    events = await _load_feedback_events(env)
    preferred, preference_profile = apply_preference_profile(candidates, events)
    quality_profile = build_discovery_quality_profile(events)

    for item in preferred:
        score, features = _score_with_quality_feedback(item, quality_profile)
        item["related_hot_score"] = score
        item["related_hot_features"] = features

    preferred.sort(
        key=lambda item: float(item.get("related_hot_score", 0.0)),
        reverse=True,
    )
    preferred = preferred[:max(1, int(CONFIG.discovery_ai_batch_max_candidates))]

    if not hasattr(env, "AI") or JsJSON is None:
        rejected_count = _apply_post_judge_gates(preferred)
        return preferred, {
            "mode": "deterministic",
            "ai_calls": 0,
            "rejected_count": rejected_count,
            "preference_evidence_pairs": int(preference_profile.get("evidence_pairs", 0) or 0),
            "quality_feedback_queries": len(quality_profile),
        }

    model_candidates = [CONFIG.discovery_ai_judge_model] + [
        model for model in CONFIG.workers_ai_models
        if model != CONFIG.discovery_ai_judge_model
    ]

    ai_calls = 0
    judged_count = 0
    for offset in range(0, len(preferred), 12):
        batch = preferred[offset:offset + 12]
        parsed = []
        used_model = ""
        last_error = ""

        for model_id in model_candidates:
            try:
                payload = JsJSON.parse(json.dumps({
                    "prompt": _judge_prompt(batch),
                    "temperature": 0.1,
                    "max_tokens": 1800,
                }))
                result = await env.AI.run(model_id, payload)
                ai_calls += 1
                parsed = _parse_judge_array(result)
                if parsed:
                    used_model = model_id
                    break
            except Exception as err:
                last_error = str(err)
                continue

        if not parsed:
            for item in batch:
                item["ai_reason"] = "deterministic fallback" + (
                    f": {last_error[:80]}" if last_error else ""
                )
                item["ai_model"] = "deterministic"
            continue

        result_by_id = {
            str(row.get("id", "")): row
            for row in parsed
            if row.get("id")
        }

        for item in batch:
            row = result_by_id.get(str(item.get("id", "")))
            if not row:
                item["ai_reason"] = "AI batch omitted item; deterministic fallback"
                item["ai_model"] = used_model or "deterministic"
                continue

            def score(name, default):
                try:
                    return max(0.0, min(1.0, float(row.get(name, default))))
                except Exception:
                    return default

            item["relevance_score"] = score(
                "relevance",
                item["related_hot_features"]["relevance"],
            )
            item["quality_score"] = score(
                "quality",
                item["related_hot_features"]["quality"],
            )
            item["novelty_score"] = score(
                "novelty",
                item["related_hot_features"]["novelty"],
            )
            item["source_score"] = score(
                "source",
                item["related_hot_features"]["source"],
            )
            item["promo_probability"] = score("promo", 0.0)
            item["nsfw_probability"] = score("nsfw", 0.0)
            item["spam_probability"] = score("spam", 0.0)
            item["ai_reason"] = str(row.get("reason", "") or "")[:240]
            item["ai_model"] = used_model

            final_score, final_features = _score_with_quality_feedback(item, quality_profile)
            item["related_hot_score"] = final_score
            item["related_hot_features"] = final_features
            judged_count += 1

    rejected_count = _apply_post_judge_gates(preferred)
    return preferred, {
        "mode": "workers_ai_micro_batch",
        "ai_calls": ai_calls,
        "judged_count": judged_count,
        "rejected_count": rejected_count,
        "preference_evidence_pairs": int(preference_profile.get("evidence_pairs", 0) or 0),
        "quality_feedback_queries": len(quality_profile),
    }


async def persist_judgements(env, items: list[dict]) -> int:
    if not items:
        return 0

    normalized = []
    for item in items:
        features = item.get("related_hot_features") or {}
        normalized.append({
            "tweet_id": str(item.get("id", "") or ""),
            "relevance_score": float(item.get("relevance_score", features.get("relevance", 0.0)) or 0.0),
            "quality_score": float(item.get("quality_score", features.get("quality", 0.0)) or 0.0),
            "novelty_score": float(item.get("novelty_score", features.get("novelty", 0.0)) or 0.0),
            "engagement_velocity": float(features.get("engagement_velocity", 0.0) or 0.0),
            "source_score": float(item.get("source_score", features.get("source", 0.0)) or 0.0),
            "freshness_score": float(features.get("freshness", 0.0) or 0.0),
            "penalty_score": float(features.get("penalty", 0.0) or 0.0),
            "final_score": float(item.get("related_hot_score", 0.0) or 0.0),
            "ai_reason": str(item.get("ai_reason", "") or ""),
            "ai_model": str(item.get("ai_model", "deterministic") or "deterministic"),
            "rank_version": str(CONFIG.related_hot_version),
            "state": "rejected" if item.get("discovery_rejected") else "judged",
        })

    sql = """
    UPDATE discovery_candidates SET
        relevance_score = json_extract(j.value, '$.relevance_score'),
        quality_score = json_extract(j.value, '$.quality_score'),
        novelty_score = json_extract(j.value, '$.novelty_score'),
        engagement_velocity = json_extract(j.value, '$.engagement_velocity'),
        source_score = json_extract(j.value, '$.source_score'),
        freshness_score = json_extract(j.value, '$.freshness_score'),
        penalty_score = json_extract(j.value, '$.penalty_score'),
        final_score = json_extract(j.value, '$.final_score'),
        ai_reason = json_extract(j.value, '$.ai_reason'),
        ai_model = json_extract(j.value, '$.ai_model'),
        rank_version = json_extract(j.value, '$.rank_version'),
        state = CASE
            WHEN state IN ('hidden', 'rejected', 'saved_pending', 'saved') THEN state
            ELSE json_extract(j.value, '$.state')
        END
    FROM json_each(?) AS j
    WHERE tweet_id = json_extract(j.value, '$.tweet_id')
    """
    await env.DB.prepare(sql).bind(json.dumps(normalized, ensure_ascii=False)).run()
    return len(normalized)


async def _today_rankable_rows(env) -> list[dict]:
    res = await env.DB.prepare(
        "SELECT * FROM discovery_candidates "
        "WHERE discovery_date = ? "
        "AND state NOT IN ('hidden', 'rejected', 'saved_pending', 'saved') "
        "AND final_score IS NOT NULL "
        "ORDER BY final_score DESC LIMIT 2000"
    ).bind(_today()).all()

    rows = []
    for row in res.results:
        payload = _json_obj(_row_get(row, "payload_json", "{}"))
        state = str(_row_get(row, "state", "") or "")
        payload.update({
            "id": str(_row_get(row, "tweet_id", payload.get("id", "")) or ""),
            "author": _row_get(row, "author", payload.get("author", "")) or "",
            "username": _row_get(row, "username", payload.get("username", "")) or "",
            "url": _row_get(row, "url", payload.get("url", "")) or "",
            "created_at": _row_get(row, "created_at", payload.get("created_at", "")) or "",
            "category": _row_get(row, "category", payload.get("category", "")) or "",
            "sub_category": _row_get(row, "sub_category", payload.get("sub_category", "")) or "",
            "title": _row_get(row, "title", payload.get("title", "")) or "",
            "snippet": _row_get(row, "snippet", payload.get("snippet", "")) or "",
            "body_raw": _row_get(row, "body_raw", payload.get("body_raw", "")) or "",
            "likes": int(_row_get(row, "likes", payload.get("likes", 0)) or 0),
            "retweets": int(_row_get(row, "retweets", payload.get("retweets", 0)) or 0),
            "views": int(_row_get(row, "views", payload.get("views", 0)) or 0),
            "related_hot_score": float(_row_get(row, "final_score", 0.0) or 0.0),
            "discovery_reason": _row_get(row, "ai_reason", "") or "",
            "discovery_query": _row_get(row, "discovery_query", "") or "",
            "discovery_source": _row_get(row, "discovery_source", "") or "",
            "source_kind": "bookmark" if state == "saved" else "discovery",
            "is_bookmark": state == "saved",
            "discovery_state": state,
        })
        rows.append(payload)
    return rows


def diversity_select(rows: list[dict], limit: int | None = None) -> list[dict]:
    limit = max(1, int(limit or CONFIG.discovery_daily_limit))
    author_cap = max(1, int(CONFIG.discovery_author_daily_cap))
    sub_cap = max(1, int(CONFIG.discovery_subcategory_daily_cap))
    category_cap = max(
        1,
        int(limit * float(CONFIG.discovery_category_daily_ratio_cap)),
    )

    author_counts = {}
    sub_counts = {}
    category_counts = {}
    selected = []

    for item in sorted(
        rows,
        key=lambda row: float(row.get("related_hot_score", 0.0)),
        reverse=True,
    ):
        author_key = str(
            item.get("username") or item.get("author") or "unknown"
        ).lower()
        category = str(item.get("category") or "未分类")
        sub = str(item.get("sub_category") or "未分类")

        if author_counts.get(author_key, 0) >= author_cap:
            continue
        if sub_counts.get((category, sub), 0) >= sub_cap:
            continue
        if category_counts.get(category, 0) >= category_cap:
            continue

        selected.append(item)
        author_counts[author_key] = author_counts.get(author_key, 0) + 1
        sub_counts[(category, sub)] = sub_counts.get((category, sub), 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1

        if len(selected) >= limit:
            break

    return selected


async def materialize_daily_feed(env) -> tuple[int, list[dict]]:
    rows = await _today_rankable_rows(env)
    selected = diversity_select(rows, CONFIG.discovery_daily_limit)
    today = _today()

    await env.DB.prepare("DELETE FROM daily_feed WHERE feed_date = ?").bind(today).run()

    if selected:
        records = [
            {
                "feed_date": today,
                "tweet_id": str(item.get("id", "")),
                "rank": idx + 1,
                "final_score": float(item.get("related_hot_score", 0.0) or 0.0),
                "category": str(item.get("category", "") or ""),
                "sub_category": str(item.get("sub_category", "") or ""),
                "selected_at": _now_iso(),
            }
            for idx, item in enumerate(selected)
        ]
        sql = """
        INSERT INTO daily_feed (
            feed_date, tweet_id, rank, final_score, category, sub_category, selected_at
        )
        SELECT
            json_extract(value, '$.feed_date'),
            json_extract(value, '$.tweet_id'),
            json_extract(value, '$.rank'),
            json_extract(value, '$.final_score'),
            json_extract(value, '$.category'),
            json_extract(value, '$.sub_category'),
            json_extract(value, '$.selected_at')
        FROM json_each(?)
        """
        await env.DB.prepare(sql).bind(
            json.dumps(records, ensure_ascii=False)
        ).run()

        await env.DB.prepare(
            "UPDATE discovery_candidates SET state = 'judged' "
            "WHERE discovery_date = ? AND state = 'selected'"
        ).bind(today).run()

        ids = [str(item.get("id", "")) for item in selected if item.get("id")]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            await env.DB.prepare(
                f"UPDATE discovery_candidates SET state = 'selected' "
                f"WHERE tweet_id IN ({placeholders}) "
                "AND state NOT IN ('hidden','saved')"
            ).bind(*ids).run()

    return len(selected), selected


async def get_daily_feed(env, feed_date: str | None = None) -> list[dict]:
    if not hasattr(env, "DB"):
        return []
    await ensure_discovery_schema(env)
    day = feed_date or _today()

    res = await env.DB.prepare(
        "SELECT d.*, f.rank AS feed_rank, f.final_score AS feed_score "
        "FROM daily_feed f "
        "JOIN discovery_candidates d ON d.tweet_id = f.tweet_id "
        "WHERE f.feed_date = ? AND d.state NOT IN ('hidden', 'rejected', 'saved_pending', 'saved') "
        "ORDER BY f.rank ASC"
    ).bind(day).all()

    items = []
    for row in res.results:
        payload = _json_obj(_row_get(row, "payload_json", "{}"))
        state = str(_row_get(row, "state", "") or "")
        payload.update({
            "id": str(_row_get(row, "tweet_id", payload.get("id", "")) or ""),
            "author": _row_get(row, "author", payload.get("author", "")) or "",
            "username": _row_get(row, "username", payload.get("username", "")) or "",
            "url": _row_get(row, "url", payload.get("url", "")) or "",
            "created_at": _row_get(row, "created_at", payload.get("created_at", "")) or "",
            "category": _row_get(row, "category", payload.get("category", "")) or "",
            "sub_category": _row_get(row, "sub_category", payload.get("sub_category", "")) or "",
            "title": _row_get(row, "title", payload.get("title", "")) or "",
            "snippet": _row_get(row, "snippet", payload.get("snippet", "")) or "",
            "body_raw": _row_get(row, "body_raw", payload.get("body_raw", "")) or "",
            "likes": int(_row_get(row, "likes", payload.get("likes", 0)) or 0),
            "retweets": int(_row_get(row, "retweets", payload.get("retweets", 0)) or 0),
            "views": int(_row_get(row, "views", payload.get("views", 0)) or 0),
            "related_hot_score": float(_row_get(row, "feed_score", 0.0) or 0.0),
            "discovery_reason": _row_get(row, "ai_reason", "") or "",
            "discovery_query": _row_get(row, "discovery_query", "") or "",
            "feed_rank": int(_row_get(row, "feed_rank", 0) or 0),
            "source_kind": "bookmark" if state == "saved" else "discovery",
            "is_bookmark": state == "saved",
            "discovery_state": state,
        })
        items.append(payload)
    return items


async def set_candidate_state(env, tweet_id: str, state: str) -> tuple[bool, str]:
    allowed = {"hidden", "rejected", "saved_pending", "saved", "candidate", "judged", "selected"}
    if state not in allowed:
        return False, f"unsupported state: {state}"
    if not hasattr(env, "DB"):
        return False, "Discovery state requires D1"

    await ensure_discovery_schema(env)
    await env.DB.prepare(
        "UPDATE discovery_candidates "
        "SET state = ?, last_seen_at = ? "
        "WHERE tweet_id = ?"
    ).bind(state, _now_iso(), str(tweet_id)).run()

    if state in ("hidden", "rejected", "saved_pending", "saved"):
        await env.DB.prepare(
            "DELETE FROM daily_feed WHERE tweet_id = ?"
        ).bind(str(tweet_id)).run()
    return True, "candidate state updated"


async def reconcile_candidate_promotions(env) -> int:
    """Promote saved_pending candidates only after the bookmark plane confirms them.

    The tweets table remains the durable bookmark truth. This bridge closes the
    explicit save -> X -> bookmark sync -> durable knowledge transaction without
    ever copying an unverified recommendation directly into tweets.
    """
    if not hasattr(env, "DB"):
        return 0
    await ensure_discovery_schema(env)
    try:
        res = await env.DB.prepare(
            "SELECT COUNT(*) AS total FROM discovery_candidates "
            "WHERE state = 'saved_pending' AND tweet_id IN (SELECT id FROM tweets)"
        ).all()
        total = int(_row_get(res.results[0], "total", 0) or 0) if res.results else 0
        if total:
            await env.DB.prepare(
                "UPDATE discovery_candidates SET state = 'saved', last_seen_at = ? "
                "WHERE state = 'saved_pending' AND tweet_id IN (SELECT id FROM tweets)"
            ).bind(_now_iso()).run()
            await env.DB.prepare(
                "DELETE FROM daily_feed WHERE tweet_id IN "
                "(SELECT tweet_id FROM discovery_candidates WHERE state = 'saved')"
            ).run()
        return total
    except Exception:
        return 0


async def get_discovery_status(env) -> dict:
    if not hasattr(env, "DB"):
        return {
            "success": False,
            "available": False,
            "message": "Discovery Plane requires D1",
        }

    await ensure_discovery_schema(env)
    today = _today()
    counts = {
        "candidate": 0,
        "judged": 0,
        "selected": 0,
        "hidden": 0,
        "saved_pending": 0,
        "saved": 0,
        "rejected": 0,
    }
    try:
        res = await env.DB.prepare(
            "SELECT state, COUNT(*) AS total "
            "FROM discovery_candidates WHERE discovery_date = ? "
            "GROUP BY state"
        ).bind(today).all()
        for row in res.results:
            state = str(_row_get(row, "state", "") or "")
            counts[state] = int(_row_get(row, "total", 0) or 0)
    except Exception:
        pass

    try:
        feed_res = await env.DB.prepare(
            "SELECT COUNT(*) AS total FROM daily_feed WHERE feed_date = ?"
        ).bind(today).all()
        feed_count = int(_row_get(feed_res.results[0], "total", 0) or 0) if feed_res.results else 0
    except Exception:
        feed_count = 0

    return {
        "success": True,
        "available": True,
        "enabled": bool(CONFIG.discovery_enabled),
        "today": today,
        "last_attempt_at": await _meta_get(env, "discovery:last_attempt_at", ""),
        "last_run_at": await _meta_get(env, "discovery:last_run_at", ""),
        "last_run_summary": await _meta_get(env, "discovery:last_run_summary", ""),
        "query_cursor": await _meta_get(env, "discovery:query_cursor", "0"),
        "states": counts,
        "daily_feed_count": feed_count,
    }


async def run_discovery_cycle(env, force: bool = False) -> tuple[int, dict]:
    if not CONFIG.discovery_enabled:
        return 200, {
            "success": True,
            "skipped": True,
            "reason": "discovery_disabled",
        }
    if not hasattr(env, "DB"):
        return 400, {
            "success": False,
            "error": "Discovery Plane requires D1",
        }

    await ensure_discovery_schema(env)
    if not await discovery_due(env, force=force):
        return 200, {
            "success": True,
            "skipped": True,
            "reason": "not_due",
        }

    auth_token = getattr(env, "X_AUTH_TOKEN", "") or ""
    ct0 = getattr(env, "X_CT0", "") or ""
    if not auth_token or not ct0:
        return 400, {
            "success": False,
            "error": "X_DISCOVERY_AUTH_MISSING",
            "message": "Discovery uses the same X_AUTH_TOKEN / X_CT0 session as bookmark sync.",
        }

    selected_queries = await select_queries_for_run(env)
    if not selected_queries:
        return 400, {
            "success": False,
            "error": "DISCOVERY_QUERY_PLAN_EMPTY",
            "message": "prompts/discovery_queries.json has no usable queries.",
        }

    known_bookmarks = await _known_bookmark_ids(env)
    raw_count = 0
    rejected_count = 0
    duplicate_bookmark_count = 0
    accepted_by_id = {}
    query_reports = []

    for spec in selected_queries:
        query = spec["query"]
        try:
            rows, meta = await fetch_search_timeline(
                auth_token,
                ct0,
                query,
                count=CONFIG.discovery_search_count,
                max_pages=CONFIG.discovery_max_pages_per_query,
                category_hint=spec.get("category", ""),
                sub_category_hint=spec.get("sub_category", ""),
            )
            query_reports.append(meta)
        except Exception as err:
            query_reports.append({
                "query": query,
                "error": str(err),
                "pulled_count": 0,
            })
            continue

        raw_count += len(rows)
        for item in rows:
            tweet_id = str(item.get("id", "") or "")
            if not tweet_id:
                continue
            if tweet_id in known_bookmarks:
                duplicate_bookmark_count += 1
                continue

            accepted, _reason, penalty = cheap_gate_candidate(item)
            if not accepted:
                rejected_count += 1
                continue

            item["penalty_score"] = penalty
            item["discovery_source"] = "x_search"
            item["discovery_query"] = query
            accepted_by_id[tweet_id] = item

    successful_queries = sum(
        1 for report in query_reports if not report.get("error")
    )
    await _meta_set(env, "discovery:last_attempt_at", _now_iso())
    if successful_queries == 0:
        return 502, {
            "success": False,
            "error": "DISCOVERY_SOURCE_UNAVAILABLE",
            "message": "All SearchTimeline queries failed; bookmark sync remains unaffected.",
            "queries": query_reports,
        }

    accepted = list(accepted_by_id.values())
    persisted = await persist_candidates(env, accepted)

    judged, judge_meta = await judge_candidates(env, accepted)
    judged_persisted = await persist_judgements(env, judged)
    feed_count, _selected = await materialize_daily_feed(env)

    summary = {
        "raw": raw_count,
        "accepted": len(accepted),
        "judged": judged_persisted,
        "feed": feed_count,
    }
    await _meta_set(env, "discovery:last_run_at", _now_iso())
    await _meta_set(
        env,
        "discovery:last_run_summary",
        json.dumps(summary, ensure_ascii=False),
    )

    return 200, {
        "success": True,
        "stage": "published",
        "query_count": len(selected_queries),
        "successful_queries": successful_queries,
        "raw_candidates": raw_count,
        "bookmark_duplicates": duplicate_bookmark_count,
        "cheap_rejected": rejected_count,
        "accepted_candidates": len(accepted),
        "persisted_candidates": persisted,
        "judged_candidates": judged_persisted,
        "daily_feed_count": feed_count,
        "judge": judge_meta,
        "queries": query_reports,
    }

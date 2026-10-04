# -*- coding: utf-8 -*-
"""存储层与拓扑重整化状态机模块。

职责：
1. 边缘内存热缓存与 HTTP JSON 响应封装 (json_resp, invalidate_cache)
2. 存储级联下潜架构 (D1 边缘关系库 -> KV 边缘键值对 -> 静态离线兜底)
3. 推文读写与删除操作 (load_tweets, save_tweets, delete_tweet_from_storage)
4. 拓扑状态感知与自适应重整化状态机 (get_topology_status, renormalize_topology)
5. 待分类推文批量智能重分类 (batch_classify_pending)
"""

import json
from datetime import datetime, timezone
from config_loader import CONFIG
from classifier import rule_classify_tweet, get_existing_categories, ai_classify_tweet
from ranking import enrich_related_hot_many

try:
    from js import Response, Headers, Object as JsObject
except ImportError:
    Response = None
    Headers = None
    JsObject = None

# 边缘实例级内存高速缓存（读写分离：只在写入时使缓存失效）
_MEM_CACHE_TWEETS = None


def invalidate_cache():
    """使边缘内存高速缓存失效。"""
    global _MEM_CACHE_TWEETS
    _MEM_CACHE_TWEETS = None


def json_resp(data, status: int = 200, cache_seconds: int = 0):
    """统一生成标准 JSON 响应，支持边缘 CDN 与浏览器双层缓存控制。"""
    if Response is None:
        return json.dumps(data)

    headers = Headers.new()
    headers.set("Content-Type", "application/json; charset=utf-8")
    if cache_seconds > 0:
        headers.set(
            "Cache-Control",
            f"public, max-age={cache_seconds}, s-maxage={cache_seconds * 5}, stale-while-revalidate=86400",
        )
    else:
        headers.set("Cache-Control", "no-store, no-cache, must-revalidate")

    init = JsObject.new()
    init.status = status
    init.headers = headers
    return Response.new(json.dumps(data, ensure_ascii=False), init)


def get_kv_binding(env):
    """自适应探测 Cloudflare KV 存储绑定。"""
    if hasattr(env, "KV"):
        return env.KV
    if hasattr(env, "KV_BOOKMARKS"):
        return env.KV_BOOKMARKS
    return None


def _row_get(row, key: str, default=None):
    """兼容 Python dict、JsProxy/Record 与属性访问形式的 D1 行对象。"""
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


def _json_list(value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


async def _load_bookmark_order(env) -> list[str]:
    """读取 X 收藏流顺序；第 0 个 ID 表示当前最新收藏。"""
    if not hasattr(env, "DB"):
        return []
    try:
        stmt = env.DB.prepare("SELECT value FROM meta_kv WHERE key = ?").bind("x_bookmark_order")
        res = await stmt.all()
        if not res.results:
            return []
        raw = _row_get(res.results[0], "value", "") or ""
        parsed = json.loads(raw)
        return [str(x) for x in parsed if x]
    except Exception:
        return []


async def _save_bookmark_order(env, ordered_ids: list[str]):
    """D1 Profile 保存 X 当前权威收藏顺序。KV 直接使用列表顺序，不需要额外元数据。"""
    if not hasattr(env, "DB"):
        return
    await env.DB.prepare(
        "CREATE TABLE IF NOT EXISTS meta_kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
    ).run()
    await env.DB.prepare(
        "INSERT INTO meta_kv (key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at"
    ).bind(
        "x_bookmark_order",
        json.dumps([str(x) for x in ordered_ids if x], ensure_ascii=False),
    ).run()


async def get_known_tweet_ids(env) -> set[str]:
    """读取当前主存储已有 ID。

    Storage Plan:
    - DB binding 存在：D1 是唯一主存储；读取失败应暴露错误，不静默切 KV。
    - DB binding 不存在：若有 KV，则 KV 是主存储。
    """
    if hasattr(env, "DB"):
        try:
            res = await env.DB.prepare("SELECT id FROM tweets").all()
            return {
                str(_row_get(row, "id", ""))
                for row in res.results
                if _row_get(row, "id", "")
            }
        except Exception as err:
            raise RuntimeError(f"D1 已绑定但读取已有 ID 失败: {err}")

    kv = get_kv_binding(env)
    if kv:
        try:
            raw = await kv.get("tweets:all")
            items = json.loads(raw) if raw else []
            return {str(item.get("id")) for item in items if item.get("id")}
        except Exception as err:
            raise RuntimeError(f"KV 已绑定但读取已有 ID 失败: {err}")

    return set()


def _chunk_records(records: list[dict], max_bytes: int = 450_000) -> list[list[dict]]:
    """按 JSON UTF-8 大小分块，避免单个 D1 绑定 payload 过大。"""
    chunks = []
    current = []
    current_bytes = 2
    for item in records:
        item_bytes = len(json.dumps(item, ensure_ascii=False).encode("utf-8")) + 1
        if current and current_bytes + item_bytes > max_bytes:
            chunks.append(current)
            current = []
            current_bytes = 2
        current.append(item)
        current_bytes += item_bytes
    if current:
        chunks.append(current)
    return chunks


async def load_tweets(env, bypass_cache: bool = False) -> dict:
    """加载推文数据：D1 为权威，bookmark_position 表示 X 当前收藏流顺序。"""
    global _MEM_CACHE_TWEETS
    if _MEM_CACHE_TWEETS is not None and not bypass_cache:
        # related-hot contains time-decay features. Recompute the projection on
        # every read even when the source rows themselves are memory-cached.
        cached = dict(_MEM_CACHE_TWEETS)
        cached["data"] = enrich_related_hot_many(cached.get("data", []))
        return cached

    if hasattr(env, "DB"):
        try:
            # 不在 SQL 层按 likes 排序。收藏流顺序来自 X timeline，而不是互动量。
            stmt = env.DB.prepare("SELECT * FROM tweets")
            db_res = await stmt.all()
            rows = db_res.results
            order = await _load_bookmark_order(env)
            order_map = {tweet_id: idx for idx, tweet_id in enumerate(order)}
            unordered_base = len(order) + 1_000_000

            tweets_list = []
            for row_index, r in enumerate(rows):
                body_val = _row_get(r, "body_raw", "") or _row_get(r, "snippet", "")
                title_val = _row_get(r, "title", "")
                default_sub = rule_classify_tweet(body_val, title_val)[1]
                tweet_id = str(_row_get(r, "id", ""))

                row_dict = {
                    "id": tweet_id,
                    "filename": _row_get(r, "filename", ""),
                    "category": _row_get(r, "category", "") or "未分类",
                    "sub_category": _row_get(r, "sub_category", "") or default_sub,
                    "title": title_val,
                    "author": _row_get(r, "author", ""),
                    "username": _row_get(r, "username", ""),
                    "avatar": _row_get(r, "avatar", "") or "",
                    "url": _row_get(r, "url", ""),
                    "created_at": _row_get(r, "created_at", ""),
                    "likes": int(_row_get(r, "likes", 0) or 0),
                    "retweets": int(_row_get(r, "retweets", 0) or 0),
                    "views": int(_row_get(r, "views", 0) or 0),
                    "has_media": bool(_row_get(r, "has_media", 0)),
                    "media_type": _row_get(r, "media_type", ""),
                    "images": _json_list(_row_get(r, "images", "[]")),
                    "videos": _json_list(_row_get(r, "videos", "[]")),
                    "snippet": _row_get(r, "snippet", ""),
                    "body_raw": _row_get(r, "body_raw", ""),
                    "body_html": _row_get(r, "body_html", ""),
                    "classify_status": _row_get(r, "classify_status", "settled") or "settled",
                    # 越小越新；没有历史收藏顺序的老数据排在后面。
                    "bookmark_position": order_map.get(tweet_id, unordered_base + row_index),
                }
                tweets_list.append(row_dict)

            tweets_list.sort(key=lambda item: int(item.get("bookmark_position", unordered_base)))
            tweets_list = enrich_related_hot_many(tweets_list)

            _MEM_CACHE_TWEETS = {
                "success": True,
                "source": "Cloudflare D1",
                "total": len(tweets_list),
                "bookmark_order_count": len(order),
                "data": tweets_list,
            }
            return _MEM_CACHE_TWEETS
        except Exception as d1_err:
            return {
                "success": False,
                "source": "Cloudflare D1",
                "storage_profile": "d1",
                "message": f"D1 已绑定但读取失败: {str(d1_err)}",
                "data": [],
            }

    kv = get_kv_binding(env)
    if kv:
        try:
            raw_kv = await kv.get("tweets:all")
            if raw_kv:
                kv_tweets = json.loads(raw_kv)
                if not isinstance(kv_tweets, list):
                    kv_tweets = []
                for idx, item in enumerate(kv_tweets):
                    if isinstance(item, dict):
                        item["bookmark_position"] = idx
                kv_tweets = enrich_related_hot_many(kv_tweets)
                _MEM_CACHE_TWEETS = {
                    "success": True,
                    "source": "Cloudflare KV",
                    "storage_profile": "kv",
                    "total": len(kv_tweets),
                    "data": kv_tweets,
                }
                return _MEM_CACHE_TWEETS
        except Exception as kv_err:
            print("从 KV 读取异常:", str(kv_err))

    return {
        "success": False,
        "message": "Cloud Profile 未探测到 D1 或 KV 主存储。请绑定云存储，或使用 Local Profile。",
        "data": [],
    }


async def record_feedback_event(
    env,
    event_id: str,
    tweet_id: str,
    action: str,
    context=None,
) -> tuple[bool, str, dict]:
    """Persist one explicit/implicit preference signal.

    Feedback is append-only training data. It must never mutate source content or
    recommendation scores in-place; later ranking jobs aggregate these events
    into user/topic/author preferences.
    """
    event_id = str(event_id or "").strip()[:128]
    tweet_id = str(tweet_id or "").strip()[:128]
    action = str(action or "").strip()

    if not event_id or not tweet_id:
        return False, "event_id 和 tweet_id 不能为空", {}
    if action not in CONFIG.feedback_weights:
        return False, f"不支持的 feedback action: {action}", {}

    weight = float(CONFIG.feedback_weights[action])
    if isinstance(context, dict):
        context_text = json.dumps(context, ensure_ascii=False, separators=(",", ":"))[:2000]
    else:
        context_text = str(context or "")[:2000]

    payload = {
        "event_id": event_id,
        "tweet_id": tweet_id,
        "action": action,
        "weight": weight,
        "context": context_text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if hasattr(env, "DB"):
        try:
            await env.DB.prepare(
                "CREATE TABLE IF NOT EXISTS feedback_events ("
                "event_id TEXT PRIMARY KEY, tweet_id TEXT NOT NULL, action TEXT NOT NULL, "
                "weight REAL NOT NULL, context TEXT, created_at TEXT NOT NULL)"
            ).run()
            await env.DB.prepare(
                "INSERT OR IGNORE INTO feedback_events "
                "(event_id, tweet_id, action, weight, context, created_at) VALUES (?, ?, ?, ?, ?, ?)"
            ).bind(
                payload["event_id"],
                payload["tweet_id"],
                payload["action"],
                payload["weight"],
                payload["context"],
                payload["created_at"],
            ).run()
            return True, "feedback recorded", payload
        except Exception as err:
            return False, f"D1 feedback 写入失败: {err}", {}

    kv = get_kv_binding(env)
    if kv:
        try:
            key = "feedback:events"
            raw = await kv.get(key)
            events = json.loads(raw) if raw else []
            if not isinstance(events, list):
                events = []
            if not any(str(item.get("event_id")) == event_id for item in events if isinstance(item, dict)):
                events.append(payload)
                # Personal profile training log remains bounded in KV fallback.
                events = events[-5000:]
                await kv.put(key, json.dumps(events, ensure_ascii=False))
            return True, "feedback recorded", payload
        except Exception as err:
            return False, f"KV feedback 写入失败: {err}", {}

    return False, "Cloud Profile 未绑定 D1 或 KV，无法记录 feedback", {}


async def get_storage_status(env) -> dict:
    """直接探测持久化后端状态，不依赖边缘内存缓存。"""
    kv = get_kv_binding(env)
    status = {
        "success": True,
        "d1_bound": bool(hasattr(env, "DB")),
        "d1_ready": False,
        "d1_row_count": None,
        "d1_error": "",
        "kv_bound": bool(kv),
        "active_backend": "d1" if hasattr(env, "DB") else ("kv" if kv else "none"),
    }

    if hasattr(env, "DB"):
        try:
            stmt = env.DB.prepare("SELECT COUNT(*) AS total FROM tweets")
            res = await stmt.all()
            rows = res.results
            total = 0
            if rows:
                row = rows[0]
                if isinstance(row, dict):
                    total = int(row.get("total", 0) or 0)
                else:
                    total = int(getattr(row, "total", 0) or 0)
            status["d1_ready"] = True
            status["d1_row_count"] = total
            order = await _load_bookmark_order(env)
            status["bookmark_order_count"] = len(order)
            status["bookmark_head_ids"] = order[:10]
        except Exception as err:
            status["d1_error"] = str(err)

    return status


async def save_tweets(env, tweets: list[dict], refresh_existing: bool = False) -> tuple[bool, str, dict]:
    """批量持久化推文。

    Cloudflare Workers Free 每次 invocation 的 D1 查询数有限，因此严禁“一条推文一条 INSERT”。
    这里使用 json_each(?) 将一批记录在单条 SQL 中展开并 UPSERT。
    """
    kv = get_kv_binding(env)
    details = {
        "attempted": len(tweets),
        "d1_bound": bool(hasattr(env, "DB")),
        "d1_written": 0,
        "d1_row_count": None,
        "d1_error": "",
        "d1_queries": 0,
        "d1_existing_before": 0,
        "d1_new": 0,
        "d1_refreshed": 0,
        "d1_skipped_existing": 0,
        "order_changed": False,
        "kv_bound": bool(kv),
        "kv_written": 0,
        "kv_error": "",
        "backend": "",
        "pulled_head_ids": [str(t.get("id")) for t in tweets[:10]],
        "verified_head_ids": [],
        "missing_head_ids": [],
    }

    if not tweets:
        current = await get_storage_status(env)
        details["d1_row_count"] = current.get("d1_row_count")
        if current.get("active_backend") == "d1" and current.get("d1_ready"):
            details["backend"] = "d1"
            return True, "X 云端没有发现新书签；D1 主存储正常", details
        if current.get("active_backend") == "kv":
            details["backend"] = "kv"
            return True, "X 云端没有发现新书签；KV 主存储正常", details
        if current.get("active_backend") == "d1":
            return False, f"D1 已绑定但不可用: {current.get('d1_error') or 'unknown error'}", details
        return False, "Cloud Profile 未绑定 D1 或 KV，无法持久化", details

    saved_to_d1 = False
    saved_to_kv = False

    if hasattr(env, "DB"):
        bulk_sql = """
        INSERT INTO tweets (
            id, filename, category, sub_category, title, author, username, url, created_at,
            likes, retweets, views, has_media, media_type, images, videos, snippet,
            body_raw, body_html, avatar, classify_status
        )
        SELECT
            CAST(json_extract(value, '$.id') AS TEXT),
            json_extract(value, '$.filename'),
            json_extract(value, '$.category'),
            json_extract(value, '$.sub_category'),
            json_extract(value, '$.title'),
            json_extract(value, '$.author'),
            json_extract(value, '$.username'),
            json_extract(value, '$.url'),
            json_extract(value, '$.created_at'),
            COALESCE(json_extract(value, '$.likes'), 0),
            COALESCE(json_extract(value, '$.retweets'), 0),
            COALESCE(json_extract(value, '$.views'), 0),
            COALESCE(json_extract(value, '$.has_media'), 0),
            json_extract(value, '$.media_type'),
            json_extract(value, '$.images'),
            json_extract(value, '$.videos'),
            json_extract(value, '$.snippet'),
            json_extract(value, '$.body_raw'),
            json_extract(value, '$.body_html'),
            json_extract(value, '$.avatar'),
            json_extract(value, '$.classify_status')
        FROM json_each(?)
        WHERE 1
        ON CONFLICT(id) DO UPDATE SET
            filename = excluded.filename,
            title = excluded.title,
            author = excluded.author,
            username = excluded.username,
            url = excluded.url,
            created_at = excluded.created_at,
            likes = excluded.likes,
            retweets = excluded.retweets,
            views = excluded.views,
            has_media = excluded.has_media,
            media_type = excluded.media_type,
            images = excluded.images,
            videos = excluded.videos,
            snippet = excluded.snippet,
            body_raw = excluded.body_raw,
            body_html = excluded.body_html,
            avatar = excluded.avatar,
            category = CASE
                WHEN tweets.category IS NULL OR tweets.category = '' OR tweets.category = '未分类'
                    OR tweets.category = '00_云端实时书签'
                THEN excluded.category ELSE tweets.category END,
            sub_category = CASE
                WHEN tweets.sub_category IS NULL OR tweets.sub_category = ''
                    OR tweets.sub_category = '精选'
                THEN excluded.sub_category ELSE tweets.sub_category END,
            classify_status = COALESCE(tweets.classify_status, excluded.classify_status)
        """

        try:
            existing_ids = await get_known_tweet_ids(env)
            details["d1_queries"] += 1
            details["d1_existing_before"] = len(existing_ids)

            new_items = [
                item for item in tweets
                if str(item.get("id", "")) not in existing_ids
            ]
            write_items = tweets if refresh_existing else new_items
            details["d1_new"] = len(new_items)
            details["d1_refreshed"] = max(0, len(write_items) - len(new_items))
            details["d1_skipped_existing"] = len(tweets) - len(write_items)

            normalized = []
            for item in write_items:
                images = item.get("images") or []
                videos = item.get("videos") or []
                normalized.append({
                    "id": str(item["id"]),
                    "filename": item.get("filename") or f"twitter_{item.get('username', '')}_status_{item['id']}.md",
                    "category": item.get("category", "未分类"),
                    "sub_category": item.get("sub_category", "精选研读"),
                    "title": item.get("title", ""),
                    "author": item.get("author", ""),
                    "username": item.get("username", ""),
                    "url": item.get("url", ""),
                    "created_at": item.get("created_at", ""),
                    "likes": int(item.get("likes") or 0),
                    "retweets": int(item.get("retweets") or 0),
                    "views": int(item.get("views") or 0),
                    "has_media": int(bool(item.get("has_media") or images or videos)),
                    "media_type": item.get("media_type", "") or ("video" if videos else ("image" if images else "")),
                    "images": json.dumps(images, ensure_ascii=False),
                    "videos": json.dumps(videos, ensure_ascii=False),
                    "snippet": item.get("snippet", ""),
                    "body_raw": item.get("body_raw", ""),
                    "body_html": item.get("body_html", ""),
                    "avatar": item.get("avatar", "") or "",
                    "classify_status": item.get("classify_status", "projected") or "projected",
                })

            for chunk in _chunk_records(normalized):
                payload = json.dumps(chunk, ensure_ascii=False)
                await env.DB.prepare(bulk_sql).bind(payload).run()
                details["d1_queries"] += 1
                details["d1_written"] += len(chunk)

            # 确保历史部署也具备元数据表，然后保存“收藏流”顺序。
            await env.DB.prepare(
                "CREATE TABLE IF NOT EXISTS meta_kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            ).run()
            details["d1_queries"] += 1

            # 新一轮拉取的 ID 放最前，历史未出现在本轮窗口中的 ID 顺序保持不变。
            pulled_ids = [str(item.get("id")) for item in tweets if item.get("id")]
            old_order = await _load_bookmark_order(env)
            pulled_set = set(pulled_ids)
            merged_order = pulled_ids + [tweet_id for tweet_id in old_order if tweet_id not in pulled_set]

            if merged_order != old_order:
                await env.DB.prepare(
                    "INSERT INTO meta_kv (key, value, updated_at) VALUES (?, ?, datetime('now')) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at"
                ).bind(
                    "x_bookmark_order",
                    json.dumps(merged_order, ensure_ascii=False),
                ).run()
                details["d1_queries"] += 1
                details["order_changed"] = True

            count_res = await env.DB.prepare("SELECT COUNT(*) AS total FROM tweets").all()
            details["d1_queries"] += 1
            if count_res.results:
                details["d1_row_count"] = int(_row_get(count_res.results[0], "total", 0) or 0)

            head_ids = pulled_ids[:10]
            if head_ids:
                verify_res = await env.DB.prepare(
                    "SELECT id FROM tweets WHERE id IN (SELECT value FROM json_each(?))"
                ).bind(json.dumps(head_ids)).all()
                details["d1_queries"] += 1
                persisted = {str(_row_get(row, "id", "")) for row in verify_res.results}
                details["verified_head_ids"] = [tweet_id for tweet_id in head_ids if tweet_id in persisted]
                details["missing_head_ids"] = [tweet_id for tweet_id in head_ids if tweet_id not in persisted]

            saved_to_d1 = (
                details["d1_written"] == len(write_items)
                and details["d1_row_count"] is not None
                and not details["missing_head_ids"]
            )
        except Exception as db_err:
            details["d1_error"] = str(db_err)
            print("D1 批量保存写入异常:", details["d1_error"])

    # Storage Plan 是能力选择，不是双写：只有未绑定 D1 时才使用 KV。
    if kv and not hasattr(env, "DB"):
        try:
            existing_raw = await kv.get("tweets:all")
            existing_items = json.loads(existing_raw) if existing_raw else []
            if not isinstance(existing_items, list):
                existing_items = []
            existing_map = {
                str(item.get("id")): item
                for item in existing_items
                if isinstance(item, dict) and item.get("id")
            }

            pulled_ids = set()
            ordered = []
            for item in tweets:
                tweet_id = str(item.get("id", "") or "")
                if not tweet_id:
                    continue
                pulled_ids.add(tweet_id)
                old = existing_map.get(tweet_id)
                merged_item = dict(old or {})
                merged_item.update(item)
                if old:
                    for semantic_key in ("category", "sub_category", "classify_status"):
                        if old.get(semantic_key):
                            merged_item[semantic_key] = old[semantic_key]
                merged_item.setdefault("classify_status", "projected")
                ordered.append(merged_item)

            ordered.extend(
                item for item in existing_items
                if str(item.get("id", "") or "") not in pulled_ids
            )

            await kv.put("tweets:all", json.dumps(ordered, ensure_ascii=False))
            details["kv_written"] = len([
                item for item in tweets
                if str(item.get("id", "") or "") not in {
                    str(old.get("id")) for old in existing_items if isinstance(old, dict)
                }
            ])
            saved_to_kv = True
        except Exception as kv_err:
            details["kv_error"] = str(kv_err)
            print("KV 同步写入异常:", details["kv_error"])

    if saved_to_d1 or saved_to_kv:
        invalidate_cache()

    if saved_to_d1:
        details["backend"] = "d1"
        if refresh_existing:
            message = (
                f"D1 完整刷新 {details['d1_written']} 条"
                f"（新增 {details['d1_new']}，刷新已有 {details['d1_refreshed']}），"
                f"当前表内共 {details['d1_row_count']} 条"
            )
        else:
            message = (
                f"D1 新增写入 {details['d1_new']} 条，"
                f"跳过已有 {details['d1_skipped_existing']} 条，"
                f"当前表内共 {details['d1_row_count']} 条"
            )
        return True, message, details

    if saved_to_kv:
        details["backend"] = "kv"
        return True, f"KV 主存储已写入 {details['kv_written']} 条", details

    if details["d1_bound"] and details["d1_error"]:
        return False, f"D1 已被选为主存储，但写入失败: {details['d1_error']}", details
    if not details["d1_bound"] and not details["kv_bound"]:
        return False, "Worker 未绑定 D1(DB) 或 KV，无法持久化", details
    return False, "持久化后端写入未完成", details


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


async def save_sync_status(env, status: dict) -> dict:
    """将后台同步状态写入当前主存储，供 UI/运维读取。"""
    payload = dict(status)
    payload.setdefault("updated_at", _utc_now_iso())
    raw = json.dumps(payload, ensure_ascii=False)

    if hasattr(env, "DB"):
        try:
            await env.DB.prepare(
                "CREATE TABLE IF NOT EXISTS meta_kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            ).run()
            await env.DB.prepare(
                "INSERT INTO meta_kv (key, value, updated_at) VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at"
            ).bind("x_sync_status", raw).run()
            return payload
        except Exception as err:
            print("D1 同步状态写入异常:", str(err))
            return payload

    kv = get_kv_binding(env)
    if kv:
        try:
            await kv.put("meta:sync_status", raw)
        except Exception as err:
            print("KV 同步状态写入异常:", str(err))
    return payload


async def get_sync_status(env) -> dict:
    """读取最近一次后台/手动同步状态。"""
    if hasattr(env, "DB"):
        try:
            res = await env.DB.prepare(
                "SELECT value FROM meta_kv WHERE key = ?"
            ).bind("x_sync_status").all()
            if res.results:
                raw = _row_get(res.results[0], "value", "") or ""
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    parsed.setdefault("storage_profile", "d1")
                    return parsed
        except Exception:
            pass
        return {
            "success": True,
            "state": "never",
            "storage_profile": "d1",
            "message": "尚无同步运行记录",
        }

    kv = get_kv_binding(env)
    if kv:
        try:
            raw = await kv.get("meta:sync_status")
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    parsed.setdefault("storage_profile", "kv")
                    return parsed
        except Exception:
            pass
        return {
            "success": True,
            "state": "never",
            "storage_profile": "kv",
            "message": "尚无同步运行记录",
        }

    return {
        "success": False,
        "state": "unavailable",
        "storage_profile": "none",
        "message": "Cloud Profile 未绑定持久化后端",
    }


async def delete_tweet_from_storage(env, tweet_id: str):
    """删除当前主存储中的单条收藏。

    用于“网页点击移除”路径：先在 X DeleteBookmark 成功，再删除本地/云端镜像。
    D1 与 KV 是互斥主存储，不做双写。
    """
    tweet_id = str(tweet_id)

    if hasattr(env, "DB"):
        try:
            await env.DB.prepare("DELETE FROM tweets WHERE id = ?").bind(tweet_id).run()
            order = await _load_bookmark_order(env)
            if tweet_id in order:
                await _save_bookmark_order(env, [x for x in order if x != tweet_id])
            invalidate_cache()
            return True
        except Exception as err:
            print("D1 删除推文异常:", str(err))
            return False

    kv = get_kv_binding(env)
    if kv:
        try:
            raw = await kv.get("tweets:all")
            items = json.loads(raw) if raw else []
            if not isinstance(items, list):
                items = []
            filtered = [t for t in items if str(t.get("id")) != tweet_id]
            if len(filtered) != len(items):
                await kv.put("tweets:all", json.dumps(filtered, ensure_ascii=False))
            invalidate_cache()
            return True
        except Exception as err:
            print("KV 删除推文异常:", str(err))
            return False

    return False


async def reconcile_removed_bookmarks(env, authoritative_order: list[str]) -> dict:
    """用一次完整 X Bookmarks 快照对账“负事件”（X 端取消收藏）。

    只有调用方确认 full scan 已自然到达时间线末尾时才允许调用。
    authoritative_order 即 X 当前完整书签 ID 顺序。
    """
    authoritative_order = [str(x) for x in authoritative_order if x]
    authoritative_set = set(authoritative_order)
    result = {
        "removed_count": 0,
        "removed_ids": [],
        "backend": "d1" if hasattr(env, "DB") else ("kv" if get_kv_binding(env) else "none"),
    }

    if hasattr(env, "DB"):
        existing = await get_known_tweet_ids(env)
        removed = sorted(existing - authoritative_set)
        if removed:
            # ID payload 很小；json_each 保持一次/少量 SQL，而不是逐条 DELETE。
            for chunk in _chunk_records([{"id": x} for x in removed], max_bytes=200_000):
                ids = [item["id"] for item in chunk]
                await env.DB.prepare(
                    "DELETE FROM tweets WHERE id IN (SELECT value FROM json_each(?))"
                ).bind(json.dumps(ids)).run()
        await _save_bookmark_order(env, authoritative_order)
        result["removed_count"] = len(removed)
        result["removed_ids"] = removed[:50]
        invalidate_cache()
        return result

    kv = get_kv_binding(env)
    if kv:
        raw = await kv.get("tweets:all")
        items = json.loads(raw) if raw else []
        if not isinstance(items, list):
            items = []
        existing_map = {
            str(item.get("id")): item
            for item in items
            if isinstance(item, dict) and item.get("id")
        }
        removed = sorted(set(existing_map) - authoritative_set)
        reconciled = [
            existing_map[tweet_id]
            for tweet_id in authoritative_order
            if tweet_id in existing_map
        ]
        await kv.put("tweets:all", json.dumps(reconciled, ensure_ascii=False))
        result["removed_count"] = len(removed)
        result["removed_ids"] = removed[:50]
        invalidate_cache()
        return result

    return result


async def get_topology_status(env) -> dict:
    """计算当前推文知识库的拓扑分布与自适应重整化状态。"""
    total = 0
    projected = 0
    settled = 0
    cat_counts = {}

    if hasattr(env, "DB"):
        try:
            stmt = env.DB.prepare("SELECT category, classify_status FROM tweets")
            res = await stmt.all()
            for r in res.results:
                total += 1
                st = _row_get(r, "classify_status", "settled") or "settled"
                if st == "projected":
                    projected += 1
                else:
                    settled += 1
                c = _row_get(r, "category", "未分类")
                cat_counts[c] = cat_counts.get(c, 0) + 1
        except Exception as e:
            print("获取 D1 拓扑状态异常:", str(e))
    else:
        kv = get_kv_binding(env)
        if kv:
            try:
                raw = await kv.get("tweets:all")
                if raw:
                    items = json.loads(raw)
                    total = len(items)
                    for it in items:
                        st = it.get("classify_status", "settled")
                        if st == "projected":
                            projected += 1
                        else:
                            settled += 1
                        c = it.get("category", "未分类")
                        cat_counts[c] = cat_counts.get(c, 0) + 1
            except Exception as e:
                print("获取 KV 拓扑状态异常:", str(e))

    max_ratio = (max(cat_counts.values()) / total) if total > 0 and cat_counts else 0.0
    needs_renormalize = (
        projected >= CONFIG.renormalize_threshold
        or (projected >= 10 and max_ratio > CONFIG.max_cluster_ratio)
    )

    return {
        "success": True,
        "total_tweets": total,
        "projected_count": projected,
        "settled_count": settled,
        "needs_renormalize": needs_renormalize,
        "categories": cat_counts,
        "max_cluster_ratio": round(max_ratio, 3),
    }


async def renormalize_topology(env) -> tuple[bool, str]:
    """执行拓扑重整化：将所有暂存 (projected) 状态的推文固化为已稳定 (settled) 状态。"""
    if hasattr(env, "DB"):
        try:
            stmt = env.DB.prepare(
                "UPDATE tweets SET classify_status = 'settled' WHERE classify_status = 'projected' OR classify_status IS NULL"
            )
            await stmt.run()
            invalidate_cache()
            return True, "Cloudflare 边缘拓扑重整化已成功执行并固化至 D1 数据库！"
        except Exception as d1_rn_err:
            return False, f"D1 拓扑重整化异常: {str(d1_rn_err)}"

    kv = get_kv_binding(env)
    if kv:
        try:
            raw = await kv.get("tweets:all")
            if raw:
                items = json.loads(raw)
                for it in items:
                    it["classify_status"] = "settled"
                await kv.put("tweets:all", json.dumps(items, ensure_ascii=False))
                invalidate_cache()
                return True, "Cloudflare 边缘拓扑重整化已成功执行并固化至 KV 存储！"
        except Exception as kv_rn_err:
            return False, f"KV 拓扑重整化异常: {str(kv_rn_err)}"

    return False, "未探测到活跃存储后端"


async def batch_classify_pending(env, limit: int = 60) -> tuple[bool, str, list[dict]]:
    """批量对历史/未分类/暂存推文执行智能分类与专区归档。"""
    if not hasattr(env, "DB"):
        return False, "未绑定 Cloudflare D1 数据库", []

    try:
        existing_cats = await get_existing_categories(env)
        stmt = env.DB.prepare(f"""
            SELECT id, title, snippet, body_raw, category, sub_category 
            FROM tweets 
            WHERE category = '00_云端实时书签' OR category = '未分类' OR category LIKE '%书签%' OR sub_category IS NULL OR sub_category = '' OR sub_category = '精选'
            LIMIT {limit}
        """)
        db_res = await stmt.all()
        rows = db_res.results

        classified_items = []
        for r in rows:
            t_id = str(_row_get(r, "id", ""))
            t_title = _row_get(r, "title", "") or ""
            t_body = _row_get(r, "body_raw", "") or _row_get(r, "snippet", "") or ""

            cat, subcat = await ai_classify_tweet(t_body, t_title, existing_cats, env)
            if cat not in existing_cats:
                existing_cats.append(cat)

            up_stmt = env.DB.prepare("""
                UPDATE tweets 
                SET category = ?, sub_category = ?, classify_status = 'settled'
                WHERE id = ?
            """).bind(cat, subcat, t_id)
            await up_stmt.run()

            classified_items.append({
                "id": t_id,
                "title": t_title[:30],
                "category": cat,
                "sub_category": subcat,
            })

        if classified_items:
            invalidate_cache()

        return True, f"成功完成 {len(classified_items)} 篇推文智能分类并更新至各个专区！", classified_items
    except Exception as e:
        return False, f"批量分类异常: {str(e)}", []

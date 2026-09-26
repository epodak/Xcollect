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
from config_loader import CONFIG
from classifier import rule_classify_tweet, get_existing_categories, ai_classify_tweet

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


async def load_tweets(env, bypass_cache: bool = False) -> dict:
    """加载推文数据（级联读取：边缘内存 -> D1 数据库 -> KV 存储）。"""
    global _MEM_CACHE_TWEETS
    if _MEM_CACHE_TWEETS is not None and not bypass_cache:
        return _MEM_CACHE_TWEETS

    # 1. 优先读取 Cloudflare D1 数据库
    if hasattr(env, "DB"):
        try:
            stmt = env.DB.prepare("SELECT * FROM tweets ORDER BY likes DESC")
            db_res = await stmt.all()
            rows = db_res.results
            tweets_list = []
            for r in rows:
                body_val = getattr(r, "body_raw", "") or getattr(r, "snippet", "")
                title_val = getattr(r, "title", "")
                default_sub = rule_classify_tweet(body_val, title_val)[1]

                row_dict = {
                    "id": str(getattr(r, "id", "")),
                    "filename": getattr(r, "filename", ""),
                    "category": getattr(r, "category", "") or "未分类",
                    "sub_category": getattr(r, "sub_category", "") or default_sub,
                    "title": title_val,
                    "author": getattr(r, "author", ""),
                    "username": getattr(r, "username", ""),
                    "avatar": getattr(r, "avatar", "") or "",
                    "url": getattr(r, "url", ""),
                    "created_at": getattr(r, "created_at", ""),
                    "likes": int(getattr(r, "likes", 0) or 0),
                    "retweets": int(getattr(r, "retweets", 0) or 0),
                    "views": int(getattr(r, "views", 0) or 0),
                    "has_media": bool(getattr(r, "has_media", 0)),
                    "media_type": getattr(r, "media_type", ""),
                    "images": json.loads(getattr(r, "images", "[]") or "[]")
                    if isinstance(getattr(r, "images", None), str)
                    else [],
                    "videos": json.loads(getattr(r, "videos", "[]") or "[]")
                    if isinstance(getattr(r, "videos", None), str)
                    else [],
                    "snippet": getattr(r, "snippet", ""),
                    "body_raw": getattr(r, "body_raw", ""),
                    "body_html": getattr(r, "body_html", ""),
                    "classify_status": getattr(r, "classify_status", "settled") or "settled",
                }
                tweets_list.append(row_dict)

            _MEM_CACHE_TWEETS = {
                "success": True,
                "source": "Cloudflare D1 (Edge Cached)",
                "total": len(tweets_list),
                "data": tweets_list,
            }
            return _MEM_CACHE_TWEETS
        except Exception as d1_err:
            print("从 D1 读取异常:", str(d1_err))

    # 2. 降级读取 Cloudflare KV 存储
    kv = get_kv_binding(env)
    if kv:
        try:
            raw_kv = await kv.get("tweets:all")
            if raw_kv:
                kv_tweets = json.loads(raw_kv)
                _MEM_CACHE_TWEETS = {
                    "success": True,
                    "source": "Cloudflare KV",
                    "total": len(kv_tweets),
                    "data": kv_tweets,
                }
                return _MEM_CACHE_TWEETS
        except Exception as kv_err:
            print("从 KV 读取异常:", str(kv_err))

    return {
        "success": False,
        "message": "数据库与KV暂无推文数据，请点击右上角【从 X 同步】开始拉取！",
        "data": [],
    }


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
        except Exception as err:
            status["d1_error"] = str(err)

    return status


async def save_tweets(env, tweets: list[dict]) -> tuple[bool, str, dict]:
    """批量持久化推文，并返回可审计的 D1/KV 写入统计。"""
    kv = get_kv_binding(env)
    details = {
        "attempted": len(tweets),
        "d1_bound": bool(hasattr(env, "DB")),
        "d1_written": 0,
        "d1_row_count": None,
        "d1_error": "",
        "kv_bound": bool(kv),
        "kv_written": 0,
        "kv_error": "",
        "backend": "",
    }

    if not tweets:
        current = await get_storage_status(env)
        details["d1_row_count"] = current.get("d1_row_count")
        details["backend"] = "d1" if current.get("d1_ready") else ("kv" if details["kv_bound"] else "")
        return True, "X 云端没有返回待保存数据", details

    saved_to_d1 = False
    saved_to_kv = False

    if hasattr(env, "DB"):
        sql_full = """
        INSERT INTO tweets (
            id, filename, category, sub_category, title, author, username, url, created_at,
            likes, retweets, views, has_media, media_type, images, videos, snippet, body_raw, body_html, avatar, classify_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        sql_no_status = """
        INSERT OR REPLACE INTO tweets (
            id, filename, category, sub_category, title, author, username, url, created_at,
            likes, retweets, views, has_media, media_type, images, videos, snippet, body_raw, body_html, avatar
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        sql_legacy = """
        INSERT OR REPLACE INTO tweets (
            id, filename, category, sub_category, title, author, username, url, created_at,
            likes, retweets, views, has_media, media_type, images, videos, snippet, body_raw, body_html
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        try:
            for item in tweets:
                images = item.get("images") or []
                videos = item.get("videos") or []
                has_media = int(bool(item.get("has_media") or images or videos))
                media_type = item.get("media_type", "") or (
                    "video" if videos else ("image" if images else "")
                )
                base_args = [
                    str(item["id"]),
                    item.get("filename") or f"twitter_{item.get('username', '')}_status_{item['id']}.md",
                    item.get("category", "未分类"),
                    item.get("sub_category", "精选研读"),
                    item.get("title", ""),
                    item.get("author", ""),
                    item.get("username", ""),
                    item.get("url", ""),
                    item.get("created_at", ""),
                    int(item.get("likes") or 0),
                    int(item.get("retweets") or 0),
                    int(item.get("views") or 0),
                    has_media,
                    media_type,
                    json.dumps(images, ensure_ascii=False),
                    json.dumps(videos, ensure_ascii=False),
                    item.get("snippet", ""),
                    item.get("body_raw", ""),
                    item.get("body_html", ""),
                ]
                avatar_val = item.get("avatar", "") or ""
                status_val = item.get("classify_status", "projected") or "projected"

                try:
                    stmt = env.DB.prepare(sql_full).bind(*(base_args + [avatar_val, status_val]))
                    await stmt.run()
                except Exception as col_err:
                    err_str = str(col_err).lower()
                    if "classify_status" in err_str:
                        try:
                            stmt = env.DB.prepare(sql_no_status).bind(*(base_args + [avatar_val]))
                            await stmt.run()
                        except Exception:
                            stmt = env.DB.prepare(sql_legacy).bind(*base_args)
                            await stmt.run()
                    elif "avatar" in err_str:
                        stmt = env.DB.prepare(sql_legacy).bind(*base_args)
                        await stmt.run()
                    else:
                        raise

                details["d1_written"] += 1

            count_stmt = env.DB.prepare("SELECT COUNT(*) AS total FROM tweets")
            count_res = await count_stmt.all()
            count_rows = count_res.results
            if count_rows:
                row = count_rows[0]
                if isinstance(row, dict):
                    details["d1_row_count"] = int(row.get("total", 0) or 0)
                else:
                    details["d1_row_count"] = int(getattr(row, "total", 0) or 0)

            # “D1 已确认”要求写入条数完整且 COUNT(*) read-back 成功。
            saved_to_d1 = (
                details["d1_written"] == len(tweets)
                and details["d1_row_count"] is not None
            )
        except Exception as db_err:
            details["d1_error"] = str(db_err)
            print("D1 批量保存写入异常:", details["d1_error"])

    if kv:
        try:
            existing_raw = await kv.get("tweets:all")
            existing_items = json.loads(existing_raw) if existing_raw else []
            id_map = {str(t.get("id")): t for t in existing_items}
            for item in tweets:
                item_copy = dict(item)
                item_copy.setdefault("classify_status", "projected")
                id_map[str(item_copy.get("id"))] = item_copy
            merged = list(id_map.values())
            await kv.put("tweets:all", json.dumps(merged, ensure_ascii=False))
            details["kv_written"] = len(tweets)
            saved_to_kv = True
        except Exception as kv_err:
            details["kv_error"] = str(kv_err)
            print("KV 同步写入异常:", details["kv_error"])

    if saved_to_d1 or saved_to_kv:
        invalidate_cache()

    if saved_to_d1:
        details["backend"] = "d1"
        return (
            True,
            f"D1 已确认写入 {details['d1_written']} 条，当前表内共 {details['d1_row_count']} 条",
            details,
        )

    if saved_to_kv:
        details["backend"] = "kv"
        prefix = ""
        if details["d1_bound"] and details["d1_error"]:
            prefix = f"D1 写入失败 ({details['d1_error']})，"
        return True, prefix + f"已降级写入 KV {details['kv_written']} 条", details

    if details["d1_bound"] and details["d1_error"]:
        return False, f"D1 写入失败: {details['d1_error']}", details
    if not details["d1_bound"] and not details["kv_bound"]:
        return False, "Worker 未绑定 D1(DB) 或 KV，无法持久化", details
    return False, "持久化后端写入未完成", details


async def delete_tweet_from_storage(env, tweet_id: str):
    """从 D1 数据库与 KV 存储中同步删除推文记录。"""
    # 1. 从 D1 删除
    if hasattr(env, "DB"):
        try:
            stmt = env.DB.prepare("DELETE FROM tweets WHERE id = ?").bind(str(tweet_id))
            await stmt.run()
        except Exception as d_err:
            print("D1 删除推文同步异常:", str(d_err))

    # 2. 从 KV 删除
    kv = get_kv_binding(env)
    if kv:
        try:
            raw = await kv.get("tweets:all")
            if raw:
                items = json.loads(raw)
                filtered = [t for t in items if str(t.get("id")) != str(tweet_id)]
                if len(filtered) != len(items):
                    await kv.put("tweets:all", json.dumps(filtered, ensure_ascii=False))
        except Exception as k_err:
            print("KV 删除推文同步异常:", str(k_err))

    invalidate_cache()


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
                st = getattr(r, "classify_status", "settled") or "settled"
                if st == "projected":
                    projected += 1
                else:
                    settled += 1
                c = getattr(r, "category", "未分类")
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
            t_id = str(getattr(r, "id", ""))
            t_title = getattr(r, "title", "") or ""
            t_body = getattr(r, "body_raw", "") or getattr(r, "snippet", "") or ""

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

# -*- coding: utf-8 -*-
"""Twitter / X API 交互客户端模块。

职责：
1. X 用户头像与媒体字段结构化提取
2. X Bookmark API 添加 / 删除
3. Bookmarks GraphQL queryId 动态解析与 fallback
4. 游标连续翻页抓取
5. 同步阶段只做零网络开销的规则投影，AI 深分类交给独立批处理端点
"""

import json
import urllib.parse

from config_loader import CONFIG
from classifier import rule_classify_tweet

try:
    from js import Headers, Object as JsObject, fetch as js_fetch
except ImportError:
    Headers = None
    JsObject = None
    js_fetch = None

TWITTER_BEARER = CONFIG.twitter_bearer
QUERY_ID_CREATE = CONFIG.query_id_create
QUERY_ID_DELETE = CONFIG.query_id_delete
_BOOKMARK_QUERY_IDS_CACHE = None

BOOKMARK_FEATURES = {
    "graphql_timeline_v2_bookmark_timeline": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "articles_preview_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

BOOKMARK_FIELD_TOGGLES = {
    "withArticleRichContentState": True,
    "withArticlePlainText": True,
}


def normalize_avatar_url(url: str) -> str:
    if not url:
        return ""
    for suffix in ("_normal", "_bigger", "_mini", "_reasonably_small"):
        if suffix in url:
            return url.replace(suffix, "_400x400")
    return url


def _unwrap_user_result(user_result: dict) -> dict:
    if not isinstance(user_result, dict):
        return {}
    if user_result.get("__typename") == "UserWithVisibilityResults":
        return user_result.get("user", {}) or {}
    return user_result


def _unwrap_tweet_result(tweet_result: dict) -> dict:
    if not isinstance(tweet_result, dict):
        return {}
    if tweet_result.get("__typename") == "TweetWithVisibilityResults":
        return tweet_result.get("tweet", {}) or {}
    if isinstance(tweet_result.get("tweet"), dict):
        return tweet_result.get("tweet", {}) or {}
    return tweet_result


def extract_avatar(user_result: dict) -> str:
    user_result = _unwrap_user_result(user_result)
    url = user_result.get("avatar", {}).get("image_url", "")
    if not url:
        url = user_result.get("legacy", {}).get("profile_image_url_https", "")
    return normalize_avatar_url(url)


def build_x_headers(auth_token: str, ct0: str):
    if Headers is None:
        return None
    h = Headers.new()
    h.set("authorization", TWITTER_BEARER)
    h.set("x-csrf-token", ct0)
    h.set("x-twitter-active-user", "yes")
    h.set("x-twitter-auth-type", "OAuth2Session")
    h.set("x-twitter-client-language", "en")
    h.set("accept", "*/*")
    h.set("accept-language", "en-US,en;q=0.9")
    h.set("content-type", "application/json")
    h.set("referer", "https://x.com/i/bookmarks")
    h.set("user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")
    h.set("cookie", f"auth_token={auth_token}; ct0={ct0};")
    return h


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


async def resolve_bookmark_query_ids() -> list[str]:
    """优先动态解析 Bookmarks queryId，失败时使用 config.toml fallback。"""
    global _BOOKMARK_QUERY_IDS_CACHE
    if _BOOKMARK_QUERY_IDS_CACHE:
        return list(_BOOKMARK_QUERY_IDS_CACHE)

    candidates = []
    registry_url = getattr(CONFIG, "query_id_registry_url", "") or ""
    if registry_url and js_fetch is not None:
        try:
            resp = await js_fetch(registry_url)
            if int(getattr(resp, "status", 200) or 200) == 200:
                payload = json.loads(await resp.text())
                operation = payload.get("Bookmarks", {}) if isinstance(payload, dict) else {}
                registry_id = operation.get("queryId", "") if isinstance(operation, dict) else ""
                if registry_id:
                    candidates.append(registry_id)
        except Exception as err:
            print("Bookmarks queryId registry 解析失败，使用本地 fallback:", str(err))

    candidates.append(getattr(CONFIG, "query_id_bookmarks", "") or "")
    candidates.extend(getattr(CONFIG, "query_id_bookmarks_fallbacks", []) or [])
    _BOOKMARK_QUERY_IDS_CACHE = _dedupe(candidates)
    return list(_BOOKMARK_QUERY_IDS_CACHE)


def _build_bookmarks_url(query_id: str, cursor=None) -> str:
    variables = {"count": 50, "includePromotedContent": False}
    if cursor:
        variables["cursor"] = cursor
    params = {
        "variables": json.dumps(variables, separators=(",", ":")),
        "features": json.dumps(BOOKMARK_FEATURES, separators=(",", ":")),
        "fieldToggles": json.dumps(BOOKMARK_FIELD_TOGGLES, separators=(",", ":")),
    }
    return f"https://x.com/i/api/graphql/{query_id}/Bookmarks?" + urllib.parse.urlencode(params)


def _extract_timeline(raw_data: dict):
    data = raw_data.get("data", {}) if isinstance(raw_data, dict) else {}
    v2 = data.get("bookmark_timeline_v2")
    if isinstance(v2, dict) and isinstance(v2.get("timeline"), dict):
        return v2.get("timeline")
    legacy = data.get("bookmark_timeline")
    if isinstance(legacy, dict) and isinstance(legacy.get("timeline"), dict):
        return legacy.get("timeline")
    return None


def _extract_media(legacy: dict):
    images = []
    videos = []
    for media in ((legacy.get("extended_entities", {}) or {}).get("media", []) or []):
        media_type = media.get("type", "")
        if media_type == "photo" and media.get("media_url_https"):
            images.append(media["media_url_https"])
        elif media_type in ("video", "animated_gif"):
            variants = (media.get("video_info", {}) or {}).get("variants", []) or []
            mp4s = [v for v in variants if v.get("content_type") == "video/mp4" and v.get("url")]
            mp4s.sort(key=lambda v: int(v.get("bitrate", 0) or 0), reverse=True)
            if mp4s:
                videos.append({"url": mp4s[0]["url"], "poster": media.get("media_url_https", ""), "type": media_type})
    return images, videos


async def call_x_bookmark_api(tweet_id: str, action: str, auth_token: str, ct0: str) -> tuple[bool, str]:
    if js_fetch is None:
        return False, "当前运行环境不支持 js_fetch"
    query_id = QUERY_ID_CREATE if action == "create" else QUERY_ID_DELETE
    endpoint = "CreateBookmark" if action == "create" else "DeleteBookmark"
    x_url = f"https://x.com/i/api/graphql/{query_id}/{endpoint}"
    init = JsObject.new()
    init.method = "POST"
    init.headers = build_x_headers(auth_token, ct0)
    init.body = json.dumps({"variables": {"tweet_id": str(tweet_id)}})
    x_resp = await js_fetch(x_url, init)
    status = int(getattr(x_resp, "status", 0) or 0)
    res_text = await x_resp.text()
    try:
        res_data = json.loads(res_text)
    except Exception:
        return False, f"X {endpoint} 返回非 JSON (HTTP {status}): {res_text[:180]}"
    if status not in (200, 201):
        return False, f"X {endpoint} HTTP {status}: {res_text[:180]}"
    if "errors" in res_data:
        return False, res_data["errors"][0].get("message", "X API error")
    return True, f"成功从 X 云端同步: {endpoint}"


async def fetch_remote_bookmarks(
    auth_token: str,
    ct0: str,
    max_pages: int,
    existing_cats: list[str],
    env,
    known_ids: set[str] | None = None,
    full_scan: bool = False,
):
    """游标连续翻页拉取书签；同步阶段不执行逐条远程 AI 调用。"""
    if js_fetch is None:
        raise RuntimeError("当前 Worker 运行环境不支持 js_fetch")

    known_ids = known_ids or set()
    query_ids = await resolve_bookmark_query_ids()
    if not query_ids:
        raise RuntimeError("没有可用的 Bookmarks GraphQL queryId")

    cursor = None
    pulled = []
    seen_ids = set()
    selected_query_id = None
    pages_fetched = 0
    query_failures = []
    discovered_new_count = 0
    stopped_on_known_page = False
    reached_timeline_end = False

    for _page in range(max_pages):
        timeline = None
        candidate_ids = [selected_query_id] if selected_query_id else query_ids

        for query_id in candidate_ids:
            if not query_id:
                continue
            init = JsObject.new()
            init.method = "GET"
            init.headers = build_x_headers(auth_token, ct0)
            resp = await js_fetch(_build_bookmarks_url(query_id, cursor), init)
            status = int(getattr(resp, "status", 0) or 0)
            raw_text = await resp.text()

            if status in (401, 403):
                raise RuntimeError(
                    f"X 凭证失效、CSRF 不匹配或服务端拒绝请求 (HTTP {status})。"
                    "请重新从 x.com 获取 auth_token 与 ct0，并确认二者来自同一登录会话。"
                )
            if status not in (200, 201):
                query_failures.append(f"{query_id}: HTTP {status} {raw_text[:120]}")
                continue
            try:
                raw_data = json.loads(raw_text)
            except Exception:
                query_failures.append(f"{query_id}: 非 JSON 响应 {raw_text[:120]}")
                continue
            if raw_data.get("errors"):
                query_failures.append(f"{query_id}: {raw_data['errors'][0].get('message', 'GraphQL error')}")
                continue
            timeline = _extract_timeline(raw_data)
            if timeline is None:
                query_failures.append(f"{query_id}: 响应缺少 bookmark_timeline")
                continue
            selected_query_id = query_id
            break

        if timeline is None and selected_query_id is not None:
            failed_id = selected_query_id
            selected_query_id = None
            for query_id in [qid for qid in query_ids if qid != failed_id]:
                init = JsObject.new()
                init.method = "GET"
                init.headers = build_x_headers(auth_token, ct0)
                resp = await js_fetch(_build_bookmarks_url(query_id, cursor), init)
                status = int(getattr(resp, "status", 0) or 0)
                raw_text = await resp.text()
                if status in (401, 403):
                    raise RuntimeError(f"X 凭证失效或请求被拒绝 (HTTP {status})")
                if status not in (200, 201):
                    query_failures.append(f"{query_id}: HTTP {status}")
                    continue
                try:
                    raw_data = json.loads(raw_text)
                except Exception:
                    continue
                candidate_timeline = _extract_timeline(raw_data)
                if candidate_timeline is not None and not raw_data.get("errors"):
                    selected_query_id = query_id
                    timeline = candidate_timeline
                    break

        if timeline is None:
            detail = " | ".join(query_failures[-4:]) or "无可用响应"
            raise RuntimeError("X Bookmarks GraphQL 协议不可用；可能是 queryId 已轮换或请求特征发生变化。最后诊断: " + detail)

        pages_fetched += 1
        page_new_count = 0
        page_unknown_count = 0
        next_cursor = None

        for ins in timeline.get("instructions", []) or []:
            entries = ins.get("entries", []) or []
            if not entries and isinstance(ins.get("entry"), dict):
                entries = [ins["entry"]]
            for entry in entries:
                eid = entry.get("entryId", "")
                content = entry.get("content", {}) or {}
                if "cursor-bottom" in eid or content.get("cursorType") == "Bottom":
                    next_cursor = content.get("value") or (content.get("itemContent", {}) or {}).get("value")
                if "tweet" not in eid:
                    continue

                item_content = content.get("itemContent", {}) or {}
                t_res = _unwrap_tweet_result((item_content.get("tweet_results", {}) or {}).get("result", {}) or {})
                rest_id = str(t_res.get("rest_id", "") or "")
                if not rest_id or rest_id in seen_ids:
                    continue

                seen_ids.add(rest_id)
                page_new_count += 1
                if rest_id not in known_ids:
                    page_unknown_count += 1
                    discovered_new_count += 1
                legacy = t_res.get("legacy", {}) or {}
                user_res = _unwrap_user_result((t_res.get("core", {}) or {}).get("user_results", {}).get("result", {}) or {})
                user_core = user_res.get("core", {}) or {}
                avatar_url = extract_avatar(user_res)
                name = user_core.get("name", "")
                s_name = user_core.get("screen_name", "")
                text = legacy.get("full_text", "") or ""
                created_at = legacy.get("created_at", "")
                likes = int(legacy.get("favorite_count", 0) or 0)
                retweets = int(legacy.get("retweet_count", 0) or 0)
                views = int((t_res.get("views", {}) or {}).get("count", 0) or 0)
                images, videos = _extract_media(legacy)
                snippet = text.replace("\n", " ").strip()[:140]
                first_line = text.splitlines()[0] if text else "推文"
                title = first_line[:45] + ("..." if len(first_line) > 45 else "")
                cat, subcat = rule_classify_tweet(text, title)

                pulled.append({
                    "id": rest_id,
                    "author": name or s_name,
                    "username": s_name,
                    "avatar": avatar_url,
                    "title": title,
                    "snippet": snippet,
                    "likes": likes,
                    "retweets": retweets,
                    "views": views,
                    "category": cat,
                    "sub_category": subcat,
                    "body_raw": text,
                    "url": f"https://x.com/{s_name}/status/{rest_id}",
                    "created_at": created_at,
                    # X timeline 的 sortIndex 表达“在收藏流里的位置”，而不是推文发布时间。
                    # 新收藏旧推文时，created_at 无法代表收藏顺序，因此必须把这个信号保留下来。
                    "bookmark_sort_index": str(entry.get("sortIndex", "") or ""),
                    "has_media": bool(images or videos),
                    "media_type": "video" if videos else ("image" if images else ""),
                    "images": images,
                    "videos": videos,
                    "classify_status": "projected",
                })

        # 增量模式只关心“新增正事件”：遇到整页已知数据即可停止。
        # full_scan 用于 reconciliation，必须继续翻到时间线自然结束，才能安全判断删除。
        if not full_scan and known_ids and page_unknown_count == 0:
            stopped_on_known_page = True
            break
        if not next_cursor or next_cursor == cursor or page_new_count == 0:
            reached_timeline_end = True
            break
        cursor = next_cursor

    # 按 X timeline sortIndex 统一重排，跨分页仍保持“最近收藏 → 更早收藏”的顺序。
    # Python int 可安全处理 X 的大整数 sortIndex。
    pulled.sort(
        key=lambda item: int(item.get("bookmark_sort_index") or 0),
        reverse=True,
    )

    return pulled, {
        "query_id": selected_query_id,
        "query_id_candidates": query_ids,
        "pages_fetched": pages_fetched,
        "pulled_count": len(pulled),
        "known_before_count": len(known_ids),
        "discovered_new_count": discovered_new_count,
        "scan_mode": "full" if full_scan else "incremental",
        "scan_complete": bool(reached_timeline_end),
        "stopped_on_known_page": bool(stopped_on_known_page),
        "truncated_by_max_pages": bool(full_scan and not reached_timeline_end),
        "classification": "rule_projection",
        "query_failures": query_failures[-4:],
    }

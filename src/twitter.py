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

try:
    from classifier import rule_classify_tweet
except ImportError:
    from src.classifier import rule_classify_tweet

try:
    from x_bookmark_protocol import (
        operation_name, query_id_candidates, mutation_payload, interpret_mutation_response,
    )
except ImportError:
    from src.x_bookmark_protocol import (
        operation_name, query_id_candidates, mutation_payload, interpret_mutation_response,
    )

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
_SEARCH_QUERY_IDS_CACHE = None
_SEARCH_FEATURES_CACHE = None
_SEARCH_METHOD_CACHE = None

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


def build_x_headers(auth_token: str, ct0: str, referer: str = "https://x.com/i/bookmarks"):
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
    h.set("referer", referer)
    h.set("origin", "https://x.com")
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


async def resolve_search_query_ids() -> list[str]:
    """Resolve SearchTimeline query IDs plus live feature/method metadata."""
    global _SEARCH_QUERY_IDS_CACHE, _SEARCH_FEATURES_CACHE, _SEARCH_METHOD_CACHE
    if _SEARCH_QUERY_IDS_CACHE:
        return list(_SEARCH_QUERY_IDS_CACHE)

    candidates = []
    registry_url = getattr(CONFIG, "query_id_registry_url", "") or ""
    if registry_url and js_fetch is not None:
        try:
            resp = await js_fetch(registry_url)
            if int(getattr(resp, "status", 200) or 200) == 200:
                payload = json.loads(await resp.text())
                operation = payload.get("SearchTimeline", {}) if isinstance(payload, dict) else {}
                registry_id = operation.get("queryId", "") if isinstance(operation, dict) else ""
                if registry_id:
                    candidates.append(registry_id)
                if isinstance(operation, dict):
                    registry_features = operation.get("features")
                    if isinstance(registry_features, dict) and registry_features:
                        _SEARCH_FEATURES_CACHE = registry_features
                    registry_method = str(operation.get("@method", "") or "").upper()
                    if registry_method in ("GET", "POST"):
                        _SEARCH_METHOD_CACHE = registry_method
        except Exception as err:
            print("SearchTimeline queryId registry 解析失败，使用本地 fallback:", str(err))

    candidates.append(getattr(CONFIG, "query_id_search", "") or "")
    candidates.extend(getattr(CONFIG, "query_id_search_fallbacks", []) or [])
    _SEARCH_QUERY_IDS_CACHE = _dedupe(candidates)
    return list(_SEARCH_QUERY_IDS_CACHE)


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


def _expand_x_urls(text: str, entity_set: dict | None) -> str:
    """把 t.co 占位符尽量还原为真实 URL，得到可长期保存的正文。"""
    text = str(text or "")
    if not text or not isinstance(entity_set, dict):
        return text
    for entity in entity_set.get("urls", []) or []:
        short = str(entity.get("url", "") or "")
        expanded = str(entity.get("expanded_url", "") or entity.get("display_url", "") or "")
        if short and expanded:
            text = text.replace(short, expanded)
    return text


def _normalize_article_entity_map(content_state: dict) -> dict:
    raw = content_state.get("entityMap", {}) or {}
    out = {}
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and entry.get("key") is not None:
                out[str(entry.get("key"))] = entry.get("value") or {}
    elif isinstance(raw, dict):
        for key, entry in raw.items():
            if isinstance(entry, dict) and "value" in entry:
                out[str(key)] = entry.get("value") or {}
            else:
                out[str(key)] = entry or {}
    return out


def _article_to_markdown(article_result: dict) -> tuple[str, str, list[str]]:
    """将 X Article 的 Draft.js content_state 归一化为可移植 Markdown。"""
    if not isinstance(article_result, dict):
        return "", "", []

    title = str(article_result.get("title", "") or "").strip()
    content_state = article_result.get("content_state", {}) or {}
    blocks = content_state.get("blocks", []) or []
    if not isinstance(blocks, list):
        blocks = []

    entity_by_key = _normalize_article_entity_map(content_state)
    media_url_by_id = {}
    raw_media = article_result.get("media_entities", {}) or {}
    media_iter = raw_media.values() if isinstance(raw_media, dict) else raw_media
    for media in media_iter or []:
        if not isinstance(media, dict):
            continue
        media_id = media.get("media_id")
        media_url = ((media.get("media_info", {}) or {}).get("original_img_url", "") or "")
        if media_id is not None and media_url:
            media_url_by_id[str(media_id)] = str(media_url)

    parts = []
    inline_images = []
    ordered_counter = 0
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type", "unstyled") or "unstyled")
        text = str(block.get("text", "") or "")

        if block_type == "atomic":
            ranges = block.get("entityRanges", []) or []
            entity_key = ranges[0].get("key") if ranges and isinstance(ranges[0], dict) else None
            entity = entity_by_key.get(str(entity_key), {}) if entity_key is not None else {}
            if isinstance(entity, dict) and entity.get("type") == "MEDIA":
                data = entity.get("data", {}) or {}
                media_items = data.get("mediaItems", []) or []
                media_id = media_items[0].get("mediaId") if media_items and isinstance(media_items[0], dict) else None
                image_url = media_url_by_id.get(str(media_id), "") if media_id is not None else ""
                if image_url:
                    caption = str(data.get("caption", "") or "Image").replace("]", "&#93;")
                    parts.append("![" + caption + "](" + image_url + ")")
                    inline_images.append(image_url)
            continue

        if not text:
            continue
        if block_type != "ordered-list-item":
            ordered_counter = 0

        if block_type == "header-one":
            parts.append("# " + text)
        elif block_type == "header-two":
            parts.append("## " + text)
        elif block_type == "header-three":
            parts.append("### " + text)
        elif block_type == "blockquote":
            parts.append("> " + text)
        elif block_type == "unordered-list-item":
            parts.append("- " + text)
        elif block_type == "ordered-list-item":
            ordered_counter += 1
            parts.append(str(ordered_counter) + ". " + text)
        elif block_type == "code-block":
            parts.append("    " + text.replace("\n", "\n    "))
        else:
            parts.append(text)

    body = "\n\n".join(parts).strip()
    if not body:
        body = str(article_result.get("plain_text", "") or article_result.get("content", "") or "").strip()
    return title, body, inline_images


def _extract_canonical_content(tweet_result: dict, legacy: dict) -> tuple[str, str, list[str]]:
    """统一正文：Article > Note Tweet > legacy.full_text。"""
    article_result = (
        (((tweet_result.get("article", {}) or {}).get("article_results", {}) or {}).get("result"))
        or (((legacy.get("article", {}) or {}).get("article_results", {}) or {}).get("result"))
        or ((tweet_result.get("article_results", {}) or {}).get("result"))
    )
    if isinstance(article_result, dict):
        article_title, article_body, article_images = _article_to_markdown(article_result)
        if article_body:
            return article_title, article_body, article_images

    note_result = ((((tweet_result.get("note_tweet", {}) or {}).get("note_tweet_results", {}) or {}).get("result")) or {})
    note_text = str(note_result.get("text", "") or "")
    if note_text:
        note_text = _expand_x_urls(note_text, note_result.get("entity_set", {}) or {})
        return "", note_text.strip(), []

    legacy_text = str(legacy.get("full_text", "") or "")
    legacy_text = _expand_x_urls(legacy_text, legacy.get("entities", {}) or {})
    return "", legacy_text.strip(), []


def _append_quoted_tweet(body: str, tweet_result: dict) -> str:
    """把引用推文折叠进 canonical document，避免阅读器丢上下文。"""
    quoted = _unwrap_tweet_result(((tweet_result.get("quoted_status_result", {}) or {}).get("result", {}) or {}))
    if not quoted:
        return body

    q_legacy = quoted.get("legacy", {}) or {}
    _, q_body, _ = _extract_canonical_content(quoted, q_legacy)
    if not q_body:
        return body

    q_user = _unwrap_user_result(((quoted.get("core", {}) or {}).get("user_results", {}) or {}).get("result", {}) or {})
    q_core = q_user.get("core", {}) or {}
    q_legacy_user = q_user.get("legacy", {}) or {}
    q_name = q_core.get("screen_name") or q_legacy_user.get("screen_name") or "unknown"
    quoted_md = "\n".join(("> " + line) if line else ">" for line in q_body.splitlines())
    return (body.rstrip() + "\n\n---\n\n> 引用 @" + str(q_name) + "\n>\n" + quoted_md).strip()


def normalize_tweet_result(
    tweet_result: dict,
    category_hint: str = "",
    sub_category_hint: str = "",
) -> dict:
    """Normalize one X GraphQL tweet result into Xcollect's canonical shape."""
    t_res = _unwrap_tweet_result(tweet_result)
    rest_id = str(t_res.get("rest_id", "") or "")
    if not rest_id:
        return {}

    legacy = t_res.get("legacy", {}) or {}
    user_res = _unwrap_user_result(
        ((t_res.get("core", {}) or {}).get("user_results", {}) or {}).get("result", {}) or {}
    )
    user_core = user_res.get("core", {}) or {}
    avatar_url = extract_avatar(user_res)
    name = user_core.get("name", "")
    s_name = user_core.get("screen_name", "")

    title_hint, text, article_images = _extract_canonical_content(t_res, legacy)
    text = _append_quoted_tweet(text, t_res)
    images, videos = _extract_media(legacy)
    for image_url in article_images:
        if image_url not in images:
            images.append(image_url)

    snippet = text.replace("\n", " ").strip()[:140]
    first_line = title_hint or (text.splitlines()[0] if text else "推文")
    title = first_line[:72] + ("..." if len(first_line) > 72 else "")

    if category_hint:
        cat = category_hint
        subcat = sub_category_hint or "精选研读"
    else:
        cat, subcat = rule_classify_tweet(text, title)

    return {
        "id": rest_id,
        "author": name or s_name,
        "username": s_name,
        "avatar": avatar_url,
        "title": title,
        "snippet": snippet,
        "likes": int(legacy.get("favorite_count", 0) or 0),
        "retweets": int(legacy.get("retweet_count", 0) or 0),
        "views": int((t_res.get("views", {}) or {}).get("count", 0) or 0),
        "category": cat,
        "sub_category": subcat,
        "body_raw": text,
        "url": f"https://x.com/{s_name}/status/{rest_id}" if s_name else f"https://x.com/i/status/{rest_id}",
        "created_at": legacy.get("created_at", ""),
        "lang": legacy.get("lang", ""),
        "possibly_sensitive": bool(legacy.get("possibly_sensitive", False)),
        # SearchTimeline 偶尔会漏过 -filter:replies；把 reply 关系显式标准化，
        # Discovery cheap gate 才能在源端查询失真时继续守住“候选必须可独立阅读”的边界。
        "is_reply": bool(
            legacy.get("in_reply_to_status_id_str")
            or legacy.get("in_reply_to_user_id_str")
            or legacy.get("in_reply_to_screen_name")
        ),
        "reply_to_username": str(legacy.get("in_reply_to_screen_name", "") or ""),
        "has_media": bool(images or videos),
        "media_type": "video" if videos else ("image" if images else ""),
        "images": images,
        "videos": videos,
        "classify_status": "projected",
    }


SEARCH_FEATURES = {
    key: value
    for key, value in BOOKMARK_FEATURES.items()
    if key != "graphql_timeline_v2_bookmark_timeline"
}
SEARCH_FIELD_TOGGLES = {
    "withArticleRichContentState": True,
    "withArticlePlainText": True,
}


def _extract_search_timeline(raw_data: dict):
    data = raw_data.get("data", {}) if isinstance(raw_data, dict) else {}
    search_root = data.get("search_by_raw_query") or data.get("search") or {}
    if isinstance(search_root, dict):
        search_timeline = search_root.get("search_timeline") or search_root.get("timeline") or {}
        if isinstance(search_timeline, dict):
            timeline = search_timeline.get("timeline")
            if isinstance(timeline, dict):
                return timeline
            if isinstance(search_timeline.get("instructions"), list):
                return search_timeline
    return None


def _walk_dicts(node, depth: int = 0):
    if depth > 10:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_dicts(value, depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_dicts(value, depth + 1)


def _extract_entry_tweets(entry: dict) -> list[dict]:
    results = []
    seen = set()
    for node in _walk_dicts(entry):
        container = node.get("tweet_results") if isinstance(node, dict) else None
        if not isinstance(container, dict):
            continue
        result = _unwrap_tweet_result(container.get("result", {}) or {})
        rest_id = str(result.get("rest_id", "") or "")
        if rest_id and rest_id not in seen:
            seen.add(rest_id)
            results.append(result)
    return results


def _extract_bottom_cursor(entry: dict) -> str:
    for node in _walk_dicts(entry):
        if not isinstance(node, dict):
            continue
        if node.get("cursorType") == "Bottom" and node.get("value"):
            return str(node.get("value"))
        entry_id = str(node.get("entryId", "") or "")
        if "cursor-bottom" in entry_id:
            content = node.get("content", {}) or {}
            if isinstance(content, dict):
                value = content.get("value") or (content.get("itemContent", {}) or {}).get("value")
                if value:
                    return str(value)
    return ""


async def fetch_search_timeline(
    auth_token: str,
    ct0: str,
    raw_query: str,
    count: int = 60,
    max_pages: int = 1,
    category_hint: str = "",
    sub_category_hint: str = "",
):
    """Fetch X SearchTimeline (Latest) using the authenticated web GraphQL surface.

    X rotates query IDs and has changed operation transport across builds.
    The adapter therefore resolves query IDs dynamically and tolerates both GET
    and POST SearchTimeline variants.
    """
    if js_fetch is None:
        raise RuntimeError("当前 Worker 运行环境不支持 js_fetch")

    query_ids = await resolve_search_query_ids()
    if not query_ids:
        raise RuntimeError("没有可用的 SearchTimeline GraphQL queryId")

    cursor = ""
    selected_query_id = None
    failures = []
    items = []
    seen = set()
    pages_fetched = 0

    for _page in range(max(1, int(max_pages))):
        timeline = None
        candidate_ids = [selected_query_id] if selected_query_id else query_ids

        for query_id in candidate_ids:
            if not query_id:
                continue

            variables = {
                "rawQuery": str(raw_query),
                "count": max(10, min(100, int(count))),
                "querySource": "typed_query",
                "product": "Latest",
            }
            if cursor:
                variables["cursor"] = cursor

            effective_features = _SEARCH_FEATURES_CACHE or SEARCH_FEATURES
            payload = {
                "variables": variables,
                "features": effective_features,
                "fieldToggles": SEARCH_FIELD_TOGGLES,
            }
            endpoint = f"https://x.com/i/api/graphql/{query_id}/SearchTimeline"
            referer = (
                "https://x.com/search?q="
                + urllib.parse.quote(str(raw_query))
                + "&f=live"
            )

            preferred_method = _SEARCH_METHOD_CACHE if _SEARCH_METHOD_CACHE in ("GET", "POST") else "GET"
            transport_attempts = (
                preferred_method,
                "POST" if preferred_method == "GET" else "GET",
            )
            for transport in transport_attempts:
                init = JsObject.new()
                init.method = transport
                init.headers = build_x_headers(
                    auth_token,
                    ct0,
                    referer=referer,
                )

                request_url = endpoint
                if transport == "GET":
                    request_url += "?" + urllib.parse.urlencode({
                        "variables": json.dumps(
                            variables,
                            separators=(",", ":"),
                        ),
                        "features": json.dumps(
                            effective_features,
                            separators=(",", ":"),
                        ),
                        "fieldToggles": json.dumps(
                            SEARCH_FIELD_TOGGLES,
                            separators=(",", ":"),
                        ),
                    })
                else:
                    init.body = json.dumps(
                        payload,
                        separators=(",", ":"),
                    )

                resp = await js_fetch(request_url, init)
                status = int(getattr(resp, "status", 0) or 0)
                raw_text = await resp.text()

                if status in (401, 403):
                    raise RuntimeError(
                        f"X SearchTimeline 凭证失效或请求被拒绝 (HTTP {status})"
                    )
                if status not in (200, 201):
                    failures.append(
                        f"{query_id}/{transport}: HTTP {status} {raw_text[:100]}"
                    )
                    continue
                try:
                    raw_data = json.loads(raw_text)
                except Exception:
                    failures.append(
                        f"{query_id}/{transport}: 非 JSON 响应"
                    )
                    continue
                if raw_data.get("errors"):
                    failures.append(
                        f"{query_id}/{transport}: "
                        f"{raw_data['errors'][0].get('message', 'GraphQL error')}"
                    )
                    continue

                timeline = _extract_search_timeline(raw_data)
                if timeline is None:
                    failures.append(
                        f"{query_id}/{transport}: 响应缺少 search_timeline"
                    )
                    continue

                selected_query_id = query_id
                break

            if timeline is not None:
                break

        if timeline is None:
            detail = " | ".join(failures[-4:]) or "无可用响应"
            raise RuntimeError(
                "X SearchTimeline GraphQL 协议不可用；queryId/请求特征可能已轮换。最后诊断: "
                + detail
            )

        pages_fetched += 1
        next_cursor = ""
        page_count = 0
        for instruction in timeline.get("instructions", []) or []:
            entries = instruction.get("entries", []) or []
            if not entries and isinstance(instruction.get("entry"), dict):
                entries = [instruction.get("entry")]
            for entry in entries:
                cursor_value = _extract_bottom_cursor(entry)
                if cursor_value:
                    next_cursor = cursor_value
                for result in _extract_entry_tweets(entry):
                    item = normalize_tweet_result(
                        result,
                        category_hint=category_hint,
                        sub_category_hint=sub_category_hint,
                    )
                    tweet_id = str(item.get("id", "") or "")
                    if not tweet_id or tweet_id in seen:
                        continue
                    seen.add(tweet_id)
                    page_count += 1
                    items.append(item)

        if not next_cursor or next_cursor == cursor or page_count == 0:
            break
        cursor = next_cursor

    return items, {
        "query": raw_query,
        "query_id": selected_query_id,
        "query_id_candidates": query_ids,
        "pages_fetched": pages_fetched,
        "pulled_count": len(items),
        "query_failures": failures[-4:],
    }


async def resolve_mutation_query_ids(action: str) -> list[str]:
    """Resolve actual operation ID, not the unrelated Bookmarks timeline ID.

    The registry is public and may lag X's own private client. Only use a
    validated operation/method/path; the checked-in fallback remains available.
    """
    operation_name(action)  # validate without falling through to DeleteBookmark
    fallback = QUERY_ID_CREATE if action == "create" else QUERY_ID_DELETE
    registry = None
    url = getattr(CONFIG, "query_id_registry_url", "") or ""
    if url and js_fetch is not None:
        try:
            response = await js_fetch(url)
            if int(getattr(response, "status", 0) or 0) == 200:
                registry = json.loads(await response.text())
        except Exception as error:
            # Do not expose private headers or fail a user action on registry outage.
            print("X bookmark operation registry unavailable:", str(error)[:120])
    return query_id_candidates(action, registry, fallback)


async def call_x_bookmark_api(tweet_id: str, action: str, auth_token: str, ct0: str) -> tuple[bool, str]:
    if js_fetch is None:
        return False, "当前运行环境不支持 js_fetch"
    try:
        operation = operation_name(action)
        query_ids = await resolve_mutation_query_ids(action)
    except ValueError as error:
        return False, str(error)
    if not query_ids:
        return False, f"X {operation}: 没有有效的 GraphQL queryId"

    for index, query_id in enumerate(query_ids):
        x_url = f"https://x.com/i/api/graphql/{query_id}/{operation}"
        try:
            body = mutation_payload(tweet_id, query_id)
        except ValueError as error:
            return False, str(error)

        init = JsObject.new()
        init.method = "POST"
        init.headers = build_x_headers(auth_token, ct0)
        init.body = body
        try:
            response = await js_fetch(x_url, init)
            status = int(getattr(response, "status", 0) or 0)
            raw = await response.text()
        except Exception as error:
            # Transport uncertainty: do not blindly retry a user mutation.
            return False, f"X {operation} 网络失败，操作结果未确认: {str(error)[:160]}"

        ok, message = interpret_mutation_response(action, status, raw, query_id)
        if ok:
            return True, message
        if status == 404 and index + 1 < len(query_ids):
            # Only a definite rejection can move to another known operation ID.
            continue
        return False, message

    return False, f"X {operation}: 所有已知操作 ID 均被 X 拒绝"


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
                created_at = legacy.get("created_at", "")
                likes = int(legacy.get("favorite_count", 0) or 0)
                retweets = int(legacy.get("retweet_count", 0) or 0)
                views = int((t_res.get("views", {}) or {}).get("count", 0) or 0)

                title_hint, text, article_images = _extract_canonical_content(t_res, legacy)
                text = _append_quoted_tweet(text, t_res)

                images, videos = _extract_media(legacy)
                for image_url in article_images:
                    if image_url not in images:
                        images.append(image_url)

                snippet = text.replace("\n", " ").strip()[:140]
                first_line = title_hint or (text.splitlines()[0] if text else "推文")
                title = first_line[:72] + ("..." if len(first_line) > 72 else "")
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

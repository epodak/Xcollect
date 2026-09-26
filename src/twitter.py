# -*- coding: utf-8 -*-
"""Twitter / X API 交互客户端模块。

职责：
1. X 用户头像高分辨率提取与转换
2. X Bookmark API 交互（添加书签 / 删除书签）
3. 游标深度翻页拉取远端书签时间线并实时结构化解析
"""

import json
import urllib.parse
from config_loader import CONFIG
from classifier import ai_classify_tweet

try:
    from js import Headers, Object as JsObject, fetch as js_fetch
except ImportError:
    Headers = None
    JsObject = None
    js_fetch = None

TWITTER_BEARER = CONFIG.twitter_bearer
QUERY_ID_BOOKMARKS = CONFIG.query_id_bookmarks
QUERY_ID_CREATE = CONFIG.query_id_create
QUERY_ID_DELETE = CONFIG.query_id_delete


def normalize_avatar_url(url: str) -> str:
    """将 X 返回的头像 URL 规范化为更高清的版本。

    X GraphQL 的 core.user_results.result.avatar.image_url 默认返回 _normal (48px)，
    直接把尺寸后缀替换为 _400x400 即可得到高清头像，且 pbs.twimg.com 无需鉴权即可公开访问。
    """
    if not url:
        return ""
    for suffix in ("_normal", "_bigger", "_mini", "_reasonably_small"):
        if suffix in url:
            return url.replace(suffix, "_400x400")
    return url


def extract_avatar(user_result: dict) -> str:
    """从 X GraphQL 的 user_results.result 中提取作者头像 URL（兼容多套字段结构）"""
    if not isinstance(user_result, dict):
        return ""
    url = user_result.get("avatar", {}).get("image_url", "")
    if not url:
        url = user_result.get("legacy", {}).get("profile_image_url_https", "")
    return normalize_avatar_url(url)


def build_x_headers(auth_token: str, ct0: str):
    """构建访问 X GraphQL API 所需的完整身份认证 Headers。"""
    if Headers is None:
        return None
    h = Headers.new()
    h.set("authorization", TWITTER_BEARER)
    h.set("x-csrf-token", ct0)
    h.set("x-twitter-active-user", "yes")
    h.set("x-twitter-auth-type", "OAuth2Session")
    h.set("content-type", "application/json")
    h.set(
        "user-agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    )
    h.set("cookie", f"auth_token={auth_token}; ct0={ct0};")
    return h


async def call_x_bookmark_api(tweet_id: str, action: str, auth_token: str, ct0: str) -> tuple[bool, str]:
    """调用 X 官方 GraphQL 接口添加或删除书签。"""
    if js_fetch is None:
        return False, "当前运行环境不支持 js_fetch"

    query_id = QUERY_ID_CREATE if action == "create" else QUERY_ID_DELETE
    endpoint = "CreateBookmark" if action == "create" else "DeleteBookmark"
    x_url = f"https://x.com/i/api/graphql/{query_id}/{endpoint}"

    h = build_x_headers(auth_token, ct0)
    init = JsObject.new()
    init.method = "POST"
    init.headers = h
    init.body = json.dumps({"variables": {"tweet_id": str(tweet_id)}})

    x_resp = await js_fetch(x_url, init)
    res_text = await x_resp.text()
    res_data = json.loads(res_text)

    if "errors" in res_data:
        err_msg = res_data["errors"][0].get("message", "X API error")
        return False, err_msg
    return True, f"成功从 X 云端同步: {endpoint}"


async def fetch_remote_bookmarks(auth_token: str, ct0: str, max_pages: int, existing_cats: list[str], env) -> list[dict]:
    """支持游标连续翻页深度拉取推特书签，并调用分类器完成标签分配。"""
    if js_fetch is None:
        return []

    features = {
        "rweb_video_screen_enabled": False,
        "rweb_cashtags_enabled": True,
        "profile_label_improvements_pcf_label_in_post_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
    }

    cursor = None
    pulled = []
    seen_ids = set()

    for page in range(max_pages):
        params_vars = {"count": 50, "includePromotedContent": False}
        if cursor:
            params_vars["cursor"] = cursor

        params = {
            "variables": json.dumps(params_vars),
            "features": json.dumps(features),
        }
        q_str = urllib.parse.urlencode(params)
        x_url = f"https://x.com/i/api/graphql/{QUERY_ID_BOOKMARKS}/Bookmarks?{q_str}"
        h = build_x_headers(auth_token, ct0)
        init = JsObject.new()
        init.method = "GET"
        init.headers = h

        resp = await js_fetch(x_url, init)
        raw_text = await resp.text()
        if getattr(resp, "status", 200) not in (200, 201):
            raise RuntimeError(f"X API 返回 HTTP {getattr(resp, 'status', 0)}: {raw_text[:200]}")
        raw_data = json.loads(raw_text)

        instructions = (
            raw_data.get("data", {})
            .get("bookmark_timeline_v2", {})
            .get("timeline", {})
            .get("instructions", [])
        )
        page_new_count = 0
        next_cursor = None

        for ins in instructions:
            if ins.get("type") == "TimelineAddEntries":
                for entry in ins.get("entries", []):
                    eid = entry.get("entryId", "")
                    content = entry.get("content", {})

                    # 提取底部翻页游标
                    if "cursor-bottom" in eid or content.get("cursorType") == "Bottom":
                        next_cursor = content.get("value") or content.get("itemContent", {}).get("value")

                    if "tweet" in eid:
                        t_res = content.get("itemContent", {}).get("tweet_results", {}).get("result", {})
                        if "tweet" in t_res:
                            t_res = t_res["tweet"]
                        rest_id = t_res.get("rest_id", "")
                        if rest_id and rest_id not in seen_ids:
                            seen_ids.add(rest_id)
                            page_new_count += 1

                            legacy = t_res.get("legacy", {})
                            user_res = t_res.get("core", {}).get("user_results", {}).get("result", {})
                            user_core = user_res.get("core", {})
                            avatar_url = extract_avatar(user_res)
                            name = user_core.get("name", "")
                            s_name = user_core.get("screen_name", "")
                            text = legacy.get("full_text", "")
                            created_at = legacy.get("created_at", "")
                            likes = legacy.get("favorite_count", 0)
                            retweets = legacy.get("retweet_count", 0)
                            views = int(t_res.get("views", {}).get("count", 0) or 0)
                            snippet = text.replace("\n", " ")[:140]
                            title = text.splitlines()[0][:45] if text else "推文"
                            url_t = f"https://x.com/{s_name}/status/{rest_id}"

                            cat, subcat = await ai_classify_tweet(text, title, existing_cats, env)
                            if cat not in existing_cats:
                                existing_cats.append(cat)

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
                                "url": url_t,
                                "created_at": created_at,
                                "classify_status": "projected",
                            })

        # 翻页终止判定：无下游标、游标未前进、或本页无新推文
        if not next_cursor or next_cursor == cursor or page_new_count == 0:
            break
        cursor = next_cursor

    return pulled

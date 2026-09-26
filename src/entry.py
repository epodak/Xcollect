# -*- coding: utf-8 -*-
"""Cloudflare Python Worker 边缘统一路由与分发中枢。"""

import json
import urllib.parse

from config_loader import CONFIG
from classifier import get_existing_categories
from twitter import call_x_bookmark_api, fetch_remote_bookmarks
from storage import (
    json_resp,
    load_tweets,
    save_tweets,
    delete_tweet_from_storage,
    get_storage_status,
    get_topology_status,
    renormalize_topology,
    batch_classify_pending,
)

try:
    from js import Response, Object as JsObject
except ImportError:
    Response = None
    JsObject = None


async def on_fetch(request, env):
    """Worker 边缘请求处理入口。"""
    try:
        url = urllib.parse.urlparse(request.url)
        path = url.path
        method = request.method.upper()
        query = urllib.parse.parse_qs(url.query)

        if path == "/api/auth/status":
            auth_token = getattr(env, "X_AUTH_TOKEN", "") or ""
            ct0 = getattr(env, "X_CT0", "") or ""
            return json_resp({
                "configured": bool(auth_token and ct0),
                "has_auth_token": bool(auth_token),
                "has_ct0": bool(ct0),
                "runtime": "Cloudflare Python Worker (Modularized)",
                "runtime_write_supported": False,
                "credentials_source": "Cloudflare Worker Secret",
            })

        # Worker Secret 不能通过业务 HTTP 请求在运行时持久化。
        # 旧实现返回 success=True 却没有保存任何东西，会制造“网页保存成功”的假象。
        if path == "/api/auth/save" and method == "POST":
            return json_resp({
                "success": False,
                "error": (
                    "Cloudflare Worker 生产环境不能从网页写入 X 凭证。"
                    "请在 Cloudflare Worker Secrets 中配置 X_AUTH_TOKEN 与 X_CT0，"
                    "或使用 wrangler secret put。"
                ),
                "runtime_write_supported": False,
            }, 409)

        if path == "/api/storage/status":
            return json_resp(await get_storage_status(env))

        if path == "/api/bookmark/toggle" and method == "POST":
            body_text = await request.text()
            try:
                data = json.loads(body_text)
            except Exception:
                return json_resp({"success": False, "error": "Invalid JSON"}, 400)

            tweet_id = str(data.get("tweet_id", ""))
            action = data.get("action", "delete")
            auth_token = getattr(env, "X_AUTH_TOKEN", "") or ""
            ct0 = getattr(env, "X_CT0", "") or ""

            if not auth_token or not ct0:
                return json_resp({
                    "success": False,
                    "error": "Worker Secret 未配置 X_AUTH_TOKEN 或 X_CT0",
                }, 400)

            ok, msg = await call_x_bookmark_api(tweet_id, action, auth_token, ct0)
            if not ok:
                return json_resp({"success": False, "message": msg}, 400)

            if action == "delete":
                await delete_tweet_from_storage(env, tweet_id)

            return json_resp({
                "success": True,
                "message": msg,
                "action": action,
                "tweet_id": tweet_id,
            })

        # 保留 GET 兼容旧前端；新前端用 POST，因为同步会产生远端读取与本地写入副作用。
        if path == "/api/bookmarks/sync" and method in ("GET", "POST"):
            auth_token = getattr(env, "X_AUTH_TOKEN", "") or ""
            ct0 = getattr(env, "X_CT0", "") or ""
            if not auth_token or not ct0:
                return json_resp({
                    "success": False,
                    "error": "X_CREDENTIALS_MISSING",
                    "message": (
                        "生产 Worker 未配置 X_AUTH_TOKEN / X_CT0 Secret。"
                        "网页输入框不能写入 Cloudflare Secret。"
                    ),
                }, 400)

            try:
                existing_cats = await get_existing_categories(env)
                pulled, fetch_meta = await fetch_remote_bookmarks(
                    auth_token,
                    ct0,
                    CONFIG.max_sync_pages,
                    existing_cats,
                    env,
                )
            except Exception as sync_err:
                return json_resp({
                    "success": False,
                    "error": "X_SYNC_FAILED",
                    "message": str(sync_err),
                }, 502)

            saved, storage_msg, storage_meta = await save_tweets(env, pulled)
            storage_status = await get_storage_status(env)

            if not saved:
                return json_resp({
                    "success": False,
                    "error": "PERSISTENCE_FAILED",
                    "message": f"X 已拉取 {len(pulled)} 条，但持久化失败：{storage_msg}",
                    "pulled_count": len(pulled),
                    "fetch": fetch_meta,
                    "storage": storage_meta,
                    "storage_status": storage_status,
                    "data": pulled,
                }, 500)

            return json_resp({
                "success": True,
                "message": f"X 拉取 {len(pulled)} 条；{storage_msg}",
                "pulled_count": len(pulled),
                "fetch": fetch_meta,
                "storage": storage_meta,
                "storage_status": storage_status,
                "data": pulled,
            })

        if path == "/api/tweets":
            res = await load_tweets(env)
            fresh = query.get("fresh", ["0"])[0] == "1"
            return json_resp(
                res,
                200,
                cache_seconds=0 if fresh else CONFIG.cache_seconds,
            )

        if path == "/api/bookmarks/classify" and method == "POST":
            ok, msg, items = await batch_classify_pending(env)
            if not ok:
                return json_resp({"success": False, "error": msg}, 400 if "未绑定" in msg else 500)
            return json_resp({
                "success": True,
                "message": msg,
                "total_classified": len(items),
                "items": items,
            })

        if path == "/api/topology/status":
            return json_resp(await get_topology_status(env))

        if path == "/api/topology/renormalize" and method == "POST":
            ok, msg = await renormalize_topology(env)
            if not ok:
                return json_resp({"success": False, "error": msg}, 500 if "异常" in msg else 400)
            return json_resp({"success": True, "message": msg})

        if hasattr(env, "ASSETS"):
            return await env.ASSETS.fetch(request)

        return Response.new("Not Found", JsObject.new(status=404)) if Response else "Not Found"

    except Exception as err:
        return json_resp({"success": False, "error": f"Worker Exception: {str(err)}"}, 500)

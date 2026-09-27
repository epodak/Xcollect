# -*- coding: utf-8 -*-
"""Cloudflare Python Worker 边缘统一路由与分发中枢。"""

import json
import urllib.parse

from config_loader import CONFIG
from twitter import call_x_bookmark_api
from sync_service import perform_cloud_sync
from storage import (
    json_resp,
    load_tweets,
    delete_tweet_from_storage,
    get_storage_status,
    get_sync_status,
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

        if path == "/api/sync/status":
            return json_resp(await get_sync_status(env))

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

        # 手动同步只是一个触发器。真正同步逻辑位于 sync_service，
        # 与 Cloudflare Cron 共用，避免“后台一套、按钮一套”。
        if path == "/api/bookmarks/sync" and method in ("GET", "POST"):
            status_code, payload = await perform_cloud_sync(env, trigger="manual")
            return json_resp(payload, status_code)

        if path == "/api/tweets":
            fresh = query.get("fresh", ["0"])[0] == "1"
            res = await load_tweets(env, bypass_cache=fresh)
            # 书签是用户私有状态，禁止 CDN public cache / stale-while-revalidate。
            # 浏览器端已有 localStorage SWR；网络层始终返回 D1 当前状态。
            return json_resp(res, 200, cache_seconds=0)

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


async def on_scheduled(event, env, ctx):
    """Cloudflare Cron Trigger 入口。

    当前 Worker 仍使用兼容的全局 Python handler 形式，与现有 on_fetch 保持一致。
    Cron 是 Cloud Profile 的主同步路径；网页按钮只是 force-sync / diagnostics。
    """
    cron_expr = getattr(event, "cron", "") or "scheduled"
    status_code, payload = await perform_cloud_sync(
        env,
        trigger=f"cron:{cron_expr}",
    )

    # 抛错让 Cloudflare Cron Past Events / Observability 正确标记失败，
    # 而不是把失败吞成一次“成功执行”。
    if status_code >= 400 or not payload.get("success"):
        raise RuntimeError(
            f"Xcollect scheduled sync failed: "
            f"{payload.get('error', 'UNKNOWN')} - {payload.get('message', '')}"
        )


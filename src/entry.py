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
    record_feedback_event,
)
from discovery import (
    get_daily_feed,
    get_discovery_status,
    run_discovery_cycle,
    set_candidate_state,
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
            source_kind = str(data.get("source_kind", "bookmark") or "bookmark")
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
            elif action == "create":
                await set_candidate_state(env, tweet_id, "saved")

            return json_resp({
                "success": True,
                "message": msg,
                "action": action,
                "tweet_id": tweet_id,
            })

        if path == "/api/feedback" and method == "POST":
            body_text = await request.text()
            try:
                data = json.loads(body_text)
            except Exception:
                return json_resp({"success": False, "error": "Invalid JSON"}, 400)

            ok, msg, event = await record_feedback_event(
                env,
                event_id=data.get("event_id", ""),
                tweet_id=data.get("tweet_id", ""),
                action=data.get("action", ""),
                context=data.get("context", {}),
            )
            if not ok:
                return json_resp({"success": False, "error": msg}, 400)
            return json_resp({
                "success": True,
                "message": msg,
                "event": event,
            })

        # 手动同步只是一个触发器。真正同步逻辑位于 sync_service，
        # 与 Cloudflare Cron 共用，避免“后台一套、按钮一套”。
        if path == "/api/bookmarks/sync" and method in ("GET", "POST"):
            # “立即同步”是 force-sync：做完整集合对账，因此也会发现 X 端取消收藏。
            status_code, payload = await perform_cloud_sync(
                env,
                trigger="manual",
                force_reconcile=True,
            )
            return json_resp(payload, status_code)

        if path == "/api/tweets":
            fresh = query.get("fresh", ["0"])[0] == "1"
            res = await load_tweets(env, bypass_cache=fresh)
            # Bookmarks remain the durable knowledge-base endpoint.
            return json_resp(res, 200, cache_seconds=0)

        if path == "/api/feed":
            fresh = query.get("fresh", ["0"])[0] == "1"
            bookmarks = await load_tweets(env, bypass_cache=fresh)
            bookmark_items = bookmarks.get("data", []) if bookmarks.get("success") else []
            for item in bookmark_items:
                item["source_kind"] = "bookmark"
                item["is_bookmark"] = True

            discovery_items = await get_daily_feed(env)
            bookmark_ids = {str(item.get("id", "")) for item in bookmark_items}
            active_discovery = [
                item for item in discovery_items
                if str(item.get("id", "")) not in bookmark_ids and item.get("discovery_state") not in ("saved", "hidden")
            ]
            for item in active_discovery:
                item["source_kind"] = "discovery"
                item["is_bookmark"] = False

            requested_scope = str(query.get("scope", "") or "").lower()
            if requested_scope == "discovery":
                data_list = active_discovery
            elif requested_scope == "bookmarks":
                data_list = bookmark_items
            else:
                data_list = list(bookmark_items)
                data_list.extend(active_discovery)

            return json_resp({
                "success": bool(bookmarks.get("success", True)),
                "source": "Bookmarks + Daily Discovery",
                "total": len(data_list),
                "bookmark_count": len(bookmark_items),
                "discovery_count": len(active_discovery),
                "preference_evidence_pairs": bookmarks.get("preference_evidence_pairs", 0),
                "data": data_list,
            }, 200, cache_seconds=0)

        if path == "/api/discovery/status":
            return json_resp(await get_discovery_status(env), 200, cache_seconds=0)

        if path == "/api/discovery/run" and method == "POST":
            status_code, payload = await run_discovery_cycle(env, force=True)
            return json_resp(payload, status_code, cache_seconds=0)

        if path == "/api/discovery/action" and method == "POST":
            body_text = await request.text()
            try:
                data = json.loads(body_text)
            except Exception:
                return json_resp({"success": False, "error": "Invalid JSON"}, 400)

            tweet_id = str(data.get("tweet_id", "") or "")
            action = str(data.get("action", "") or "")
            state_map = {
                "not_interested": "hidden",
                "hide": "hidden",
                "saved": "saved",
            }
            state = state_map.get(action, action)
            ok, msg = await set_candidate_state(env, tweet_id, state)
            return json_resp({
                "success": ok,
                "message": msg,
                "tweet_id": tweet_id,
                "state": state,
            }, 200 if ok else 400, cache_seconds=0)

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

    try:
        bookmark_status, bookmark_payload = await perform_cloud_sync(
            env,
            trigger=f"cron:{cron_expr}",
        )
    except Exception as err:
        bookmark_status = 500
        bookmark_payload = {
            "success": False,
            "error": "BOOKMARK_CRON_EXCEPTION",
            "message": str(err),
        }

    try:
        discovery_status, discovery_payload = await run_discovery_cycle(
            env,
            force=False,
        )
    except Exception as err:
        discovery_status = 500
        discovery_payload = {
            "success": False,
            "error": "DISCOVERY_CRON_EXCEPTION",
            "message": str(err),
        }

    failures = []
    if bookmark_status >= 400 or not bookmark_payload.get("success"):
        failures.append(
            "bookmarks="
            + str(bookmark_payload.get("error", "UNKNOWN"))
            + ":"
            + str(bookmark_payload.get("message", ""))
        )
    if discovery_status >= 400 or not discovery_payload.get("success"):
        failures.append(
            "discovery="
            + str(discovery_payload.get("error", "UNKNOWN"))
            + ":"
            + str(discovery_payload.get("message", ""))
        )

    # The planes are independent: one failure must not prevent the other from
    # running, but Cron observability still needs the composite invocation to fail.
    if failures:
        raise RuntimeError("Xcollect scheduled jobs failed: " + " | ".join(failures))


# -*- coding: utf-8 -*-
"""Cloudflare Python Worker 边缘统一路由与分发中枢。"""

import json
import urllib.parse
import hmac

from retrieval import search_items
from decision import evaluate_bookmark
from research import recall_bookmarks
from research_cloud import research_with_workers_ai
from research_index import recall_cloud

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
from watch import create_watch, list_watches, set_watch_state, watch_feed
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

        # CLI/Agent read and decision endpoints: fail closed when secret is absent.
        # Legacy browser routes are unchanged; protect the entire application
        # (including /api/tweets and /api/feed) behind Cloudflare Access.
        if path.startswith("/api/v1/"):
            configured = str(getattr(env, "XCOLLECT_API_TOKEN", "") or "")
            if not configured:
                return json_resp({"success": False, "error": "API_NOT_CONFIGURED"}, 503)
            supplied = str(request.headers.get("Authorization") or "")
            if not hmac.compare_digest(supplied, "Bearer " + configured):
                return json_resp({"success": False, "error": "UNAUTHORIZED"}, 401)

            if path == "/api/v1/search" and method == "GET":
                term = str(query.get("q", [""])[0] or "")
                try:
                    limit = int(query.get("limit", ["20"])[0])
                    if not (1 <= len(term) <= 200 and 1 <= limit <= 100):
                        raise ValueError("Invalid query size or limit")
                    results, backend = await recall_cloud(env, term, limit, load_tweets)
                except (ValueError, TypeError):
                    return json_resp({"success": False, "error": "INVALID_QUERY"}, 400)
                except RuntimeError:
                    return json_resp({"success": False, "error": "STORAGE_UNAVAILABLE"}, 503)
                return json_resp({
                    "success": True, "scope": "bookmarks_only",
                    "query": term, "total": len(results), "results": results,
                    "retrieval_backend": backend,
                }, cache_seconds=0)

            if path.startswith("/api/v1/items/") and method == "GET":
                source_id = urllib.parse.unquote(path[len("/api/v1/items/"):])
                if not source_id or len(source_id) > 200 or "/" in source_id:
                    return json_resp({"success": False, "error": "INVALID_ID"}, 400)
                stored = await load_tweets(env)
                if not stored.get("success"):
                    return json_resp({"success": False, "error": "STORAGE_UNAVAILABLE"}, 503)
                item = next((t for t in stored.get("data", []) if str(t.get("id")) == source_id), None)
                return json_resp({"success": True, "item": item}, cache_seconds=0) if item else json_resp(
                    {"success": False, "error": "NOT_FOUND"}, 404)

            if path == "/api/v1/research" and method == "POST":
                # 一次请求完整贯通：词法召回→逐条 Clef/Jev 判决→LLM 综合→引用交付。
                # 不写入 DB，也不修改 Discovery 的生命周期。
                if not CONFIG.research_enabled:
                    return json_resp({"success": False, "error": "RESEARCH_DISABLED"}, 403)
                try:
                    raw = await request.text()
                    if len(raw) > 85_000:
                        raise ValueError("请求体过大")
                    body = json.loads(raw)
                    question = str(body.get("query") or "")
                    model = str(body.get("model") or CONFIG.research_default_judge_model)
                    limit = int(body.get("limit", 20))
                    count = int(body.get("max_candidates", CONFIG.research_max_candidates))
                    if not (1 <= len(question) <= 200 and 1 <= limit <= 50 and 1 <= count <= 12):
                        raise ValueError("查询参数不合法")
                    if model not in ("clef-flash", "clef", "jev"):
                        raise ValueError("未知类型化模型")
                    if model == "jev" and not CONFIG.decision_allow_jev:
                        return json_resp({"success": False, "error": "JEV_NOT_ENABLED"}, 403)
                    # 本地客户端可以提交自己召回的书签正文，由 Worker 提供 AI 算力。
                    provided = body.get("sources", None)
                    if provided is None:
                        try:
                            candidates, backend = await recall_cloud(env, question, limit, load_tweets)
                        except RuntimeError:
                            return json_resp({"success": False, "error": "STORAGE_UNAVAILABLE"}, 503)
                        profile = "cloud_bookmarks"
                    else:
                        if not isinstance(provided, list) or len(provided) > 50:
                            raise ValueError("本地候选数超过限制")
                        bookmarks = []
                        for source in provided:
                            if not isinstance(source, dict) or not str(source.get("id") or ""):
                                raise ValueError("缺少候选 ID")
                            if len(str(source.get("body_raw") or source.get("snippet") or "")) > 9000:
                                raise ValueError("候选正文过长")
                            bookmarks.append({
                                k: source.get(k) for k in (
                                    "id", "url", "title", "author", "created_at", "category",
                                    "sub_category", "body_raw", "snippet", "username"
                                )
                            })
                        profile = "demo_seed" if body.get("profile") == "demo_seed" else "client_supplied"
                        candidates = recall_bookmarks(bookmarks, question, limit, use_fts=False)
                        backend = "client_candidate_recall"
                except (ValueError, TypeError, AttributeError):
                    return json_resp({"success": False, "error": "INVALID_RESEARCH_REQUEST"}, 400)
                if not candidates:
                    return json_resp({
                        "success": True, "query": question, "profile": profile,
                        "retrieval_backend": backend,
                        "report": "# Xcollect 研究报告\n\n没有找到相关来源，未调用模型。\n",
                        "analysis": "", "sources": [], "decisions": [],
                        "stats": {"recalled": 0, "judged": 0, "accepted": 0},
                    }, cache_seconds=0)
                try:
                    result = await research_with_workers_ai(
                        env, question, candidates, decision_model=model,
                        generation_model=CONFIG.research_generation_model,
                        max_candidates=count, profile=profile,
                    )
                except Exception:
                    return json_resp({"success": False, "error": "RESEARCH_MODEL_UNAVAILABLE"}, 503)
                result["retrieval_backend"] = backend
                return json_resp(result, cache_seconds=0)

            if path == "/api/v1/decide" and method == "POST":
                # Opt-in prevents accidental billable inference.
                if not CONFIG.decision_enabled:
                    return json_resp({"success": False, "error": "DECISION_DISABLED"}, 403)
                # Explicit only: no model invocations on sync, read, or search.
                try:
                    body = json.loads(await request.text())
                    source_id = str(body.get("id") or "")
                    model = str(body.get("model") or "clef-flash")
                    if len(source_id) > 200 or not source_id or model not in ("clef-flash", "clef", "jev"):
                        raise ValueError("Invalid source id or model")
                    if model == "jev" and not CONFIG.decision_allow_jev:
                        return json_resp({"success": False, "error": "JEV_NOT_ENABLED"}, 403)
                except (ValueError, TypeError, AttributeError):
                    return json_resp({"success": False, "error": "INVALID_REQUEST"}, 400)
                stored = await load_tweets(env)
                if not stored.get("success"):
                    return json_resp({"success": False, "error": "STORAGE_UNAVAILABLE"}, 503)
                item = next((t for t in stored.get("data", []) if str(t.get("id")) == source_id), None)
                if item is None:
                    return json_resp({"success": False, "error": "NOT_FOUND"}, 404)
                try:
                    decision = await evaluate_bookmark(env, item, model)
                except Exception:
                    # Don't leak model-provider errors or private source content.
                    return json_resp({"success": False, "error": "DECISION_PROVIDER_UNAVAILABLE"}, 503)
                return json_resp({"success": True, "scope": "bookmarks_only", "decision": decision}, cache_seconds=0)

            return json_resp({"success": False, "error": "NOT_FOUND"}, 404)

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

            promotion_state = ""
            promotion_sync = None
            if action == "delete":
                await delete_tweet_from_storage(env, tweet_id)
            elif action == "create" and source_kind == "discovery":
                # X 已接受收藏，但在 tweets 主库确认之前不能假装成 Durable Bookmark。
                # 先退出 Discovery Inbox，再通过真实 Bookmark Sync 完成 Promotion。
                await set_candidate_state(env, tweet_id, "saved_pending")
                sync_status, sync_payload = await perform_cloud_sync(
                    env,
                    trigger="bookmark-create",
                    force_reconcile=False,
                )
                promotion_sync = {
                    "status": sync_status,
                    "success": bool(sync_payload.get("success")),
                    "message": sync_payload.get("message", ""),
                }
                readback = await load_tweets(env, bypass_cache=True)
                durable_ids = {
                    str(item.get("id", ""))
                    for item in (readback.get("data") or [])
                    if item.get("id")
                }
                if tweet_id in durable_ids:
                    await set_candidate_state(env, tweet_id, "saved")
                    promotion_state = "saved"
                else:
                    promotion_state = "saved_pending"
            elif action == "create":
                # 普通书签恢复沿用既有语义；Discovery 才需要 Promotion bridge。
                promotion_state = "saved"

            return json_resp({
                "success": True,
                "message": msg,
                "action": action,
                "tweet_id": tweet_id,
                "promotion_state": promotion_state,
                "promotion_sync": promotion_sync,
            })

        if path == "/api/feedback" and method == "POST":
            body_text = await request.text()
            try:
                data = json.loads(body_text)
            except Exception:
                return json_resp({"success": False, "error": "Invalid JSON"}, 400)

            # A browser interaction cannot claim verified membership in X Bookmarks.
            if str(data.get("action", "")) in ("bookmark", "unbookmark"):
                return json_resp({"success": False, "error": "BOOKMARK_FEEDBACK_SYNC_ONLY"}, 400)

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
                if str(item.get("id", "")) not in bookmark_ids
                and item.get("discovery_state") not in ("saved", "saved_pending", "hidden", "rejected")
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

        if path == "/api/watch" and method == "GET":
            return json_resp({"success":True,"topics":await list_watches(env)},200,cache_seconds=0)

        if path == "/api/watch" and method == "POST":
            try:
                topic = await create_watch(env,json.loads(await request.text()))
            except (ValueError, TypeError, json.JSONDecodeError) as err:
                return json_resp({"success":False,"error":str(err)},400)
            return json_resp({"success":True,"topic":topic},201,cache_seconds=0)

        if path == "/api/watch/state" and method == "POST":
            try:
                data=json.loads(await request.text())
                item=await set_watch_state(env,str(data.get("id","")),str(data.get("state","")))
            except (ValueError, TypeError, json.JSONDecodeError) as err:
                return json_resp({"success":False,"error":str(err)},400)
            return json_resp({"success":True,"topic":item},200,cache_seconds=0)

        if path == "/api/watch/feed" and method == "GET":
            topic_id=str(query.get("id",[""])[0] or "")
            topics=await list_watches(env)
            if not any(t["id"]==topic_id for t in topics):
                return json_resp({"success":False,"error":"UNKNOWN_TOPIC"},404)
            items=await watch_feed(env,topic_id)
            return json_resp({"success":True,"total":len(items),"data":items},200,cache_seconds=0)

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
                # “误抓/不该进入发现流”与“不喜欢这个话题”是两种不同反馈。
                "reject_candidate": "rejected",
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


# -*- coding: utf-8 -*-
"""Cloudflare Python Worker 边缘统一路由与分发中枢。

职责：
1. 接收 Edge HTTP 请求并进行轻量路径路由分发
2. 调用专职模块处理业务：
   - config_loader: 全局配置单一真源
   - classifier: 智能分类与分类发现
   - twitter: X 官方 GraphQL 协议通信与书签抓取
   - storage: 级联存储（D1/KV/缓存）与拓扑重整化
3. 托管静态资产与边缘 CDN 缓存控制
"""

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

        # 1. 凭据状态感知端点
        if path == "/api/auth/status":
            auth_token = getattr(env, "X_AUTH_TOKEN", "") or ""
            ct0 = getattr(env, "X_CT0", "") or ""
            return json_resp({
                "configured": bool(auth_token and ct0),
                "has_auth_token": bool(auth_token),
                "has_ct0": bool(ct0),
                "auth_token_preview": (auth_token[:6] + "..." + auth_token[-4:]) if auth_token else "",
                "runtime": "Cloudflare Python Worker (Modularized)",
            })

        # 1.1 凭据保存说明端点 (Cloudflare Worker 边缘 Secret 预置兼容)
        if path == "/api/auth/save" and method == "POST":
            return json_resp({
                "success": True,
                "message": "已检测到 Cloudflare Worker 边缘环境已预置有效凭证！",
            })

        # 2. 书签操作端点 (添加 / 删除)
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
                return json_resp({"success": False, "error": "Worker 环境变量未配置 X_AUTH_TOKEN 或 X_CT0"}, 400)

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

        # 3. 实时从 X 云端抓取最新书签列表并入库
        if path == "/api/bookmarks/sync":
            auth_token = getattr(env, "X_AUTH_TOKEN", "") or ""
            ct0 = getattr(env, "X_CT0", "") or ""
            if not auth_token or not ct0:
                return json_resp({"success": False, "message": "未配置 X 平台凭证"}, 400)

            existing_cats = await get_existing_categories(env)
            pulled = await fetch_remote_bookmarks(auth_token, ct0, CONFIG.max_sync_pages, existing_cats, env)

            saved, storage_msg = await save_tweets(env, pulled)
            return json_resp({
                "success": True,
                "message": f"成功拉取并智能归类 {len(pulled)} 篇推文，{storage_msg}",
                "data": pulled,
            })

        # 3.1 查询推文列表 (边缘内存缓存 -> D1 数据库 -> KV 存储级联)
        if path == "/api/tweets":
            res = await load_tweets(env)
            status_code = 200 if res.get("success") else 200
            return json_resp(res, status_code, cache_seconds=CONFIG.cache_seconds)

        # 3.2 批量对历史/未分类/暂存推文执行智能分类与专区归档
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

        # 3.3 拓扑状态感知端点
        if path == "/api/topology/status":
            status_data = await get_topology_status(env)
            return json_resp(status_data)

        # 3.4 拓扑重整化执行端点
        if path == "/api/topology/renormalize" and method == "POST":
            ok, msg = await renormalize_topology(env)
            if not ok:
                return json_resp({"success": False, "error": msg}, 500 if "异常" in msg else 400)
            return json_resp({"success": True, "message": msg})

        # 4. 静态资产回退处理
        if hasattr(env, "ASSETS"):
            return await env.ASSETS.fetch(request)

        return Response.new("Not Found", JsObject.new(status=404)) if Response else "Not Found"

    except Exception as err:
        return json_resp({"success": False, "error": f"Worker Exception: {str(err)}"}, 500)

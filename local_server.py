#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
local_server.py - Twitter 看板、云端书签实时拉取与真实双向同步本地独立服务

遵循 Agent Relay Hygiene 规范：
1. 零业务硬编码：全部解耦参数来自 config.toml (通过 config_loader.CONFIG 加载)
2. 敏感机密隔离：仅从本地私有 .env 提取凭证
3. 一行冒烟自检：python local_server.py --check
"""

import os
import sys
import json
import http.server
import socketserver
import urllib.request
import urllib.parse
import urllib.error
import re
from urllib.parse import urlparse
from pathlib import Path

# 导入集中解耦配置中心
from config_loader import CONFIG

BASE_DIR = Path(__file__).resolve().parent
SERVE_DIR = str(BASE_DIR / "public")
DB_FILE = str(BASE_DIR / "scripts" / "seed_data.json")
ENV_FILE = str(BASE_DIR / ".env")

PORT = CONFIG.port
TWITTER_BEARER = CONFIG.twitter_bearer
QUERY_ID_BOOKMARKS = CONFIG.query_id_bookmarks
QUERY_ID_CREATE = CONFIG.query_id_create
QUERY_ID_DELETE = CONFIG.query_id_delete
DEFAULT_CATEGORIES = list(CONFIG.default_categories)
VALID_CATEGORIES = list(CONFIG.default_categories)


def rule_classify_tweet(text, title=""):
    """纯本地正则与语义关键词规则引擎 (零成本、零延迟、断网100%兜底)"""
    full = f"{title} {text}".lower()
    
    # 1. 01_人工智能与Agent
    if any(k in full for k in [
        "agent", "智能体", "claude code", "cursor", "mcp", "prompt", "提示词", "skills",
        "llm", "大模型", "gpt", "deepseek", "r1", "v3", "o1", "o3", "reasoning", "思维链",
        "openai", "anthropic", "gemini", "llama", "qwen", "vllm", "ollama", "transformers", "coding agent"
    ]):
        if any(k in full for k in ["prompt", "提示词", "skills", "agents.md"]):
            sub = "Prompt与Skills工程"
        elif any(k in full for k in ["claude code", "cursor", "coding agent", "vibe coding", "ide"]):
            sub = "Coding Agent/智能编程"
        elif any(k in full for k in ["mcp", "model context protocol", "tools"]):
            sub = "MCP协议与工具扩展"
        elif any(k in full for k in ["multi-agent", "多智能体", "编排", "swarm", "crew"]):
            sub = "Multi-Agent架构协同"
        elif any(k in full for k in ["deepseek", "r1", "v3", "reasoning", "思维链", "cot", "推理"]):
            sub = "大模型推理与思维链"
        else:
            sub = "AI前沿与模型技术"
        return "01_人工智能与Agent", sub

    # 2. 02_技术架构与开发
    if any(k in full for k in [
        "python", "rust", "golang", "javascript", "typescript", "react", "vue", "docker", "k8s",
        "kubernetes", "backend", "frontend", "api", "database", "sql", "sqlite", "postgres",
        "redis", "cloudflare", "workers", "serverless", "node", "next.js", "linux", "git",
        "架构", "性能优化", "高并发", "微服务", "devops", "ci/cd"
    ]):
        if any(k in full for k in ["cloudflare", "workers", "serverless", "d1", "edge"]):
            sub = "边缘计算与Serverless"
        elif any(k in full for k in ["rust", "golang", "性能", "c++"]):
            sub = "高性能后端与系统架构"
        elif any(k in full for k in ["react", "vue", "frontend", "css", "next.js"]):
            sub = "现代前端与全栈工程"
        elif any(k in full for k in ["database", "sql", "sqlite", "postgres", "redis"]):
            sub = "数据库与存储系统"
        else:
            sub = "系统架构与工程开发"
        return "02_技术架构与开发", sub

    # 3. 03_开源精选与工具
    if any(k in full for k in [
        "github.com", "open source", "开源", "star", "repo", "tool", "tools", "工具",
        "cli", "terminal", "mac", "windows", "devtools", "插件", "workflow", "神器",
        "效率", "osint", "security", "黑客", "漏洞", "逆向"
    ]):
        if any(k in full for k in ["osint", "security", "安全", "shodan", "spiderfoot", "theharvester"]):
            sub = "安全审计与检索工具"
        elif any(k in full for k in ["cli", "terminal", "命令行", "bash", "zsh"]):
            sub = "终端神器与CLI工具"
        elif any(k in full for k in ["github", "star", "repo", "开源"]):
            sub = "GitHub高星开源项目"
        else:
            sub = "开发者生产力工具"
        return "03_开源精选与工具", sub

    # 4. 04_产品设计与思考
    if any(k in full for k in [
        "design", "ui", "ux", "figma", "css", "动效", "交互", "3d", "webgl", "threejs",
        "产品", "product", "独立开发", "indie", "商业", "增长", "用户体验", "界面"
    ]):
        if any(k in full for k in ["3d", "webgl", "threejs", "动效", "blur", "css"]):
            sub = "UI/UX与三维动效"
        elif any(k in full for k in ["独立开发", "indie", "商业", "增长", "变现"]):
            sub = "产品孵化与商业思考"
        else:
            sub = "产品交互与体验设计"
        return "04_产品设计与思考", sub

    # 5. 05_前沿资讯与研读 (兜底)
    if any(k in full for k in ["论文", "paper", "研究", "research", "报告", "report", "思考", "perspective"]):
        sub = "前沿论文与深度研读"
    else:
        sub = "行业前沿与长文洞察"
    return "05_前沿资讯与研读", sub


def get_credentials():
    """从配置中心提取机密凭证 (单一真源来自 .env / 环境)"""
    if CONFIG.x_auth_token and CONFIG.x_ct0:
        return {"auth_token": CONFIG.x_auth_token, "ct0": CONFIG.x_ct0}
    creds = {}
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() in ("X_AUTH_TOKEN", "auth_token"):
                            creds["auth_token"] = v.strip().strip('"').strip("'")
                        elif k.strip() in ("X_CT0", "ct0"):
                            creds["ct0"] = v.strip().strip('"').strip("'")
            if creds.get("auth_token") and creds.get("ct0"):
                return creds
        except Exception:
            pass
    return creds


def save_credentials(auth_token, ct0):
    """保存凭证至本地私有真源 .env 及 Cloudflare 本地机密文件 .dev.vars"""
    data = {"auth_token": auth_token.strip(), "ct0": ct0.strip()}
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write(f"# X 身份凭证 (由本地开发服务器写入，已入 .gitignore)\nX_AUTH_TOKEN={auth_token.strip()}\nX_CT0={ct0.strip()}\n")
    try:
        dev_vars_file = os.path.join(os.path.dirname(__file__), ".dev.vars")
        with open(dev_vars_file, "w", encoding="utf-8") as f:
            f.write(f"# Cloudflare Wrangler 本地开发机密注入文件 (由 .env 同步，已入 .gitignore)\nX_AUTH_TOKEN={auth_token.strip()}\nX_CT0={ct0.strip()}\n")
    except Exception:
        pass
    CONFIG.x_auth_token = auth_token.strip()
    CONFIG.x_ct0 = ct0.strip()
    return data


def classify_tweet_multi_tier(text, title="", active_cats=None):
    """三级阶梯分类调度器：用户自定义 AI -> 本地规则兜底 (保持惯性，吸附在已有大类中)"""
    if not active_cats:
        active_cats = list(DEFAULT_CATEGORIES)
    
    if CONFIG.custom_ai_api_key:
        try:
            url = f"{CONFIG.custom_ai_base.rstrip('/')}/chat/completions"
            cats_list_str = "\n".join([f"- {c}" for c in active_cats])
            prompt = CONFIG.classify_prompt_template.format(existing_categories=cats_list_str)
            payload = json.dumps({
                "model": CONFIG.custom_ai_model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"标题: {title}\n正文: {text}"[:1200]}
                ],
                "temperature": 0.2,
                "max_tokens": 120
            }).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {CONFIG.custom_ai_api_key}"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=CONFIG.timeout) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                content = res.get("choices", [{}])[0].get("message", {}).get("content", "")
                m = re.search(r"\{.*?\}", content, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(0))
                    cat = (parsed.get("category", "") or "").strip()
                    sub = (parsed.get("sub_category", "") or "").strip()
                    for ex in active_cats:
                        if ex.lower() == cat.lower() or ex.split("_", 1)[-1].lower() == cat.split("_", 1)[-1].lower():
                            cat = ex
                            break
                    if cat in active_cats:
                        return cat, (sub or "精选研读")
        except Exception as e:
            print(f"[AI] 用户自定义大模型调用异常，平滑降级至规则引擎兜底: {e}")

    # 兜底：纯本地规则引擎
    return rule_classify_tweet(text, title)


def get_base_headers(auth_token, ct0):
    return {
        "authorization": TWITTER_BEARER,
        "x-csrf-token": ct0,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "cookie": f"auth_token={auth_token}; ct0={ct0};"
    }


def call_x_bookmark_api(tweet_id, action="delete"):
    creds = get_credentials()
    auth_token = creds.get("auth_token")
    ct0 = creds.get("ct0")

    if not auth_token or not ct0:
        return False, "未配置 X 平台凭证 (缺少 auth_token 或 ct0)"

    if action == "create":
        query_id = QUERY_ID_CREATE
        endpoint = "CreateBookmark"
    else:
        query_id = QUERY_ID_DELETE
        endpoint = "DeleteBookmark"

    url = f"https://x.com/i/api/graphql/{query_id}/{endpoint}"
    headers = get_base_headers(auth_token, ct0)
    payload = json.dumps({"variables": {"tweet_id": str(tweet_id)}}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=CONFIG.timeout) as response:
            res_body = response.read().decode("utf-8")
            res_data = json.loads(res_body)
            if "errors" in res_data:
                err_msg = res_data["errors"][0].get("message", "X API 返回错误")
                return False, f"X 平台返回错误: {err_msg}"
            return True, f"成功同步至 X: {endpoint} OK"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        if e.code in (401, 403):
            return False, f"X 凭证失效或 CSRF 错误 (HTTP {e.code})，请更新凭证"
        return False, f"HTTP {e.code}: {body[:180]}"
    except Exception as ex:
        return False, f"网络请求异常: {str(ex)}"


def fetch_remote_bookmarks(max_pages=None):
    """直接调用 X 官方 GraphQL API 连续翻页（游标下潜）拉取全量云端真实书签"""
    if max_pages is None:
        max_pages = CONFIG.max_sync_pages

    creds = get_credentials()
    auth_token = creds.get("auth_token")
    ct0 = creds.get("ct0")

    if not auth_token or not ct0:
        return False, "请先配置 X 账户凭证", []

    features = {
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
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": True,
        "responsive_web_enhance_cards_enabled": False
    }

    cursor = None
    all_tweets = []
    seen_ids = set()
    headers = get_base_headers(auth_token, ct0)
    page_count = 0

    try:
        for page in range(max_pages):
            page_count += 1
            variables = {
                "count": 50,
                "includePromotedContent": False
            }
            if cursor:
                variables["cursor"] = cursor

            params = {
                "variables": json.dumps(variables),
                "features": json.dumps(features)
            }
            url = f"https://x.com/i/api/graphql/{QUERY_ID_BOOKMARKS}/Bookmarks?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req, timeout=CONFIG.timeout) as response:
                res_body = response.read().decode("utf-8")
                res_data = json.loads(res_body)

                timeline = res_data.get("data", {}).get("bookmark_timeline_v2", {}).get("timeline", {})
                instructions = timeline.get("instructions", [])

                page_new_count = 0
                next_cursor = None

                for inst in instructions:
                    entries = inst.get("entries", [])
                    for entry in entries:
                        entry_id = entry.get("entryId", "")
                        
                        # 解析下翻页游标 (以 cursor-bottom- 开头)
                        if "cursor-bottom-" in entry_id:
                            content = entry.get("content", {})
                            val = content.get("value") or content.get("itemContent", {}).get("value")
                            if val:
                                next_cursor = val

                        if entry_id.startswith("tweet-"):
                            item_content = entry.get("content", {}).get("itemContent", {})
                            tweet_res = item_content.get("tweet_results", {}).get("result", {})
                            if tweet_res.get("__typename") == "TweetWithVisibilityResults":
                                tweet_res = tweet_res.get("tweet", {})

                            rest_id = tweet_res.get("rest_id")
                            if rest_id and rest_id not in seen_ids:
                                seen_ids.add(rest_id)
                                page_new_count += 1

                                legacy = tweet_res.get("legacy", {})
                                user_res = tweet_res.get("core", {}).get("user_results", {}).get("result", {})
                                if user_res.get("__typename") == "UserWithVisibilityResults":
                                    user_res = user_res.get("user", {})
                                user_core = user_res.get("core", {})
                                
                                name = user_core.get("name", "")
                                screen_name = user_core.get("screen_name", "")
                                
                                avatar_url = user_res.get("avatar", {}).get("image_url", "")
                                if not avatar_url:
                                    avatar_url = user_res.get("legacy", {}).get("profile_image_url_https", "")
                                if avatar_url:
                                    for sfx in ("_normal", "_bigger", "_mini", "_reasonably_small"):
                                        if sfx in avatar_url:
                                            avatar_url = avatar_url.replace(sfx, "_400x400")
                                            break

                                full_text = legacy.get("full_text", "")
                                fav_count = legacy.get("favorite_count", 0)
                                retweet_count = legacy.get("retweet_count", 0)
                                views_count = 0
                                try:
                                    views_count = int(tweet_res.get("views", {}).get("count", 0))
                                except Exception:
                                    pass

                                created_at = legacy.get("created_at", "")

                                # 提取配图
                                images = []
                                extended_entities = legacy.get("extended_entities", {})
                                for m in extended_entities.get("media", []):
                                    if m.get("type") == "photo" and "media_url_https" in m:
                                        images.append(m["media_url_https"])

                                snippet = full_text.replace("\n", " ").strip()[:140]
                                first_line = full_text.splitlines()[0] if full_text else "推文"
                                display_title = first_line[:45] + ("..." if len(first_line) > 45 else "")

                                cat, subcat = classify_tweet_multi_tier(full_text, display_title)

                                all_tweets.append({
                                    "id": rest_id,
                                    "filename": f"tweet_{rest_id}.md",
                                    "category": cat,
                                    "sub_category": subcat,
                                    "title": display_title,
                                    "author": name or screen_name,
                                    "username": screen_name,
                                    "avatar": avatar_url,
                                    "url": f"https://x.com/{screen_name}/status/{rest_id}",
                                    "created_at": created_at,
                                    "likes": fav_count,
                                    "retweets": retweet_count,
                                    "views": views_count,
                                    "has_media": bool(images),
                                    "media_type": "image" if images else "",
                                    "images": images,
                                    "videos": [],
                                    "snippet": snippet,
                                    "body_raw": full_text,
                                    "classify_status": "projected"
                                })

            # 如果没有下一页游标，或者游标未变，或者本页没有新推文，说明已到达历史最底层
            if not next_cursor or next_cursor == cursor or page_new_count == 0:
                break
            cursor = next_cursor

        return True, f"成功连续翻页同步 {page_count} 页，共拉取 {len(all_tweets)} 篇云端书签！", all_tweets
    except urllib.error.HTTPError as e:
        return False, f"X 平台返回错误 (HTTP {e.code})", all_tweets
    except Exception as ex:
        return False, f"拉取失败: {str(ex)}", all_tweets


class CuratedPortalHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SERVE_DIR, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/auth/status":
            creds = get_credentials()
            is_authed = bool(creds.get("auth_token") and creds.get("ct0"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "configured": is_authed,
                "has_auth_token": bool(creds.get("auth_token")),
                "has_ct0": bool(creds.get("ct0"))
            }).encode("utf-8"))
            return

        if parsed.path == "/api/tweets":
            if os.path.exists(DB_FILE):
                try:
                    with open(DB_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": True,
                        "source": "Local JSON DB",
                        "total": len(data),
                        "data": data
                    }, ensure_ascii=False).encode("utf-8"))
                    return
                except Exception:
                    pass

        if parsed.path == "/api/bookmarks/sync":
            # 实时从云端拉取全量历史书签（多页游标循环）并合并到本地数据库中
            success, msg, remote_tweets = fetch_remote_bookmarks(max_pages=CONFIG.max_sync_pages)
            if success:
                existing_map = {}
                if os.path.exists(DB_FILE):
                    try:
                        with open(DB_FILE, "r", encoding="utf-8") as f:
                            for item in json.load(f):
                                existing_map[item.get("id")] = item
                    except Exception:
                        pass
                
                new_add_count = 0
                for rt in remote_tweets:
                    tid = rt.get("id")
                    if tid not in existing_map:
                        existing_map[tid] = rt
                        new_add_count += 1
                        
                combined_list = list(existing_map.values())
                with open(DB_FILE, "w", encoding="utf-8") as f:
                    json.dump(combined_list, f, ensure_ascii=False)
                    
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "message": f"{msg} (新增入库 {new_add_count} 篇，目前本地库总计 {len(combined_list)} 篇)",
                    "count": len(combined_list),
                    "data": remote_tweets
                }, ensure_ascii=False).encode("utf-8"))
            else:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": msg}).encode("utf-8"))
            return

        if parsed.path == "/api/topology/status":
            tweets = []
            if os.path.exists(DB_FILE):
                try:
                    with open(DB_FILE, "r", encoding="utf-8") as f:
                        tweets = json.load(f)
                except Exception:
                    pass
            total = len(tweets)
            projected = [t for t in tweets if t.get("classify_status") == "projected"]
            settled = [t for t in tweets if t.get("classify_status", "settled") == "settled"]
            
            cat_counts = {}
            for t in tweets:
                c = t.get("category", "未分类")
                cat_counts[c] = cat_counts.get(c, 0) + 1
                
            max_ratio = (max(cat_counts.values()) / total) if total > 0 and cat_counts else 0.0
            needs_renormalize = len(projected) >= CONFIG.renormalize_threshold or (len(projected) >= 10 and max_ratio > CONFIG.max_cluster_ratio)
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "total_tweets": total,
                "projected_count": len(projected),
                "settled_count": len(settled),
                "needs_renormalize": needs_renormalize,
                "categories": cat_counts,
                "max_cluster_ratio": round(max_ratio, 3)
            }, ensure_ascii=False).encode("utf-8"))
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        
        if parsed.path == "/api/auth/save":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body.decode("utf-8"))
                auth_token = data.get("auth_token", "")
                ct0 = data.get("ct0", "")
                save_credentials(auth_token, ct0)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": "凭证已安全保存至本地"}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
            return

        if parsed.path == "/api/bookmark/toggle":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body.decode("utf-8"))
                tweet_id = data.get("tweet_id", "")
                action = data.get("action", "delete")
                
                success, msg = call_x_bookmark_api(tweet_id, action)
                if success and action == "delete" and os.path.exists(DB_FILE):
                    try:
                        with open(DB_FILE, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                        filtered = [t for t in existing if str(t.get("id")) != str(tweet_id)]
                        with open(DB_FILE, "w", encoding="utf-8") as f:
                            json.dump(filtered, f, ensure_ascii=False)
                    except Exception:
                        pass

                self.send_response(200 if success else 400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success, "message": msg, "action": action, "tweet_id": tweet_id}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
            return

        if parsed.path == "/api/bookmarks/classify":
            classified_count = 0
            if os.path.exists(DB_FILE):
                try:
                    with open(DB_FILE, "r", encoding="utf-8") as f:
                        tweets = json.load(f)
                    for t in tweets:
                        if t.get("category") in ("00_云端实时书签", "未分类", "") or "书签" in t.get("category", ""):
                            cat, sub = classify_tweet_multi_tier(t.get("body_raw", "") or t.get("snippet", ""), t.get("title", ""))
                            t["category"] = cat
                            t["sub_category"] = sub
                            classified_count += 1
                    with open(DB_FILE, "w", encoding="utf-8") as f:
                        json.dump(tweets, f, ensure_ascii=False)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": True,
                        "message": f"成功完成 {classified_count} 篇推文智能分类并更新专区！",
                        "total_classified": classified_count
                    }, ensure_ascii=False).encode("utf-8"))
                    return
                except Exception as ex:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(ex)}).encode("utf-8"))
                    return

        if parsed.path == "/api/topology/renormalize":
            if os.path.exists(DB_FILE):
                try:
                    with open(DB_FILE, "r", encoding="utf-8") as f:
                        tweets = json.load(f)
                    
                    projected = [t for t in tweets if t.get("classify_status") == "projected"]
                    for t in tweets:
                        t["classify_status"] = "settled"
                    
                    with open(DB_FILE, "w", encoding="utf-8") as f:
                        json.dump(tweets, f, ensure_ascii=False)
                        
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": True,
                        "message": f"成功完成知识拓扑重整化！已将 {len(projected)} 篇新增推文锚定固化为 settled 状态。",
                        "renormalized_count": len(projected),
                        "total": len(tweets)
                    }, ensure_ascii=False).encode("utf-8"))
                    return
                except Exception as ex:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(ex)}).encode("utf-8"))
                    return

        super().do_POST()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Xcollect Twitter 智能聚合知识看板本地服务")
    parser.add_argument("--port", "-p", type=int, default=PORT, help=f"监听端口 (默认: {PORT})")
    parser.add_argument("--check", action="store_true", help="执行工程卫生冒烟自检")
    args = parser.parse_args()

    if args.check:
        print("🔍 正在执行工程卫生与环境冒烟自检...")
        required_files = [
            os.path.join(SERVE_DIR, "index.html"),
            os.path.join(SERVE_DIR, "css", "cards.css"),
            os.path.join(SERVE_DIR, "js", "app.js"),
            DB_FILE
        ]
        for fpath in required_files:
            if not os.path.exists(fpath):
                print(f"❌ 关键工程资产缺失: {fpath}")
                sys.exit(1)
            print(f"  ✓ 关键资产存在: {os.path.relpath(fpath, os.path.dirname(__file__))}")

        # 检查单一真源配置编译同步状态
        try:
            from scripts.sync_config import sync_config
            if not sync_config(check_only=True):
                print("⚠️ 正在自动将单一真源 config.toml 投影同步至 src/_config_data.py...")
                sync_config(check_only=False)
        except Exception as e:
            print(f"❌ 单一真源配置校验异常: {e}")
            sys.exit(1)

        # 检查配置解析契约：多行 TOML 数组不能退化为字符串 "["
        if not isinstance(CONFIG.default_categories, list) or len(CONFIG.default_categories) < 5:
            print(f"❌ default_categories 解析异常: {CONFIG.default_categories!r}")
            sys.exit(1)
        print(f"  ✓ default_categories 多行数组解析有效 ({len(CONFIG.default_categories)} 项)")

        if not isinstance(CONFIG.workers_ai_models, list) or not CONFIG.workers_ai_models:
            print(f"❌ workers_ai_models 解析异常: {CONFIG.workers_ai_models!r}")
            sys.exit(1)
        print(f"  ✓ workers_ai_models 多行数组解析有效 ({len(CONFIG.workers_ai_models)} 项)")

        if not CONFIG.query_id_bookmarks:
            print("❌ Bookmarks queryId fallback 未配置")
            sys.exit(1)
        print("  ✓ Bookmarks queryId 动态解析/fallback 配置存在")

        # 检查 seed_data.json
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                print("❌ 种子推文数据源格式错误，应为列表")
                sys.exit(1)
            print(f"  ✓ 种子推文数据源有效 (包含 {len(data)} 条推文)")
        except Exception as e:
            print(f"❌ 种子数据解析失败: {e}")
            sys.exit(1)

        print("✅ 工程卫生冒烟自检完全通过！(All smoke checks passed)")
        sys.exit(0)

    class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    server = ThreadedHTTPServer((CONFIG.host, args.port), CuratedPortalHandler)
    print("=" * 60)
    print(f"🚀 Xcollect Twitter 看板与同步服务已在本地启动: http://{CONFIG.host}:{args.port}")
    print(f"📂 静态托管资产目录: {SERVE_DIR}")
    print(f"📦 数据持久化文件: {DB_FILE}")
    print(f"⚙️  AI 算力引擎: {CONFIG.ai_provider} (模型: {CONFIG.custom_ai_model})")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 服务正常停止")
        server.server_close()

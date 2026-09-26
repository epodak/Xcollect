#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py - Twitter 看板、云端书签实时拉取与真实双向同步全功能服务
特性：
1. 静态看板页面与 tweets_db.json 数据服务
2. /api/auth/status 检查本地是否配置了有效凭证
3. /api/auth/save 保存用户输入的 auth_token 和 ct0
4. /api/bookmarks/sync 直接从 X 官方 GraphQL API 实时拉取最新云端收藏推文（支持按需更新 tweets_db.json）
5. /api/bookmark/toggle 代表用户真实调用 X GraphQL API 删除/恢复书签
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

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.toml")
ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
SERVE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "public"))
DB_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "seed_data.json"))

# 从 config.toml 读取非敏感运行参数，严格遵守工程卫生双轨契约
PORT = 8089
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("port =") or line.startswith("port="):
                    val = line.split("=", 1)[1].strip()
                    if val.isdigit():
                        PORT = int(val)
    except Exception:
        pass

TWITTER_BEARER = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

QUERY_ID_BOOKMARKS = "XD0ViOeSOW4YoeNTGjVaYw"
QUERY_ID_CREATE = "aoDbu3RHznuiSkQ9aNM67Q"
QUERY_ID_DELETE = "Wlmlj2-xzyS1GN3a6cj-mQ"

DEFAULT_CATEGORIES = [
    "01_人工智能与Agent",
    "02_技术架构与开发",
    "03_开源精选与工具",
    "04_产品设计与思考",
    "05_前沿资讯与研读"
]

def load_categories_from_config():
    cats = list(DEFAULT_CATEGORIES)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            m = re.search(r"default_categories\s*=\s*\[(.*?)\]", content, re.DOTALL)
            if m:
                raw_items = m.group(1).split(",")
                parsed = [item.strip().strip('"').strip("'") for item in raw_items if item.strip().strip('"').strip("'")]
                if parsed:
                    return parsed
        except Exception:
            pass
    return cats

VALID_CATEGORIES = load_categories_from_config()

def rule_classify_tweet(text, title=""):
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
        "cloudflare", "workers", "serverless", "架构", "全栈", "性能优化", "并发", "linux", "kernel"
    ]):
        if any(k in full for k in ["cloudflare", "workers", "serverless", "docker", "k8s", "部署"]):
            sub = "云原生与边缘计算"
        elif any(k in full for k in ["database", "sql", "sqlite", "postgres", "d1", "kv"]):
            sub = "数据库与存储架构"
        elif any(k in full for k in ["rust", "golang", "python", "typescript", "javascript"]):
            sub = "编程语言与系统构建"
        elif any(k in full for k in ["性能", "并发", "延迟", "benchmark", "优化"]):
            sub = "高性能与系统架构"
        else:
            sub = "全栈工程与系统设计"
        return "02_技术架构与开发", sub

    # 3. 03_开源精选与工具
    if any(k in full for k in [
        "github", "开源", "star", "repo", "open source", "cli", "terminal", "命令行", "bash", "zsh",
        "extension", "神器", "工具", "效率", "productivity", "osint", "spiderfoot", "shodan", "theharvester"
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
    """仅从单一真源 .env 或环境变量提取机密凭证"""
    creds = {}
    if os.environ.get("X_AUTH_TOKEN") and os.environ.get("X_CT0"):
        return {"auth_token": os.environ["X_AUTH_TOKEN"], "ct0": os.environ["X_CT0"]}
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
    """保存凭证至本地私有真源 .env"""
    data = {"auth_token": auth_token.strip(), "ct0": ct0.strip()}
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write(f"# X 身份凭证 (由本地开发服务器写入，已入 .gitignore)\nX_AUTH_TOKEN={auth_token.strip()}\nX_CT0={ct0.strip()}\n")
    return data

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
        with urllib.request.urlopen(req, timeout=12) as response:
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


def fetch_remote_bookmarks(max_count=40):
    """直接调用 X 官方 GraphQL API 拉取云端真实书签"""
    creds = get_credentials()
    auth_token = creds.get("auth_token")
    ct0 = creds.get("ct0")

    if not auth_token or not ct0:
        return False, "请先配置 X 账户凭证", []

    # 加载 features
    features_path = os.path.join(SERVE_DIR, "bm_features.json")
    if os.path.exists(features_path):
        with open(features_path, "r", encoding="utf-8") as ff:
            features = json.load(ff)
    else:
        features = {}

    variables = {
        "count": min(max_count, 100),
        "includePromotedContent": False
    }

    params = {
        "variables": json.dumps(variables),
        "features": json.dumps(features)
    }

    query_string = urllib.parse.urlencode(params)
    url = f"https://x.com/i/api/graphql/{QUERY_ID_BOOKMARKS}/Bookmarks?{query_string}"
    headers = get_base_headers(auth_token, ct0)

    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            
        instructions = data.get("data", {}).get("bookmark_timeline_v2", {}).get("timeline", {}).get("instructions", [])
        parsed_tweets = []
        
        for ins in instructions:
            if ins.get("type") == "TimelineAddEntries":
                for entry in ins.get("entries", []):
                    entry_id = entry.get("entryId", "")
                    if "tweet" in entry_id:
                        content = entry.get("content", {}).get("itemContent", {})
                        tweet_res = content.get("tweet_results", {}).get("result", {})
                        if "tweet" in tweet_res:
                            tweet_res = tweet_res["tweet"]
                            
                        rest_id = tweet_res.get("rest_id", "")
                        legacy = tweet_res.get("legacy", {})
                        user_res = tweet_res.get("core", {}).get("user_results", {}).get("result", {})
                        user_core = user_res.get("core", {})

                        # 提取作者头像（默认 _normal 48px，升级为 _400x400 高清版）
                        avatar_url = user_res.get("avatar", {}).get("image_url", "") or legacy.get("profile_image_url_https", "")
                        for _sfx in ("_normal", "_bigger", "_mini", "_reasonably_small"):
                            if _sfx in avatar_url:
                                avatar_url = avatar_url.replace(_sfx, "_400x400")
                                break

                        name = user_core.get("name", "")
                        screen_name = user_core.get("screen_name", "")
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

                        # 提炼分类与简单标题
                        snippet = full_text.replace("\n", " ").strip()[:140]
                        first_line = full_text.splitlines()[0] if full_text else "推文"
                        display_title = first_line[:45] + ("..." if len(first_line) > 45 else "")
                        
                        # 自动智能分类打标
                        cat, subcat = rule_classify_tweet(full_text, display_title)
                        
                        parsed_tweets.append({
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
                            "body_raw": full_text
                        })
                        
        return True, f"成功从 X 云端拉取到 {len(parsed_tweets)} 篇最新书签！", parsed_tweets
    except urllib.error.HTTPError as e:
        return False, f"X 平台返回错误 (HTTP {e.code})", []
    except Exception as ex:
        return False, f"拉取失败: {str(ex)}", []


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
                except Exception as ex:
                    pass

        if parsed.path == "/api/bookmarks/sync":
            # 实时从云端拉取书签并合并到本地数据库中
            success, msg, remote_tweets = fetch_remote_bookmarks(max_count=50)
            if success:
                # 读取已有数据进行合并去重
                existing_map = {}
                if os.path.exists(DB_FILE):
                    try:
                        with open(DB_FILE, "r", encoding="utf-8") as f:
                            for item in json.load(f):
                                existing_map[item.get("id")] = item
                    except Exception:
                        pass
                
                # 新推文插入到头部
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
                    "message": f"{msg} (新增入库 {new_add_count} 篇，总计 {len(combined_list)} 篇)",
                    "count": len(combined_list)
                }).encode("utf-8"))
            else:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": msg}).encode("utf-8"))
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
            # 批量对本地 tweets_db.json 中未分类或云端实时书签进行归类
            classified_count = 0
            if os.path.exists(DB_FILE):
                try:
                    with open(DB_FILE, "r", encoding="utf-8") as f:
                        tweets = json.load(f)
                    for t in tweets:
                        if t.get("category") in ("00_云端实时书签", "未分类", "") or "书签" in t.get("category", ""):
                            cat, sub = rule_classify_tweet(t.get("body_raw", "") or t.get("snippet", ""), t.get("title", ""))
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
        for rf in required_files:
            if not os.path.exists(rf):
                print(f"❌ 缺少关键文件: {rf}")
                sys.exit(1)
            print(f"  ✓ 关键资产存在: {os.path.relpath(rf, os.path.dirname(__file__))}")
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            print(f"  ✓ 种子推文数据源有效 (包含 {len(d)} 条推文)")
        except Exception as e:
            print(f"❌ 种子数据源解析失败: {e}")
            sys.exit(1)
        print("✅ 工程卫生冒烟自检完全通过！(All smoke checks passed)")
        sys.exit(0)

    listen_port = args.port
    print(f"[*] 启动 Twitter 知识看板与实时云端拉取中枢...")
    print(f"[*] 监听端口: http://localhost:{listen_port}")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", listen_port), CuratedPortalHandler) as httpd:
        httpd.serve_forever()


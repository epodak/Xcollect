import json
import re
import urllib.parse
from js import Response, Headers, Object as JsObject, fetch as js_fetch

TWITTER_BEARER = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
QUERY_ID_BOOKMARKS = "XD0ViOeSOW4YoeNTGjVaYw"
QUERY_ID_CREATE = "aoDbu3RHznuiSkQ9aNM67Q"
QUERY_ID_DELETE = "Wlmlj2-xzyS1GN3a6cj-mQ"

VALID_CATEGORIES = [
    "01_人工智能与Agent",
    "02_技术架构与开发",
    "03_开源精选与工具",
    "04_产品设计与思考",
    "05_前沿资讯与研读"
]

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

def normalize_avatar_url(url):
    """将 X 返回的头像 URL 规范化为更高清的版本。

    X GraphQL 的 core.user_results.result.avatar.image_url 默认返回 _normal (48px)，
    直接把尺寸后缀替换为 _400x400 即可得到高清头像，且 pbs.twimg.com 无需鉴权即可公开访问。
    """
    if not url:
        return ""
    # 仅对形如 xxx_normal.jpg / xxx_bigger.png 的官方头像 URL 做尺寸升级
    for suffix in ("_normal", "_bigger", "_mini", "_reasonably_small"):
        if suffix in url:
            return url.replace(suffix, "_400x400")
    return url


def extract_avatar(user_result):
    """从 X GraphQL 的 user_results.result 中提取作者头像 URL（兼容多套字段结构）"""
    if not isinstance(user_result, dict):
        return ""
    url = user_result.get("avatar", {}).get("image_url", "")
    if not url:
        url = user_result.get("legacy", {}).get("profile_image_url_https", "")
    return normalize_avatar_url(url)


async def get_existing_categories(env):
    cats = list(VALID_CATEGORIES)
    if hasattr(env, "DB"):
        try:
            stmt = env.DB.prepare("SELECT DISTINCT category FROM tweets WHERE category != '00_云端实时书签' AND category != '未分类' AND category NOT LIKE '%书签%'")
            res = await stmt.all()
            db_cats = [str(getattr(r, "category", "")) for r in res.results if getattr(r, "category", "")]
            if db_cats:
                cats = sorted(list(set(cats + db_cats)))
        except Exception as e:
            print("获取已有专区列表失败:", str(e))
    return cats

async def ai_classify_tweet(text, title="", existing_categories=None, env=None):
    if not existing_categories:
        existing_categories = VALID_CATEGORIES
    
    # 提取干净的已有分类列表供 AI 参考
    active_cats = [c for c in existing_categories if c and "书签" not in c and "未分类" not in c]
    if not active_cats:
        active_cats = list(VALID_CATEGORIES)
        
    cats_prompt_list = "\n".join([f"- {c}" for c in active_cats])
    
    if env and hasattr(env, "AI"):
        try:
            content_snippet = (f"标题: {title}\n正文: {text}")[:1400]
            system_prompt = (
                "你是一个科技前沿推文的自适应知识拓扑与分类专家。\n"
                "请阅读推文内容，判断其所属领域专区（category）并提取一个具体的二级子领域（sub_category，4-10字）。\n\n"
                f"【目前已有的专区列表】：\n{cats_prompt_list}\n\n"
                "【分类与自适应扩充原则】：\n"
                "1. 优先复用：如果推文主题与上述【已有专区列表】高度匹配，请直接复用该专区名称。\n"
                "2. 开放扩充（重要）：如果推文明确属于一个全新的技术/业务分支（例如：具身智能与机器人、Web3与加密经济、前沿硬件/单片机、脑机接口/生命科技等），且现有专区无法合理容纳，【请自主定义一个全新的专业专区名称】！\n"
                "   - 命名格式：如果现有专区有编号前缀，请自动顺延编号（例如当前已到05_，新专区可命名为 '06_具身智能与机器人'），字数在5-12字之间，精炼专业。\n"
                "3. 提取二级细分：为推文提炼一个 4-10 字的 sub_category（如：Coding Agent/智能编程、Prompt与Skills工程、云原生与边缘计算等）。\n\n"
                "必须严格只输出 JSON 对象，不得附带任何 markdown 解释或额外字符：\n"
                "{\"category\": \"专区名称\", \"sub_category\": \"二级细分标签\"}"
            )
            ai_res = await env.AI.run(
                "@cf/meta/llama-3.1-8b-instruct",
                {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content_snippet}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 120
                }
            )
            res_str = ""
            if isinstance(ai_res, dict):
                res_str = ai_res.get("response", "")
            elif hasattr(ai_res, "response"):
                res_str = getattr(ai_res, "response", "")
            else:
                res_str = str(ai_res)
            
            m = re.search(r"\{.*?\}", res_str, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
                cat = (parsed.get("category", "") or "").strip()
                sub = (parsed.get("sub_category", "") or "").strip()
                if cat and len(cat) <= 30:
                    # 优先归一化匹配已有分类（防止微小符号差异）
                    for ex in active_cats:
                        if ex.lower() == cat.lower() or ex.split("_", 1)[-1].lower() == cat.split("_", 1)[-1].lower():
                            cat = ex
                            break
                    return cat, (sub or "精选研读")
        except Exception as e:
            print("Workers AI 自适应分类调用异常，回退至规则兜底:", str(e))

    return rule_classify_tweet(text, title)

# 边缘实例级内存高速缓存（读写分离：只在写入时使缓存失效）
_MEM_CACHE_TWEETS = None

def invalidate_cache():
    global _MEM_CACHE_TWEETS
    _MEM_CACHE_TWEETS = None

def json_resp(data, status=200, cache_seconds=0):
    headers = Headers.new()
    headers.set("Content-Type", "application/json; charset=utf-8")
    if cache_seconds > 0:
        # 边缘 CDN 缓存 5 分钟，浏览器缓存 cache_seconds 秒，stale-while-revalidate 兜底
        headers.set("Cache-Control", f"public, max-age={cache_seconds}, s-maxage={cache_seconds * 5}, stale-while-revalidate=86400")
    else:
        headers.set("Cache-Control", "no-store, no-cache, must-revalidate")
    init = JsObject.new()
    init.status = status
    init.headers = headers
    return Response.new(json.dumps(data, ensure_ascii=False), init)

async def on_fetch(request, env):
    try:
        url = urllib.parse.urlparse(request.url)
        path = url.path
        method = request.method.upper()

        # 1. 状态自检端点
        if path == "/api/auth/status":
            auth_token = ""
            ct0 = ""
            try:
                auth_token = getattr(env, "X_AUTH_TOKEN", "") or ""
                ct0 = getattr(env, "X_CT0", "") or ""
            except Exception:
                pass
            configured = bool(auth_token and ct0)
            return json_resp({
                "configured": configured,
                "has_auth_token": bool(auth_token),
                "has_ct0": bool(ct0),
                "auth_token_preview": (auth_token[:6] + "..." + auth_token[-4:]) if auth_token else "",
                "runtime": "Cloudflare Python Worker"
            })

        # 1.1 保存凭据接口 (Cloudflare Worker 边缘环境兼容支持)
        if path == "/api/auth/save" and method == "POST":
            return json_resp({
                "success": True,
                "message": "已检测到 Cloudflare Worker 边缘 Secret 已预置有效凭证！"
            })

        # 2. 书签操作端点 (删除/恢复)
        if path == "/api/bookmark/toggle" and method == "POST":
            body_text = await request.text()
            try:
                data = json.loads(body_text)
            except Exception:
                return json_resp({"success": False, "error": "Invalid JSON"}, 400)

            tweet_id = data.get("tweet_id", "")
            action = data.get("action", "delete")

            auth_token = getattr(env, "X_AUTH_TOKEN", "") or ""
            ct0 = getattr(env, "X_CT0", "") or ""

            if not auth_token or not ct0:
                return json_resp({"success": False, "error": "Worker 环境变量未配置 X_AUTH_TOKEN 或 X_CT0"}, 400)

            query_id = QUERY_ID_CREATE if action == "create" else QUERY_ID_DELETE
            endpoint = "CreateBookmark" if action == "create" else "DeleteBookmark"
            x_url = f"https://x.com/i/api/graphql/{query_id}/{endpoint}"

            h = Headers.new()
            h.set("authorization", TWITTER_BEARER)
            h.set("x-csrf-token", ct0)
            h.set("x-twitter-active-user", "yes")
            h.set("x-twitter-auth-type", "OAuth2Session")
            h.set("content-type", "application/json")
            h.set("user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")
            h.set("cookie", f"auth_token={auth_token}; ct0={ct0};")

            init = JsObject.new()
            init.method = "POST"
            init.headers = h
            init.body = json.dumps({"variables": {"tweet_id": str(tweet_id)}})

            x_resp = await js_fetch(x_url, init)
            res_text = await x_resp.text()
            res_data = json.loads(res_text)

            if "errors" in res_data:
                err_msg = res_data["errors"][0].get("message", "X API error")
                return json_resp({"success": False, "message": err_msg}, 400)

            # 同步更新 Cloudflare D1 边缘数据库：若在 X 上移出书签，则从 D1 中删除该推文
            if hasattr(env, "DB") and action == "delete":
                try:
                    stmt = env.DB.prepare("DELETE FROM tweets WHERE id = ?").bind(str(tweet_id))
                    await stmt.run()
                    invalidate_cache()
                except Exception as d_err:
                    print("D1 删除推文同步异常:", str(d_err))

            return json_resp({"success": True, "message": f"成功从 X 云端与 D1 数据库同步: {endpoint}", "action": action, "tweet_id": tweet_id})

        # 3. 实时从 X 云端抓取最新书签列表并入库 D1
        if path == "/api/bookmarks/sync":
            auth_token = getattr(env, "X_AUTH_TOKEN", "") or ""
            ct0 = getattr(env, "X_CT0", "") or ""
            if not auth_token or not ct0:
                return json_resp({"success": False, "message": "未配置 X 平台凭证"}, 400)

            features = {
                "rweb_video_screen_enabled": False,
                "rweb_cashtags_enabled": True,
                "profile_label_improvements_pcf_label_in_post_enabled": True,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "view_counts_everywhere_api_enabled": True,
                "longform_notetweets_consumption_enabled": True
            }
            # 支持游标连续翻页深度拉取（最大 15 页，单页 50 篇，足以完整覆盖 750+ 篇全量书签）
            max_pages = 15
            cursor = None
            pulled = []
            seen_ids = set()
            page_count = 0

            # 动态获取当前系统已有分类拓扑
            existing_cats = await get_existing_categories(env)

            for page in range(max_pages):
                page_count += 1
                params_vars = {"count": 50, "includePromotedContent": False}
                if cursor:
                    params_vars["cursor"] = cursor

                params = {
                    "variables": json.dumps(params_vars),
                    "features": json.dumps(features)
                }
                q_str = urllib.parse.urlencode(params)
                x_url = f"https://x.com/i/api/graphql/{QUERY_ID_BOOKMARKS}/Bookmarks?{q_str}"

                h = Headers.new()
                h.set("authorization", TWITTER_BEARER)
                h.set("x-csrf-token", ct0)
                h.set("x-twitter-active-user", "yes")
                h.set("x-twitter-auth-type", "OAuth2Session")
                h.set("content-type", "application/json")
                h.set("user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")
                h.set("cookie", f"auth_token={auth_token}; ct0={ct0};")

                init = JsObject.new()
                init.method = "GET"
                init.headers = h

                resp = await js_fetch(x_url, init)
                raw_text = await resp.text()
                raw_data = json.loads(raw_text)

                instructions = raw_data.get("data", {}).get("bookmark_timeline_v2", {}).get("timeline", {}).get("instructions", [])
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
                                        "created_at": created_at
                                    })

                # 翻页终止判定：无下游标、游标未前进、或本页无新推文
                if not next_cursor or next_cursor == cursor or page_new_count == 0:
                    break
                cursor = next_cursor

            # 如果 Worker 绑定了 D1 数据库，则批量写入持久化保存！
            saved_to_d1 = False
            if hasattr(env, "DB") and pulled:
                try:
                    # 向后兼容：优先写入含 avatar 列的新 schema，若数据库尚未执行迁移则自动降级为旧 schema
                    sql = """
                    INSERT OR REPLACE INTO tweets (
                        id, filename, category, sub_category, title, author, username, url, created_at,
                        likes, retweets, views, has_media, media_type, images, videos, snippet, body_raw, body_html, avatar
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    sql_legacy = """
                    INSERT OR REPLACE INTO tweets (
                        id, filename, category, sub_category, title, author, username, url, created_at,
                        likes, retweets, views, has_media, media_type, images, videos, snippet, body_raw, body_html
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    for item in pulled:
                        base_args = [
                            str(item["id"]),
                            f"twitter_{item['username']}_status_{item['id']}.md",
                            item["category"],
                            item["sub_category"],
                            item["title"],
                            item["author"],
                            item["username"],
                            item["url"],
                            item["created_at"],
                            int(item["likes"] or 0),
                            int(item["retweets"] or 0),
                            int(item["views"] or 0),
                            0,
                            "",
                            "[]",
                            "[]",
                            item["snippet"],
                            item["body_raw"],
                            ""
                        ]
                        try:
                            stmt = env.DB.prepare(sql).bind(*(base_args + [item.get("avatar", "") or ""]))
                            await stmt.run()
                        except Exception as col_err:
                            if "avatar" in str(col_err).lower():
                                print("avatar 列缺失，降级为旧 schema 写入:", str(col_err))
                                stmt = env.DB.prepare(sql_legacy).bind(*base_args)
                                await stmt.run()
                            else:
                                raise
                    saved_to_d1 = True
                except Exception as db_err:
                    print("D1 自动同步写入异常:", str(db_err))

            if saved_to_d1:
                invalidate_cache()

            msg_suffix = "，并已永久固化保存至 Cloudflare D1 边缘数据库！" if saved_to_d1 else ""
            return json_resp({"success": True, "message": f"Cloudflare Worker 成功拉取并智能归类 {len(pulled)} 篇书签{msg_suffix}", "data": pulled})

        # 3.2 批量对历史/未分类/暂存推文执行 Workers AI 智能分类与专区归档
        if path == "/api/bookmarks/classify" and method == "POST":
            if not hasattr(env, "DB"):
                return json_resp({"success": False, "message": "未绑定 Cloudflare D1 数据库"}, 400)
            try:
                # 动态获取已存在的分类列表
                existing_cats = await get_existing_categories(env)

                # 查找待分类的推文（包含 00_云端实时书签 或 未分类）
                stmt = env.DB.prepare("""
                    SELECT id, title, snippet, body_raw, category, sub_category 
                    FROM tweets 
                    WHERE category = '00_云端实时书签' OR category = '未分类' OR category LIKE '%书签%' OR sub_category IS NULL OR sub_category = '' OR sub_category = '精选'
                    LIMIT 60
                """)
                db_res = await stmt.all()
                rows = db_res.results
                
                classified_items = []
                for r in rows:
                    t_id = str(getattr(r, "id", ""))
                    t_title = getattr(r, "title", "") or ""
                    t_body = getattr(r, "body_raw", "") or getattr(r, "snippet", "") or ""
                    
                    cat, subcat = await ai_classify_tweet(t_body, t_title, existing_cats, env)
                    if cat not in existing_cats:
                        existing_cats.append(cat)
                    
                    up_stmt = env.DB.prepare("""
                        UPDATE tweets 
                        SET category = ?, sub_category = ? 
                        WHERE id = ?
                    """).bind(cat, subcat, t_id)
                    await up_stmt.run()
                    
                    classified_items.append({
                        "id": t_id,
                        "title": t_title[:30],
                        "category": cat,
                        "sub_category": subcat
                    })

                if classified_items:
                    invalidate_cache()
                    
                return json_resp({
                    "success": True,
                    "message": f"Cloudflare Workers AI 成功完成 {len(classified_items)} 篇推文智能分类并更新至各个专区！",
                    "total_classified": len(classified_items),
                    "items": classified_items
                })
            except Exception as clf_err:
                return json_resp({"success": False, "error": f"批量智能分类异常: {str(clf_err)}"}, 500)

        # 3.1 查询推文列表（优先边缘内存高速缓存与全球 CDN 缓存，彻底避免访客重复击穿 D1 数据库）
        if path == "/api/tweets":
            global _MEM_CACHE_TWEETS
            if _MEM_CACHE_TWEETS is not None:
                # 内存命中：0ms 访问 D1，带边缘 CDN 缓存控制
                return json_resp(_MEM_CACHE_TWEETS, 200, cache_seconds=60)

            if hasattr(env, "DB"):
                try:
                    stmt = env.DB.prepare("SELECT * FROM tweets ORDER BY likes DESC LIMIT 1000")
                    db_res = await stmt.all()
                    rows = db_res.results
                    # 转换 rows (JsArray of JsObjects)
                    tweets_list = []
                    for r in rows:
                        row_dict = {
                            "id": str(getattr(r, "id", "")),
                            "filename": getattr(r, "filename", ""),
                            "category": getattr(r, "category", "") or "未分类",
                            "sub_category": getattr(r, "sub_category", "") or rule_classify_tweet(getattr(r, "body_raw", "") or getattr(r, "snippet", ""), getattr(r, "title", ""))[1],
                            "title": getattr(r, "title", ""),
                            "author": getattr(r, "author", ""),
                            "username": getattr(r, "username", ""),
                            "avatar": getattr(r, "avatar", "") or "",
                            "url": getattr(r, "url", ""),
                            "created_at": getattr(r, "created_at", ""),
                            "likes": int(getattr(r, "likes", 0) or 0),
                            "retweets": int(getattr(r, "retweets", 0) or 0),
                            "views": int(getattr(r, "views", 0) or 0),
                            "has_media": bool(getattr(r, "has_media", 0)),
                            "media_type": getattr(r, "media_type", ""),
                            "images": json.loads(getattr(r, "images", "[]") or "[]") if isinstance(getattr(r, "images", None), str) else [],
                            "videos": json.loads(getattr(r, "videos", "[]") or "[]") if isinstance(getattr(r, "videos", None), str) else [],
                            "snippet": getattr(r, "snippet", ""),
                            "body_raw": getattr(r, "body_raw", ""),
                            "body_html": getattr(r, "body_html", "")
                        }
                        tweets_list.append(row_dict)
                    if tweets_list:
                        _MEM_CACHE_TWEETS = {
                            "success": True, 
                            "source": "Cloudflare D1 (Edge Cached)", 
                            "total": len(tweets_list), 
                            "data": tweets_list
                        }
                        return json_resp(_MEM_CACHE_TWEETS, 200, cache_seconds=60)
                except Exception as d1_err:
                    print("从 D1 读取异常:", str(d1_err))

            return json_resp({"success": False, "message": "D1 数据库未就绪或暂时无数据"}, 404)

        # 4. 其他路由回退给静态资产 binding
        if hasattr(env, "ASSETS"):
            return await env.ASSETS.fetch(request)
        return Response.new("Not Found", JsObject.new(status=404))

    except Exception as err:
        return json_resp({"success": False, "error": f"Worker Exception: {str(err)}"}, 500)

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
import shutil
import threading
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime, timezone

# 导入集中解耦配置中心
from config_loader import CONFIG
from src.ranking import enrich_related_hot_many
from src.preferences import apply_preference_profile

BASE_DIR = Path(__file__).resolve().parent
SERVE_DIR = str(BASE_DIR / "public")
DATA_DIR = BASE_DIR / "data"
DB_FILE = str(DATA_DIR / "xcollect.json")
SEED_FILE = str(BASE_DIR / "scripts" / "seed_data.json")
ENV_FILE = str(BASE_DIR / ".env")
FEEDBACK_FILE = str(DATA_DIR / "feedback_events.jsonl")
LOCAL_DB_LOCK = threading.RLock()


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


def atomic_write_json(path, data, keep_backup=True):
    """原子写入本地 JSON；同目录临时文件 + fsync + os.replace，避免中断损坏主库。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    backup = target.with_suffix(target.suffix + ".bak")

    with LOCAL_DB_LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        if keep_backup and target.exists():
            try:
                shutil.copy2(target, backup)
            except Exception:
                pass

        os.replace(tmp, target)


def ensure_local_data_file():
    """创建 Local Profile 数据文件；首次运行兼容迁移旧 seed_data.json 内容。"""
    target = Path(DB_FILE)
    if target.exists():
        return

    initial = []
    legacy = Path(SEED_FILE)
    if legacy.exists():
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                initial = loaded
        except Exception:
            initial = []

    atomic_write_json(DB_FILE, initial, keep_backup=False)


def load_local_feedback(limit=5000):
    feedback_path = Path(FEEDBACK_FILE)
    if not feedback_path.exists():
        return []
    events = []
    with LOCAL_DB_LOCK:
        try:
            with open(feedback_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            events.append(event)
                    except Exception:
                        continue
        except Exception:
            return []
    return events[-max(1, int(limit)):]


def append_local_feedback(event_id, tweet_id, action, context=None):
    event_id = str(event_id or "").strip()[:128]
    tweet_id = str(tweet_id or "").strip()[:128]
    action = str(action or "").strip()
    if not event_id or not tweet_id:
        return False, "event_id 和 tweet_id 不能为空", {}

    if action == "reject_candidate":
        feedback_weight = float(CONFIG.feedback_weights.get("not_interested", -1.20))
    elif action in CONFIG.feedback_weights:
        feedback_weight = float(CONFIG.feedback_weights[action])
    else:
        return False, f"不支持的 feedback action: {action}", {}

    if isinstance(context, dict):
        context_value = context
    else:
        context_value = {"value": str(context or "")[:2000]}

    payload = {
        "event_id": event_id,
        "tweet_id": tweet_id,
        "action": action,
        "weight": feedback_weight,
        "context": context_value,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOCAL_DB_LOCK:
        existing_ids = set()
        feedback_path = Path(FEEDBACK_FILE)
        if feedback_path.exists():
            try:
                with open(feedback_path, "r", encoding="utf-8") as existing_file:
                    for line in existing_file:
                        try:
                            old = json.loads(line)
                            if old.get("event_id"):
                                existing_ids.add(str(old["event_id"]))
                        except Exception:
                            continue
            except Exception:
                pass

        if event_id not in existing_ids:
            with open(feedback_path, "a", encoding="utf-8") as out:
                out.write(json.dumps(payload, ensure_ascii=False) + "\n")
                out.flush()
                os.fsync(out.fileno())

    return True, "feedback recorded", payload


def load_local_tweets():
    ensure_local_data_file()
    with LOCAL_DB_LOCK:
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []


def save_local_tweets(tweets):
    atomic_write_json(DB_FILE, tweets)


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
    """Local Profile 仅更新 .env 中的 X 凭证，并保留其他私有配置。"""
    auth_token = auth_token.strip()
    ct0 = ct0.strip()
    data = {"auth_token": auth_token, "ct0": ct0}

    preserved = []
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    key = line.split("=", 1)[0].strip() if "=" in line else ""
                    if key not in ("X_AUTH_TOKEN", "X_CT0"):
                        preserved.append(line.rstrip("\n"))
        except Exception:
            preserved = []

    lines = [
        "# Xcollect 本地私有配置（已入 .gitignore）",
        f"X_AUTH_TOKEN={auth_token}",
        f"X_CT0={ct0}",
    ]
    if preserved:
        lines.extend([""] + preserved)

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
        f.flush()
        os.fsync(f.fileno())

    CONFIG.x_auth_token = auth_token
    CONFIG.x_ct0 = ct0
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


def resolve_bookmark_query_ids_local():
    """Local Profile 动态解析 Bookmarks queryId，并保留 config fallback。"""
    candidates = []
    registry_url = getattr(CONFIG, "query_id_registry_url", "") or ""
    if registry_url:
        try:
            req = urllib.request.Request(
                registry_url,
                headers={"User-Agent": "Xcollect/1.0"},
            )
            with urllib.request.urlopen(req, timeout=CONFIG.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                operation = payload.get("Bookmarks", {}) if isinstance(payload, dict) else {}
                registry_id = operation.get("queryId", "") if isinstance(operation, dict) else ""
                if registry_id:
                    candidates.append(registry_id)
        except Exception as e:
            print(f"[X] queryId registry 不可用，继续使用本地 fallback: {e}")

    candidates.append(getattr(CONFIG, "query_id_bookmarks", "") or "")
    candidates.extend(getattr(CONFIG, "query_id_bookmarks_fallbacks", []) or [])

    result = []
    seen = set()
    for value in candidates:
        value = str(value or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _expand_x_urls_local(text, entity_set):
    text = str(text or "")
    if not text or not isinstance(entity_set, dict):
        return text
    for entity in entity_set.get("urls", []) or []:
        short = str(entity.get("url", "") or "")
        expanded = str(entity.get("expanded_url", "") or entity.get("display_url", "") or "")
        if short and expanded:
            text = text.replace(short, expanded)
    return text


def _article_to_markdown_local(article_result):
    if not isinstance(article_result, dict):
        return "", ""
    title = str(article_result.get("title", "") or "").strip()
    content_state = article_result.get("content_state", {}) or {}
    blocks = content_state.get("blocks", []) or []
    if not isinstance(blocks, list):
        blocks = []
    parts = []
    ordered_counter = 0
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type", "unstyled") or "unstyled")
        text = str(block.get("text", "") or "")
        if block_type == "atomic" or not text:
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
    return title, body


def _extract_canonical_content_local(tweet_result, legacy):
    article_result = (
        (((tweet_result.get("article", {}) or {}).get("article_results", {}) or {}).get("result"))
        or (((legacy.get("article", {}) or {}).get("article_results", {}) or {}).get("result"))
        or ((tweet_result.get("article_results", {}) or {}).get("result"))
    )
    if isinstance(article_result, dict):
        title, body = _article_to_markdown_local(article_result)
        if body:
            return title, body

    note_result = ((((tweet_result.get("note_tweet", {}) or {}).get("note_tweet_results", {}) or {}).get("result")) or {})
    note_text = str(note_result.get("text", "") or "")
    if note_text:
        return "", _expand_x_urls_local(note_text, note_result.get("entity_set", {}) or {}).strip()

    legacy_text = str(legacy.get("full_text", "") or "")
    return "", _expand_x_urls_local(legacy_text, legacy.get("entities", {}) or {}).strip()


def fetch_remote_bookmarks(max_pages=None, known_ids=None, full_scan=False):
    """Local Profile 拉取 X Bookmarks；full_scan=True 时用于安全删除对账。"""
    if max_pages is None:
        max_pages = CONFIG.max_sync_pages
    known_ids = {str(x) for x in (known_ids or set()) if x}

    creds = get_credentials()
    auth_token = creds.get("auth_token")
    ct0 = creds.get("ct0")

    if not auth_token or not ct0:
        return False, "请先配置 X 账户凭证", [], {"scan_complete": False}

    query_ids = resolve_bookmark_query_ids_local()
    if not query_ids:
        return False, "没有可用的 X Bookmarks queryId", [], {"scan_complete": False}

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
        "articles_preview_enabled": True,
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": True,
        "responsive_web_enhance_cards_enabled": False,
    }

    cursor = None
    all_tweets = []
    seen_ids = set()
    headers = get_base_headers(auth_token, ct0)
    page_count = 0
    selected_query_id = None
    failures = []
    stopped_on_known_page = False
    reached_timeline_end = False

    for _page in range(max_pages):
        page_count += 1
        variables = {"count": 50, "includePromotedContent": False}
        if cursor:
            variables["cursor"] = cursor
        params = {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(features, separators=(",", ":")),
            "fieldToggles": json.dumps({
                "withArticleRichContentState": True,
                "withArticlePlainText": True,
            }, separators=(",", ":")),
        }

        timeline = None
        candidate_ids = [selected_query_id] if selected_query_id else query_ids

        for query_id in candidate_ids:
            if not query_id:
                continue
            url = f"https://x.com/i/api/graphql/{query_id}/Bookmarks?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=CONFIG.timeout) as response:
                    raw = response.read().decode("utf-8")
                    payload = json.loads(raw)
                if payload.get("errors"):
                    failures.append(f"{query_id}: {payload['errors'][0].get('message', 'GraphQL error')}")
                    continue

                data = payload.get("data", {})
                timeline = (
                    (data.get("bookmark_timeline_v2", {}) or {}).get("timeline")
                    or (data.get("bookmark_timeline", {}) or {}).get("timeline")
                )
                if not isinstance(timeline, dict):
                    failures.append(f"{query_id}: 响应缺少 bookmark timeline")
                    timeline = None
                    continue

                selected_query_id = query_id
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    return False, f"X 凭证失效或 CSRF 错误 (HTTP {e.code})，请更新凭证", all_tweets, {"scan_complete": False}
                failures.append(f"{query_id}: HTTP {e.code}")
            except Exception as e:
                failures.append(f"{query_id}: {str(e)[:120]}")

        if timeline is None:
            detail = " | ".join(failures[-4:]) or "无可用响应"
            return False, f"X Bookmarks 协议不可用：{detail}", all_tweets, {"scan_complete": False}

        page_seen_count = 0
        page_unknown_count = 0
        next_cursor = None

        for inst in timeline.get("instructions", []) or []:
            entries = inst.get("entries", []) or []
            if not entries and isinstance(inst.get("entry"), dict):
                entries = [inst["entry"]]

            for entry in entries:
                entry_id = entry.get("entryId", "")
                content = entry.get("content", {}) or {}

                if "cursor-bottom" in entry_id or content.get("cursorType") == "Bottom":
                    val = content.get("value") or (content.get("itemContent", {}) or {}).get("value")
                    if val:
                        next_cursor = val

                if "tweet" not in entry_id:
                    continue

                item_content = content.get("itemContent", {}) or {}
                tweet_res = (item_content.get("tweet_results", {}) or {}).get("result", {}) or {}
                if tweet_res.get("__typename") == "TweetWithVisibilityResults":
                    tweet_res = tweet_res.get("tweet", {}) or {}
                elif isinstance(tweet_res.get("tweet"), dict):
                    tweet_res = tweet_res.get("tweet", {}) or {}

                rest_id = str(tweet_res.get("rest_id", "") or "")
                if not rest_id or rest_id in seen_ids:
                    continue

                seen_ids.add(rest_id)
                page_seen_count += 1
                if rest_id not in known_ids:
                    page_unknown_count += 1

                legacy = tweet_res.get("legacy", {}) or {}
                user_res = (tweet_res.get("core", {}) or {}).get("user_results", {}).get("result", {}) or {}
                if user_res.get("__typename") == "UserWithVisibilityResults":
                    user_res = user_res.get("user", {}) or {}
                user_core = user_res.get("core", {}) or {}

                name = user_core.get("name", "")
                screen_name = user_core.get("screen_name", "")

                avatar_url = (user_res.get("avatar", {}) or {}).get("image_url", "")
                if not avatar_url:
                    avatar_url = (user_res.get("legacy", {}) or {}).get("profile_image_url_https", "")
                if avatar_url:
                    for sfx in ("_normal", "_bigger", "_mini", "_reasonably_small"):
                        if sfx in avatar_url:
                            avatar_url = avatar_url.replace(sfx, "_400x400")
                            break

                title_hint, full_text = _extract_canonical_content_local(tweet_res, legacy)
                fav_count = int(legacy.get("favorite_count", 0) or 0)
                retweet_count = int(legacy.get("retweet_count", 0) or 0)
                try:
                    views_count = int((tweet_res.get("views", {}) or {}).get("count", 0) or 0)
                except Exception:
                    views_count = 0

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
                            videos.append({
                                "url": mp4s[0]["url"],
                                "poster": media.get("media_url_https", ""),
                                "type": media_type,
                            })

                snippet = full_text.replace("\n", " ").strip()[:140]
                first_line = title_hint or (full_text.splitlines()[0] if full_text else "推文")
                display_title = first_line[:72] + ("..." if len(first_line) > 72 else "")
                cat, subcat = rule_classify_tweet(full_text, display_title)

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
                    "created_at": legacy.get("created_at", ""),
                    "bookmark_sort_index": str(entry.get("sortIndex", "") or ""),
                    "likes": fav_count,
                    "retweets": retweet_count,
                    "views": views_count,
                    "has_media": bool(images or videos),
                    "media_type": "video" if videos else ("image" if images else ""),
                    "images": images,
                    "videos": videos,
                    "snippet": snippet,
                    "body_raw": full_text,
                    "classify_status": "projected",
                })

        # 增量模式可在整页已知时停止；完整对账必须翻到时间线自然结束。
        if not full_scan and known_ids and page_unknown_count == 0:
            stopped_on_known_page = True
            break
        if not next_cursor or next_cursor == cursor or page_seen_count == 0:
            reached_timeline_end = True
            break
        cursor = next_cursor

    all_tweets.sort(
        key=lambda item: int(item.get("bookmark_sort_index") or 0),
        reverse=True,
    )
    return (
        True,
        f"成功同步 {page_count} 页，共读取 {len(all_tweets)} 篇书签"
        + (f"（queryId={selected_query_id}）" if selected_query_id else ""),
        all_tweets,
        {
            "scan_mode": "full" if full_scan else "incremental",
            "scan_complete": bool(reached_timeline_end),
            "stopped_on_known_page": bool(stopped_on_known_page),
            "truncated_by_max_pages": bool(full_scan and not reached_timeline_end),
        },
    )


def sync_local_bookmarks():
    """执行 Local Profile 的 X → JSON 增量同步，并返回 HTTP 状态码与响应体。"""
    existing = load_local_tweets()
    known_ids = {str(item.get("id")) for item in existing if item.get("id")}

    success, msg, remote_tweets, fetch_meta = fetch_remote_bookmarks(
        max_pages=CONFIG.max_sync_pages,
        known_ids=known_ids,
        full_scan=True,
    )
    if not success:
        return 400, {
            "success": False,
            "message": msg,
            "storage_profile": "local",
            "fetch": fetch_meta,
        }

    existing_map = {str(item.get("id")): item for item in existing if item.get("id")}
    remote_ordered = []
    remote_ids = set()
    new_add_count = 0

    for position, rt in enumerate(remote_tweets):
        tid = str(rt.get("id", ""))
        if not tid:
            continue
        remote_ids.add(tid)
        old = existing_map.get(tid)

        if old:
            merged = dict(old)
            merged.update(rt)
            # 用户知识层优先于重新同步得到的规则投影。
            for semantic_key in ("category", "sub_category", "classify_status"):
                if old.get(semantic_key):
                    merged[semantic_key] = old[semantic_key]
        else:
            merged = dict(rt)
            new_add_count += 1

        merged["bookmark_position"] = position
        remote_ordered.append(merged)

    if fetch_meta.get("scan_complete"):
        # X 完整书签集合是本轮权威真值：本地存在但 X 不存在的条目就是已取消收藏。
        removed_ids = [
            str(item.get("id"))
            for item in existing
            if str(item.get("id", "")) not in remote_ids
        ]
        tail = []
    else:
        # 未翻到时间线末尾时绝不根据“缺失”删除，避免 max_pages 导致误删。
        removed_ids = []
        tail = [
            item for item in existing
            if str(item.get("id", "")) not in remote_ids
        ]

    for offset, item in enumerate(tail, start=len(remote_ordered)):
        item["bookmark_position"] = offset

    combined_list = remote_ordered + tail
    save_local_tweets(combined_list)

    removed_count = len(removed_ids)
    reconcile_msg = (
        f"；移除 {removed_count} 条 X 已取消收藏"
        if fetch_meta.get("scan_complete")
        else "；完整对账未完成，未执行删除"
    )

    return 200, {
        "success": True,
        "message": f"{msg}；Local JSON 新增 {new_add_count} 篇{reconcile_msg}；总计 {len(combined_list)} 篇",
        "pulled_count": len(remote_tweets),
        "new_count": new_add_count,
        "removed_count": removed_count,
        "reconciliation": {
            "requested": True,
            "complete": bool(fetch_meta.get("scan_complete")),
            "removed_count": removed_count,
            "removed_ids": removed_ids[:50],
        },
        "fetch": fetch_meta,
        "count": len(combined_list),
        "storage_profile": "local",
        "data": remote_tweets,
    }


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
                "has_ct0": bool(creds.get("ct0")),
                "runtime": "Local Python",
                "storage_profile": "local"
            }).encode("utf-8"))
            return

        if parsed.path == "/api/sync/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "state": "manual",
                "storage_profile": "local",
                "message": "Local Profile 在本机进程运行期间按需同步；Cloud Cron 仅属于 Personal Cloud Profile。"
            }, ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/tweets":
            data, preference_profile = apply_preference_profile(
                load_local_tweets(),
                load_local_feedback(),
            )
            data = enrich_related_hot_many(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "source": "Local JSON",
                "storage_profile": "local",
                "total": len(data),
                "preference_evidence_pairs": int(preference_profile.get("evidence_pairs", 0) or 0),
                "data": data
            }, ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/feed":
            data, preference_profile = apply_preference_profile(
                load_local_tweets(),
                load_local_feedback(),
            )
            data = enrich_related_hot_many(data)
            for item in data:
                item["source_kind"] = "bookmark"
                item["is_bookmark"] = True
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "source": "Local Bookmarks",
                "storage_profile": "local",
                "total": len(data),
                "bookmark_count": len(data),
                "discovery_count": 0,
                "preference_evidence_pairs": int(preference_profile.get("evidence_pairs", 0) or 0),
                "data": data
            }, ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/discovery/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "available": False,
                "enabled": False,
                "storage_profile": "local",
                "message": "Global Discovery 当前只在 Personal Cloud / D1 Profile 运行。"
            }, ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/bookmarks/sync":
            status, payload = sync_local_bookmarks()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/topology/status":
            tweets = load_local_tweets()
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

        if parsed.path == "/api/bookmarks/sync":
            status, payload = sync_local_bookmarks()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            return
        
        if parsed.path == "/api/discovery/run":
            self.send_response(409)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": False,
                "error": "DISCOVERY_CLOUD_ONLY",
                "message": "Global Discovery 需要 Personal Cloud / D1 / Workers AI。"
            }, ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/discovery/action":
            self.send_response(409)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": False,
                "error": "DISCOVERY_CLOUD_ONLY"
            }, ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/feedback":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body.decode("utf-8"))
                ok, msg, event = append_local_feedback(
                    data.get("event_id", ""),
                    data.get("tweet_id", ""),
                    data.get("action", ""),
                    data.get("context", {}),
                )
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": ok,
                    "message": msg,
                    "event": event,
                }, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

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
                if success and action == "delete":
                    existing = load_local_tweets()
                    filtered = [t for t in existing if str(t.get("id")) != str(tweet_id)]
                    save_local_tweets(filtered)

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
                    tweets = load_local_tweets()
                    for t in tweets:
                        if t.get("category") in ("00_云端实时书签", "未分类", "") or "书签" in t.get("category", ""):
                            cat, sub = classify_tweet_multi_tier(t.get("body_raw", "") or t.get("snippet", ""), t.get("title", ""))
                            t["category"] = cat
                            t["sub_category"] = sub
                            classified_count += 1
                    save_local_tweets(tweets)
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
                    tweets = load_local_tweets()
                    projected = [t for t in tweets if t.get("classify_status") == "projected"]
                    for t in tweets:
                        t["classify_status"] = "settled"
                    save_local_tweets(tweets)
                        
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
            SEED_FILE,
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
            with open(SEED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                print("❌ 种子推文数据源格式错误，应为列表")
                sys.exit(1)
            print(f"  ✓ 种子推文数据源有效 (包含 {len(data)} 条推文)")
        except Exception as e:
            print(f"❌ 种子数据解析失败: {e}")
            sys.exit(1)

        # Local Profile 的运行时数据不要求预先存在，但目录必须可创建/写入。
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            probe = DATA_DIR / ".xcollect_write_probe"
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
                f.flush()
                os.fsync(f.fileno())
            probe.unlink(missing_ok=True)
            print(f"  ✓ Local Profile 数据目录可写: {DATA_DIR}")
        except Exception as e:
            print(f"❌ Local Profile 数据目录不可写: {e}")
            sys.exit(1)

        print("✅ 工程卫生冒烟自检完全通过！(All smoke checks passed)")
        sys.exit(0)

    # 正常启动时才初始化/迁移 Local Profile 数据；--check 不要求用户数据预先存在。
    ensure_local_data_file()

    class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    server = ThreadedHTTPServer((CONFIG.host, args.port), CuratedPortalHandler)
    print("=" * 60)
    print(f"🚀 Xcollect Twitter 看板与同步服务已在本地启动: http://{CONFIG.host}:{args.port}")
    print(f"📂 静态托管资产目录: {SERVE_DIR}")
    print(f"📦 Local Profile 数据文件: {DB_FILE}")
    print(f"⚙️  AI 算力引擎: {CONFIG.ai_provider} (模型: {CONFIG.custom_ai_model})")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 服务正常停止")
        server.server_close()

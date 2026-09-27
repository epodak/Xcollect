# -*- coding: utf-8 -*-
"""推文智能分类与规则引擎模块。

职责：
1. 关键词与规则启发式快速分类 (rule_classify_tweet)
2. 动态发现当前系统已有的分类专区 (get_existing_categories)
3. 级联 AI 分类引擎 (ai_classify_tweet):
   - 第一梯队：用户自定义 OpenAI 兼容模型 API (如 DeepSeek, OpenAI)
   - 第二梯队：Cloudflare Workers AI 免费活跃模型矩阵
   - 终极兜底：本地正则关键词规则引擎
"""

import json
import re
from config_loader import CONFIG

try:
    from js import Headers, Object as JsObject, JSON as JsJSON, fetch as js_fetch
except ImportError:
    Headers = None
    JsObject = None
    JsJSON = None
    js_fetch = None

VALID_CATEGORIES = list(CONFIG.default_categories)
WORKERS_AI_CANDIDATE_MODELS = list(CONFIG.workers_ai_models)


def _row_get(row, key: str, default=None):
    """兼容 D1 Python bridge 返回的 dict / JS Record 属性访问。"""
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        value = getattr(row, key)
        return default if value is None else value
    except Exception:
        pass
    try:
        value = row[key]
        return default if value is None else value
    except Exception:
        return default


def rule_classify_tweet(text: str, title: str = "") -> tuple[str, str]:
    """基于规则启发式的双层分类（专区分类, 子分类）。"""
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


async def get_existing_categories(env) -> list[str]:
    """从数据库或默认配置中动态获取当前系统已有分类列表。"""
    cats = list(VALID_CATEGORIES)
    if hasattr(env, "DB"):
        try:
            stmt = env.DB.prepare(
                "SELECT DISTINCT category FROM tweets "
                "WHERE category != '00_云端实时书签' AND category != '未分类' AND category NOT LIKE '%书签%'"
            )
            res = await stmt.all()
            db_cats = [str(_row_get(r, "category", "")) for r in res.results if _row_get(r, "category", "")]
            if db_cats:
                cats = sorted(list(set(cats + db_cats)))
        except Exception as e:
            print("获取已有专区列表失败:", str(e))
    return cats


async def ai_classify_tweet(text: str, title: str = "", existing_categories: list[str] = None, env=None) -> tuple[str, str]:
    """级联 AI 分类引擎：优先自定义大模型 -> Workers AI 矩阵 -> 规则兜底。"""
    if not existing_categories:
        existing_categories = VALID_CATEGORIES

    # 提取干净的已有分类专区供 AI 参考
    active_cats = [c for c in existing_categories if c and "书签" not in c and "未分类" not in c]
    if not active_cats:
        active_cats = list(VALID_CATEGORIES)

    cats_prompt_list = "\n".join([f"- {c}" for c in active_cats])
    content_snippet = (f"标题: {title}\n正文: {text}")[:1400]
    system_prompt = CONFIG.classify_prompt_template.format(existing_categories=cats_prompt_list)

    # 1. 优先梯队：检测用户是否配置了自定义大模型 API (从环境变量或 Secret 提取，非敏感参数来自 config.toml)
    custom_key = ""
    custom_base = CONFIG.custom_ai_base
    custom_model = CONFIG.custom_ai_model
    if env:
        try:
            custom_key = getattr(env, "CUSTOM_AI_API_KEY", "") or getattr(env, "AI_API_KEY", "") or ""
            custom_base = getattr(env, "CUSTOM_AI_API_BASE", "") or getattr(env, "AI_API_BASE", "") or CONFIG.custom_ai_base
            custom_model = getattr(env, "CUSTOM_AI_MODEL", "") or getattr(env, "AI_MODEL", "") or CONFIG.custom_ai_model
        except Exception:
            pass

    if custom_key and js_fetch is not None:
        try:
            req_init = JsObject.new()
            req_init.method = "POST"
            headers = Headers.new()
            headers.set("Content-Type", "application/json")
            headers.set("Authorization", f"Bearer {custom_key}")
            req_init.headers = headers
            req_init.body = json.dumps({
                "model": custom_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content_snippet}
                ],
                "temperature": 0.2,
                "max_tokens": 120
            })
            resp = await js_fetch(f"{custom_base.rstrip('/')}/chat/completions", req_init)
            if resp.status == 200:
                resp_text = await resp.text()
                data = json.loads(resp_text)
                ai_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                m = re.search(r"\{.*?\}", ai_text, re.DOTALL)
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
        except Exception as custom_err:
            print("用户自定义大模型调用失败，自动降级至 Workers AI 免费额度:", str(custom_err))

    # 2. 第二梯队：Cloudflare Workers AI 免费候选模型级联容灾
    if env and hasattr(env, "AI") and JsJSON is not None:
        ai_payload_dict = {
            "prompt": f"<|system|>\n{system_prompt}\n<|user|>\n{content_snippet}\n<|assistant|>\n",
            "temperature": 0.2,
            "max_tokens": 120
        }
        js_payload = JsJSON.parse(json.dumps(ai_payload_dict))

        for model_id in WORKERS_AI_CANDIDATE_MODELS:
            try:
                ai_res = await env.AI.run(model_id, js_payload)
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
                        for ex in active_cats:
                            if ex.lower() == cat.lower() or ex.split("_", 1)[-1].lower() == cat.split("_", 1)[-1].lower():
                                cat = ex
                                break
                        if cat in active_cats:
                            return cat, (sub or "精选研读")
            except Exception as e:
                print(f"Workers AI 模型 [{model_id}] 暂不可用: {str(e)}，尝试下一个候选模型...")
                continue

    # 3. 终极兜底：本地正则关键词规则引擎
    return rule_classify_tweet(text, title)

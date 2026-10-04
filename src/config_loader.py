# -*- coding: utf-8 -*-
"""
src/config_loader.py - 统一工程卫生配置中心 (Agent Relay Hygiene v1.1)

职责：
1. 单一真源加载 config.toml (非敏感工程解耦参数)
2. 单一真源加载 .env (敏感私有凭证)
3. 单一真源加载 prompts/classify_system.txt (外部解耦提示词资产)
4. 杜绝任何业务代码内部硬编码！
"""

import os
import re
from pathlib import Path

# 向上定位工程根目录
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_TOML_PATH = BASE_DIR / "config.toml"
ENV_PATH = BASE_DIR / ".env"
PROMPT_CLASSIFY_PATH = BASE_DIR / "prompts" / "classify_system.txt"
DISCOVERY_QUERIES_PATH = BASE_DIR / "prompts" / "discovery_queries.json"


def parse_simple_toml(content: str) -> dict:
    """零第三方依赖 TOML 子集解析器，支持本项目使用的多行数组。"""
    data = {}
    current_section = None
    pending_array_key = None
    pending_array_target = None
    pending_array_parts = []

    def parse_array_items(raw: str) -> list[str]:
        inner = raw.strip()
        if inner.startswith("["):
            inner = inner[1:]
        if inner.endswith("]"):
            inner = inner[:-1]
        items = []
        for item in inner.split(","):
            cleaned = item.strip().strip('"').strip("'")
            if cleaned:
                items.append(cleaned)
        return items

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if pending_array_key is not None:
            pending_array_parts.append(line)
            if line.endswith("]"):
                raw = " ".join(pending_array_parts)
                pending_array_target[pending_array_key] = parse_array_items(raw)
                pending_array_key = None
                pending_array_target = None
                pending_array_parts = []
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            if current_section not in data:
                data[current_section] = {}
            continue

        if "=" not in line:
            continue

        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        target = data[current_section] if current_section else data

        if v.startswith("["):
            if v.endswith("]"):
                target[k] = parse_array_items(v)
            else:
                pending_array_key = k
                pending_array_target = target
                pending_array_parts = [v]
        elif v.lower() == "true":
            target[k] = True
        elif v.lower() == "false":
            target[k] = False
        elif re.match(r"^-?\d+$", v):
            target[k] = int(v)
        elif re.match(r"^-?\d+\.\d+$", v):
            target[k] = float(v)
        else:
            target[k] = v.strip('"').strip("'")

    if pending_array_key is not None:
        raise ValueError(f"未闭合的 TOML 数组: {pending_array_key}")

    return data


class AppConfig:
    def __init__(self):
        # 1. 加载 config.toml
        toml_content = ""
        # 优先从本地磁盘读取单一真源 config.toml
        if CONFIG_TOML_PATH.exists():
            try:
                with open(CONFIG_TOML_PATH, "r", encoding="utf-8") as f:
                    toml_content = f.read()
            except Exception:
                pass

        # 若处于无本地磁盘的 Cloudflare Worker 边缘环境，从单一真源编译镜像 _config_data.py 加载
        if not toml_content.strip():
            try:
                from _config_data import CONFIG_TOML_CONTENT
                toml_content = CONFIG_TOML_CONTENT
            except ImportError:
                pass

        parsed = parse_simple_toml(toml_content)

        # 基础服务与运行参数
        server_cfg = parsed.get("server", {})
        self.port = int(server_cfg.get("port", 8089))
        self.host = str(server_cfg.get("host", "127.0.0.1"))

        runtime_cfg = parsed.get("runtime", {})
        self.timeout = float(runtime_cfg.get("timeout", 30.0))
        self.max_retries = int(runtime_cfg.get("max_retries", 3))
        self.cache_seconds = int(runtime_cfg.get("cache_seconds", 60))
        self.max_sync_pages = int(runtime_cfg.get("max_sync_pages", 25))

        sync_cfg = parsed.get("sync", {})
        self.reconcile_interval_hours = float(sync_cfg.get("reconcile_interval_hours", 6))

        # Twitter Web API 协议常量 (严格来自 config.toml 单一真源)
        twitter_cfg = parsed.get("twitter", {})
        self.twitter_bearer = str(twitter_cfg.get("bearer_token", ""))
        self.query_id_registry_url = str(twitter_cfg.get("query_id_registry_url", ""))
        self.query_id_bookmarks = str(twitter_cfg.get("query_id_bookmarks", ""))
        fallbacks = twitter_cfg.get("query_id_bookmarks_fallbacks", [])
        self.query_id_bookmarks_fallbacks = list(fallbacks) if isinstance(fallbacks, list) else []
        self.query_id_create = str(twitter_cfg.get("query_id_create", ""))
        self.query_id_delete = str(twitter_cfg.get("query_id_delete", ""))
        self.query_id_search = str(twitter_cfg.get("query_id_search", ""))
        search_fallbacks = twitter_cfg.get("query_id_search_fallbacks", [])
        self.query_id_search_fallbacks = list(search_fallbacks) if isinstance(search_fallbacks, list) else []

        # 分类专区 (严格来自 config.toml 单一真源)
        taxonomy_cfg = parsed.get("taxonomy", {})
        self.default_categories = list(taxonomy_cfg.get("default_categories", []))

        # AI 算力配置 (严格来自 config.toml 单一真源)
        ai_cfg = parsed.get("ai", {})
        self.ai_provider = str(ai_cfg.get("provider", "auto"))
        self.custom_ai_base = str(ai_cfg.get("custom_api_base", "https://api.deepseek.com/v1"))
        self.custom_ai_model = str(ai_cfg.get("custom_model", "deepseek-chat"))
        self.workers_ai_models = list(ai_cfg.get("workers_ai_models", []))

        # Discovery Plane 参数（严格来自 config.toml 单一真源）
        discovery_cfg = parsed.get("discovery", {})
        self.discovery_enabled = bool(discovery_cfg.get("enabled", True))
        self.discovery_interval_hours = float(discovery_cfg.get("interval_hours", 2.0))
        self.discovery_queries_per_run = int(discovery_cfg.get("queries_per_run", 3))
        self.discovery_search_count = int(discovery_cfg.get("search_count", 60))
        self.discovery_max_pages_per_query = int(discovery_cfg.get("max_pages_per_query", 1))
        self.discovery_cheap_penalty_threshold = float(discovery_cfg.get("cheap_penalty_threshold", 0.42))
        self.discovery_min_text_chars = int(discovery_cfg.get("min_text_chars", 36))
        self.discovery_min_final_score = float(discovery_cfg.get("min_final_score", 0.50))
        self.discovery_min_relevance = float(discovery_cfg.get("min_relevance", 0.45))
        self.discovery_min_quality = float(discovery_cfg.get("min_quality", 0.35))
        self.discovery_ai_reject_probability = float(discovery_cfg.get("ai_reject_probability", 0.60))
        self.discovery_ai_batch_max_candidates = int(discovery_cfg.get("ai_batch_max_candidates", 120))
        self.discovery_ai_judge_model = str(
            discovery_cfg.get("ai_judge_model", "@cf/meta/llama-4-scout-17b-16e-instruct")
        )
        self.discovery_daily_limit = int(discovery_cfg.get("daily_limit", 300))
        self.discovery_author_daily_cap = int(discovery_cfg.get("author_daily_cap", 3))
        self.discovery_subcategory_daily_cap = int(discovery_cfg.get("subcategory_daily_cap", 24))
        self.discovery_category_daily_ratio_cap = float(discovery_cfg.get("category_daily_ratio_cap", 0.35))

        # Related-hot 排名与训练 reward（严格来自 config.toml 单一真源）
        ranking_cfg = parsed.get("ranking", {})
        self.related_hot_version = str(ranking_cfg.get("related_hot_version", "rh_v1"))
        self.rank_relevance_weight = float(ranking_cfg.get("relevance_weight", 0.30))
        self.rank_quality_weight = float(ranking_cfg.get("quality_weight", 0.20))
        self.rank_novelty_weight = float(ranking_cfg.get("novelty_weight", 0.15))
        self.rank_velocity_weight = float(ranking_cfg.get("velocity_weight", 0.15))
        self.rank_source_weight = float(ranking_cfg.get("source_weight", 0.10))
        self.rank_freshness_weight = float(ranking_cfg.get("freshness_weight", 0.10))
        self.rank_freshness_half_life_hours = float(ranking_cfg.get("freshness_half_life_hours", 48.0))
        self.rank_velocity_age_exponent = float(ranking_cfg.get("velocity_age_exponent", 0.68))
        self.rank_velocity_scale = float(ranking_cfg.get("velocity_scale", 135.0))

        feedback_cfg = parsed.get("feedback", {})
        self.feedback_weights = {
            "open_detail": float(feedback_cfg.get("open_detail_weight", 0.15)),
            "copy": float(feedback_cfg.get("copy_weight", 0.80)),
            "open_original": float(feedback_cfg.get("open_original_weight", 0.30)),
            "bookmark": float(feedback_cfg.get("bookmark_weight", 1.00)),
            "unbookmark": float(feedback_cfg.get("unbookmark_weight", -1.00)),
            "not_interested": float(feedback_cfg.get("not_interested_weight", -1.20)),
            "hide_author": float(feedback_cfg.get("hide_author_weight", -2.00)),
        }

        # 拓扑重整化 (严格来自 config.toml 单一真源)
        topology_cfg = parsed.get("topology", {})
        self.renormalize_threshold = int(topology_cfg.get("renormalize_threshold", 30))
        self.max_cluster_ratio = float(topology_cfg.get("max_cluster_ratio", 0.40))

        # 2. 读取解耦的 Prompt 外部资产 (单一真源来自 prompts/classify_system.txt)
        self.classify_prompt_template = ""
        if PROMPT_CLASSIFY_PATH.exists():
            try:
                with open(PROMPT_CLASSIFY_PATH, "r", encoding="utf-8") as f:
                    self.classify_prompt_template = f.read().strip()
            except Exception:
                pass

        if not self.classify_prompt_template:
            try:
                from _config_data import PROMPT_CLASSIFY_CONTENT
                self.classify_prompt_template = PROMPT_CLASSIFY_CONTENT.strip()
            except ImportError:
                pass

        # Discovery query seeds are a business asset, mirrored into Worker code
        # exactly like prompts so edge runtime never depends on a writable disk.
        discovery_queries_raw = "[]"
        if DISCOVERY_QUERIES_PATH.exists():
            try:
                with open(DISCOVERY_QUERIES_PATH, "r", encoding="utf-8") as f:
                    discovery_queries_raw = f.read()
            except Exception:
                pass
        if not discovery_queries_raw.strip() or discovery_queries_raw.strip() == "[]":
            try:
                from _config_data import DISCOVERY_QUERIES_CONTENT
                discovery_queries_raw = DISCOVERY_QUERIES_CONTENT
            except ImportError:
                pass
        try:
            import json as _json
            parsed_queries = _json.loads(discovery_queries_raw or "[]")
            self.discovery_queries = parsed_queries if isinstance(parsed_queries, list) else []
        except Exception:
            self.discovery_queries = []

        # 3. 读取本地私有敏感凭据 (.env)
        self.x_auth_token = os.environ.get("X_AUTH_TOKEN", "")
        self.x_ct0 = os.environ.get("X_CT0", "")
        self.custom_ai_api_key = os.environ.get("CUSTOM_AI_API_KEY", "")

        if ENV_PATH.exists():
            try:
                with open(ENV_PATH, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k == "X_AUTH_TOKEN" and not self.x_auth_token:
                                self.x_auth_token = v
                            elif k == "X_CT0" and not self.x_ct0:
                                self.x_ct0 = v
                            elif k == "CUSTOM_AI_API_KEY" and not self.custom_ai_api_key:
                                self.custom_ai_api_key = v
            except Exception:
                pass


# 全局单例配置实例
CONFIG = AppConfig()

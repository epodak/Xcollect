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


def parse_simple_toml(content: str) -> dict:
    """零第三方依赖的极简 TOML 解析器 (适配标准 Python 与 Pyodide 环境)"""
    data = {}
    current_section = None

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            if current_section not in data:
                data[current_section] = {}
            continue

        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()

            target = data[current_section] if current_section else data

            if v.startswith("[") and v.endswith("]"):
                inner = v[1:-1].strip()
                items = []
                if inner:
                    for item in re.split(r",\s*", inner):
                        cleaned = item.strip().strip('"').strip("'")
                        if cleaned:
                            items.append(cleaned)
                target[k] = items
            elif v.lower() == "true":
                target[k] = True
            elif v.lower() == "false":
                target[k] = False
            elif v.isdigit():
                target[k] = int(v)
            elif re.match(r"^\d+\.\d+$", v):
                target[k] = float(v)
            else:
                target[k] = v.strip('"').strip("'")

    return data


class AppConfig:
    def __init__(self):
        # 1. 加载 config.toml
        toml_content = ""
        if CONFIG_TOML_PATH.exists():
            try:
                with open(CONFIG_TOML_PATH, "r", encoding="utf-8") as f:
                    toml_content = f.read()
            except Exception:
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

        # Twitter Web API 协议常量
        twitter_cfg = parsed.get("twitter", {})
        self.twitter_bearer = str(twitter_cfg.get("bearer_token", ""))
        self.query_id_bookmarks = str(twitter_cfg.get("query_id_bookmarks", ""))
        self.query_id_create = str(twitter_cfg.get("query_id_create", ""))
        self.query_id_delete = str(twitter_cfg.get("query_id_delete", ""))

        # 分类专区
        taxonomy_cfg = parsed.get("taxonomy", {})
        self.default_categories = taxonomy_cfg.get("default_categories", [
            "01_人工智能与Agent",
            "02_技术架构与开发",
            "03_开源精选与工具",
            "04_产品设计与思考",
            "05_前沿资讯与研读"
        ])

        # AI 算力配置
        ai_cfg = parsed.get("ai", {})
        self.ai_provider = str(ai_cfg.get("provider", "auto"))
        self.custom_ai_base = str(ai_cfg.get("custom_api_base", "https://api.deepseek.com/v1"))
        self.custom_ai_model = str(ai_cfg.get("custom_model", "deepseek-chat"))
        self.workers_ai_models = ai_cfg.get("workers_ai_models", [
            "@cf/meta/llama-3.1-8b-instruct-fast",
            "@cf/meta/llama-3.2-3b-instruct",
            "@cf/meta/llama-3.2-1b-instruct"
        ])

        # 拓扑重整化
        topology_cfg = parsed.get("topology", {})
        self.renormalize_threshold = int(topology_cfg.get("renormalize_threshold", 30))
        self.max_cluster_ratio = float(topology_cfg.get("max_cluster_ratio", 0.40))

        # 2. 读取解耦的 Prompt 外部资产
        self.classify_prompt_template = ""
        if PROMPT_CLASSIFY_PATH.exists():
            try:
                with open(PROMPT_CLASSIFY_PATH, "r", encoding="utf-8") as f:
                    self.classify_prompt_template = f.read().strip()
            except Exception:
                pass
        if not self.classify_prompt_template:
            # 契约安全保护：若资产文件无法读取时的备选模版
            self.classify_prompt_template = (
                "你是一个科技前沿推文的自适应知识拓扑与分类专家。\n"
                "请阅读推文内容，判断其所属领域专区（category）并提取一个具体的二级子领域（sub_category，4-10字）。\n\n"
                "【目前已有的专区列表】：\n{existing_categories}\n\n"
                "【分类与自适应原则】：\n"
                "1. 优先复用：必须从上述【已有专区列表】中选择最匹配的专区名称，保持知识拓扑基准惯性。\n"
                "2. 细分提炼：为推文提炼一个 4-10 字的 sub_category（如：Coding Agent/智能编程、Prompt与Skills工程、云原生与边缘计算等）。\n\n"
                "必须严格只输出 JSON 对象：\n"
                "{{\"category\": \"专区名称\", \"sub_category\": \"二级细分标签\"}}"
            )

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

# -*- coding: utf-8 -*-
"""根目录直通配置导入入口"""
from src.config_loader import CONFIG, AppConfig, parse_simple_toml

__all__ = ["CONFIG", "AppConfig", "parse_simple_toml"]

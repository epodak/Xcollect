#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-fast guard for Personal Cloud deployments.

Xcollect's Cloud Profile is background-sync-first. Having an on_scheduled handler
without a Wrangler Cron Trigger would silently regress the product back to
"open the web page and click sync".
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRANGLER = ROOT / "wrangler.jsonc"

if not WRANGLER.exists():
    print("❌ 缺少私有 wrangler.jsonc。")
    print("   先执行: cp wrangler.example.jsonc wrangler.jsonc")
    sys.exit(1)

text = WRANGLER.read_text(encoding="utf-8")

cron_match = re.search(
    r'"crons"\s*:\s*\[\s*"([^"]+)"',
    text,
    flags=re.MULTILINE,
)

if not cron_match:
    print("❌ Personal Cloud 未配置 Cron Trigger。")
    print("   Xcollect Cloud Profile 的正常同步不应依赖打开网页或手动点击。")
    print("")
    print('   请在 wrangler.jsonc 顶层加入：')
    print('   "triggers": {')
    print('     "crons": ["*/15 * * * *"]')
    print('   },')
    print("")
    print("   然后重新运行: pnpm run deploy")
    sys.exit(1)

print(f"✓ Cloud background sync cron configured: {cron_match.group(1)}")

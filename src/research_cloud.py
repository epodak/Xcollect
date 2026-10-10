# -*- coding: utf-8 -*-
"""Cloudflare Workers AI 的研究服务适配器；无静默模型调用。"""
from __future__ import annotations

import json

try:
    from .decision import evaluate_bookmark
    from .research import run_research
except ImportError:
    from decision import evaluate_bookmark
    from research import run_research

try:
    from js import JSON as JsJSON
except ImportError:
    JsJSON = None


def decode_model_result(value):
    if isinstance(value, dict):
        return value
    if JsJSON is None:
        raise RuntimeError("无法读取生成模型响应")
    return json.loads(str(JsJSON.stringify(value)))


async def research_with_workers_ai(env, question, candidates, *,
                                   decision_model, generation_model,
                                   max_candidates=8, profile="bookmarks"):
    if not hasattr(env, "AI") or getattr(env, "AI") is None:
        raise RuntimeError("Cloudflare AI 绑定缺失")

    async def judge(item, asked_question):
        return await evaluate_bookmark(env, item, decision_model, asked_question)

    async def generate(messages):
        request = {
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 1600,
        }
        payload = JsJSON.parse(json.dumps(request, ensure_ascii=False)) if JsJSON is not None else request
        response = decode_model_result(await env.AI.run(generation_model, payload))
        text = response.get("response")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("生成模型没有返回有效的中文综述")
        return text

    return await run_research(
        question, candidates, judge, generate, model_name=generation_model,
        max_candidates=max_candidates, profile=profile,
    )

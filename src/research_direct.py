# -*- coding: utf-8 -*-
"""CLI 直接调用 Cloudflare typed decision + Workers AI 或 DeepSeek 生成。

不需要先部署 Xcollect Worker。使用最小权限的 API Token，绝不输出密钥。
与 Worker 的研究链路共用 src.research.run_research。
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .decision import make_request, parse_result
from .research import run_research


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 阻止代理/重定向将 Cloudflare 或 DeepSeek Token 送到其他域名。
        return None


def _post_json(url: str, token: str, payload: dict) -> dict:
    if not token:
        raise ValueError("缺少 AI 提供商 API Token")
    request = Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=90) as response:
            reply = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"模型接口 HTTP {error.code}，请检查令牌权限/额度") from None
    except URLError as error:
        raise RuntimeError("模型接口网络不可用") from None
    if not isinstance(reply, dict):
        raise RuntimeError("模型接口返回非 JSON 对象")
    if reply.get("success") is False:
        raise RuntimeError("模型接口报告调用失败；检查权限或额度")
    return reply.get("result", reply)


async def research_direct(question: str, candidates: list[dict], *,
                          judge_model: str, generation_model: str,
                          max_candidates: int, account_id: str,
                          cloudflare_token: str, generator: str = "workers",
                          deepseek_key: str = "", deepseek_base: str = "",
                          deepseek_model: str = "deepseek-chat",
                          allow_jev: bool = False, profile: str = "local_bookmarks") -> dict:
    if judge_model == "jev" and not allow_jev:
        raise ValueError("Jev 按量付费：直接调用必须显式提供 --allow-jev")
    if not account_id or not cloudflare_token:
        raise ValueError("直接调用需要 CLOUDFLARE_ACCOUNT_ID 与 CLOUDFLARE_API_TOKEN")
    if not all(ch.isalnum() or ch in "_-" for ch in account_id) or len(account_id) > 80:
        raise ValueError("Cloudflare Account ID 格式不正确")

    api = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run"

    async def judge(item, asked_question):
        model_id, request = make_request(item, judge_model, asked_question)
        if judge_model == "jev":
            response = _post_json(api, cloudflare_token, {"model": model_id, "input": request})
        else:
            response = _post_json(api + "/" + model_id, cloudflare_token, request)
        return {"model_id": model_id, **parse_result(response)}

    async def generate(messages):
        if generator == "deepseek":
            if not deepseek_key or not deepseek_base.startswith("https://"):
                raise ValueError("DeepSeek 模式需要有效的 CUSTOM_AI_API_KEY 与 HTTPS 端点")
            response = _post_json(
                deepseek_base.rstrip("/") + "/chat/completions", deepseek_key,
                {"model": deepseek_model, "messages": messages, "temperature": 0.2,
                 "max_tokens": 1800},
            )
            text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        elif generator == "workers":
            response = _post_json(
                api + "/" + generation_model, cloudflare_token,
                {"messages": messages, "temperature": 0.2, "max_tokens": 1600},
            )
            text = response.get("response", "")
        else:
            raise ValueError("未知生成服务类型")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("生成模型没有返回正文")
        return text

    return await run_research(
        question, candidates, judge, generate,
        model_name=deepseek_model if generator == "deepseek" else generation_model,
        max_candidates=max_candidates, profile=profile,
    )

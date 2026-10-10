# -*- coding: utf-8 -*-
"""Optional, explicitly invoked structured decision models for bookmark triage.

This is not summarization or semantic retrieval. No writes to source records.
The caller is responsible for authentication and rate limiting. AI errors are
reported, never silently converted into invented rule-based probabilities.
"""
from __future__ import annotations

import json

try:
    from js import JSON as JsJSON
except ImportError:  # CPython tests / Local Profile
    JsJSON = None

MODELS = {
    "clef-flash": ("@cf/cloudflare/clef-flash", "clef-flash"),
    "clef": ("@cf/cloudflare/clef", "clef"),
    "jev": ("typesafe/jev", None),
}


def make_request(item: dict, model: str = "clef-flash") -> tuple[str, dict]:
    if model not in MODELS:
        raise ValueError("Unknown decision model")
    model_id, model_selector = MODELS[model]
    raw = str(item.get("body_raw") or item.get("snippet") or "")
    state = {
        "source": "user_saved_x_bookmark",
        "title": str(item.get("title") or "")[:300],
        "text": raw[:6000],
        "category": str(item.get("category") or "")[:100],
        "author": str(item.get("author") or "")[:150],
    }
    questions = {
        "technical_content": {
            "type": "noul",
            "instructions": "Does the source include concrete technical information rather than only promotion or hype?",
            "criteria": {
                "true": "Includes specific methods, architecture, measurements, code, or testable claims",
                "false": "Primarily promotional, vague, or unrelated",
            },
        },
        "research_value": {
            "type": "score",
            "instructions": "How useful is this source as evidence for technical research? Judge the source, not the reader.",
            "criteria": [
                "Low: no verifiable technical content",
                "Medium: some technical details but substantial gaps",
                "High: specific and independently checkable technical details",
            ],
        },
        "content_type": {
            "type": "choice",
            "instructions": "What best describes the content?",
            "criteria": {
                "announcement": "Product/model release news or announcements",
                "tutorial": "Instructions, reproducible workflows, or code examples",
                "research": "Experiment, benchmark, technical analysis or a paper",
                "opinion": "Personal interpretation, speculation or discussion",
                "other": "None of the above",
            },
        },
    }
    request = {"state": state, "questions": questions}
    if model_selector is not None:
        request["model"] = model_selector
    return model_id, request


def parse_result(result) -> dict:
    if isinstance(result, dict):
        raw = result
    elif JsJSON is not None:
        # Workers AI may return a JS object proxy.
        raw = json.loads(str(JsJSON.stringify(result)))
    else:
        raise RuntimeError("AI response is not JSON-compatible")
    answers = raw.get("answers")
    if not isinstance(answers, dict):
        raise RuntimeError("Decision model returned no structured answers")
    return {"answers": answers, "usage": raw.get("usage", {}), "reported_model": raw.get("model", "")}


async def evaluate_bookmark(env, item: dict, model: str = "clef-flash") -> dict:
    if not hasattr(env, "AI") or getattr(env, "AI") is None:
        raise RuntimeError("Cloudflare AI binding is unavailable")
    model_id, request = make_request(item, model)
    payload = JsJSON.parse(json.dumps(request)) if JsJSON is not None else request
    result = await env.AI.run(model_id, payload)
    return {"model_id": model_id, "source_id": str(item.get("id")), **parse_result(result)}

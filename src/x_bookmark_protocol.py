# -*- coding: utf-8 -*-
"""Pure, credential-free contract for X Web bookmark mutations.

X Web's private GraphQL API is not a stable, supported service contract.
Keep protocol decisions testable without HTTP, cookies or Worker JS runtime.
"""
import json
import re

_OPERATIONS = {"create": "CreateBookmark", "delete": "DeleteBookmark"}
_QID = re.compile(r"^[A-Za-z0-9_-]{8,100}$")


def operation_name(action):
    if action not in _OPERATIONS:
        raise ValueError("unsupported bookmark action")
    return _OPERATIONS[action]


def query_id_candidates(action, registry, fallback):
    """Only trust exact operation/method/path pairs; keep reviewed fallback."""
    operation = operation_name(action)
    ids = []
    if isinstance(registry, dict):
        record = registry.get(operation)
        if isinstance(record, dict):
            query_id = record.get("queryId")
            path = record.get("@path")
            method = str(record.get("@method", "")).upper()
            variables = record.get("variables", {})
            if (isinstance(query_id, str) and _QID.fullmatch(query_id)
                    and path == f"/i/api/graphql/{query_id}/{operation}"
                    and method == "POST"
                    and isinstance(variables, dict) and "tweet_id" in variables):
                ids.append(query_id)
    if isinstance(fallback, str) and _QID.fullmatch(fallback) and fallback not in ids:
        ids.append(fallback)
    return ids


def mutation_payload(tweet_id, query_id):
    """Use X's documented *web* POST envelope (not the official OAuth v2 API)."""
    identifier = str(tweet_id).strip()
    if not identifier.isascii() or not identifier.isdigit() or len(identifier) > 25:
        raise ValueError("invalid numeric tweet_id")
    if not isinstance(query_id, str) or not _QID.fullmatch(query_id):
        raise ValueError("invalid GraphQL queryId")
    return json.dumps({
        "variables": {"tweet_id": identifier},
        "queryId": query_id,
    }, separators=(",", ":"))


def interpret_mutation_response(action, status, body, query_id):
    """Never mark an X bookmark as saved unless X returned valid success data."""
    operation = operation_name(action)
    raw = body if isinstance(body, str) else ""
    if status == 404:
        message = (
            f"X {operation} HTTP 404 (queryId={query_id}; "
            "X 网页私有接口拒绝请求。可能是操作 ID 失效或需要有效的 "
            "x-client-transaction-id/其他会话校验；单靠更换凭证未必有效)。"
        )
        return False, message
    if status in (401, 403):
        return False, f"X {operation} HTTP {status}：凭证/CSRF/权限校验失败"
    if status == 429:
        return False, f"X {operation} HTTP 429：X 限流，请稍后再试"
    if status not in (200, 201):
        return False, f"X {operation} HTTP {status}：上游接口失败（queryId={query_id}）"
    try:
        result = json.loads(raw)
    except (ValueError, TypeError):
        return False, f"X {operation} HTTP {status}：上游未返回 JSON，不能确认操作成功"
    if not isinstance(result, dict):
        return False, f"X {operation}：无效的 GraphQL 响应结构"
    errors = result.get("errors")
    if errors:
        first = errors[0] if isinstance(errors, list) else errors
        message = first.get("message", "unknown GraphQL error") if isinstance(first, dict) else str(first)
        return False, f"X {operation} GraphQL 错误: {str(message)[:180]}"
    # Some responses contain HTTP 200 but a null/empty data payload. Fail closed.
    data = result.get("data")
    if not isinstance(data, dict) or not data:
        return False, f"X {operation}：缺少成功数据，未确认收藏状态"
    return True, f"成功同步至 X: {operation} OK"

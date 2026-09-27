# -*- coding: utf-8 -*-
"""Cloud Profile bookmark synchronization application service.

Trigger-agnostic by design:
- HTTP manual sync
- Cloudflare Cron scheduled sync
- future Queue / Workflow / admin triggers

All triggers call the same application service so the sync semantics cannot drift.
"""

from datetime import datetime, timedelta, timezone

from config_loader import CONFIG
from classifier import get_existing_categories
from twitter import fetch_remote_bookmarks
from storage import (
    get_known_tweet_ids,
    get_storage_status,
    get_sync_status,
    load_tweets,
    reconcile_removed_bookmarks,
    save_sync_status,
    save_tweets,
)


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _reconciliation_due(previous: dict) -> bool:
    last_attempt = _parse_iso(previous.get("last_reconcile_attempt_at"))
    if last_attempt is None:
        return True
    return (
        datetime.now(timezone.utc) - last_attempt
        >= timedelta(hours=float(CONFIG.reconcile_interval_hours))
    )


async def _record_failure(env, previous: dict, trigger: str, code: str, message: str, extra=None):
    payload = {
        "success": False,
        "state": "failed",
        "trigger": trigger,
        "error": code,
        "message": message,
        "last_attempt_at": _utc_now_iso(),
        "last_success_at": previous.get("last_success_at"),
        "last_reconcile_attempt_at": previous.get("last_reconcile_attempt_at"),
        "last_reconcile_success_at": previous.get("last_reconcile_success_at"),
    }
    if extra:
        payload.update(extra)
    await save_sync_status(env, payload)
    return payload


async def perform_cloud_sync(env, trigger: str = "manual", force_reconcile: bool = False):
    """Run one complete X -> selected cloud storage -> read-back transaction.

    Returns:
        (http_like_status_code, payload)
    """
    previous = await get_sync_status(env)
    started_at = _utc_now_iso()
    full_scan = bool(force_reconcile or _reconciliation_due(previous))

    await save_sync_status(env, {
        "success": True,
        "state": "running",
        "trigger": trigger,
        "started_at": started_at,
        "last_attempt_at": started_at,
        "last_success_at": previous.get("last_success_at"),
        "last_reconcile_attempt_at": previous.get("last_reconcile_attempt_at"),
        "last_reconcile_success_at": previous.get("last_reconcile_success_at"),
        "sync_mode": "reconcile" if full_scan else "incremental",
        "message": "完整对账进行中" if full_scan else "增量同步进行中",
    })

    auth_token = getattr(env, "X_AUTH_TOKEN", "") or ""
    ct0 = getattr(env, "X_CT0", "") or ""
    if not auth_token or not ct0:
        payload = await _record_failure(
            env,
            previous,
            trigger,
            "X_CREDENTIALS_MISSING",
            "Worker Secret 未配置 X_AUTH_TOKEN / X_CT0。",
        )
        return 400, payload

    try:
        existing_cats = await get_existing_categories(env)
        known_ids = await get_known_tweet_ids(env)
    except Exception as storage_err:
        payload = await _record_failure(
            env,
            previous,
            trigger,
            "STORAGE_PRECHECK_FAILED",
            str(storage_err),
        )
        return 500, payload

    try:
        pulled, fetch_meta = await fetch_remote_bookmarks(
            auth_token,
            ct0,
            CONFIG.max_sync_pages,
            existing_cats,
            env,
            known_ids=known_ids,
            full_scan=full_scan,
        )
    except Exception as sync_err:
        payload = await _record_failure(
            env,
            previous,
            trigger,
            "X_SYNC_FAILED",
            str(sync_err),
        )
        return 502, payload

    saved, storage_msg, storage_meta = await save_tweets(env, pulled)
    storage_status = await get_storage_status(env)

    if not saved:
        payload = await _record_failure(
            env,
            previous,
            trigger,
            "PERSISTENCE_FAILED",
            f"X 已拉取 {len(pulled)} 条，但持久化失败：{storage_msg}",
            {
                "pulled_count": len(pulled),
                "fetch": fetch_meta,
                "storage": storage_meta,
                "storage_status": storage_status,
            },
        )
        return 500, payload

    reconciliation = {
        "requested": full_scan,
        "complete": False,
        "removed_count": 0,
        "removed_ids": [],
    }
    reconcile_attempt_at = previous.get("last_reconcile_attempt_at")
    reconcile_success_at = previous.get("last_reconcile_success_at")

    if full_scan:
        reconcile_attempt_at = _utc_now_iso()
        if fetch_meta.get("scan_complete"):
            authoritative_order = [
                str(item.get("id"))
                for item in pulled
                if item.get("id")
            ]
            reconciliation.update(
                await reconcile_removed_bookmarks(env, authoritative_order)
            )
            reconciliation["complete"] = True
            reconcile_success_at = reconcile_attempt_at
        else:
            reconciliation["warning"] = (
                "完整对账未到达 X Bookmarks 时间线末尾；为避免误删，本轮不处理缺失 ID。"
            )

    # Read back through the same repository path consumed by the UI.
    readback = await load_tweets(env, bypass_cache=True)
    readback_head_ids = [
        str(item.get("id"))
        for item in (readback.get("data") or [])[:10]
        if item.get("id")
    ]
    expected_head_ids = [
        str(item.get("id"))
        for item in pulled[:10]
        if item.get("id")
    ]

    storage_meta["readback_head_ids"] = readback_head_ids
    storage_meta["readback_total"] = int(readback.get("total", 0) or 0)
    storage_meta["readback_source"] = readback.get("source", "")
    storage_meta["head_order_matches"] = (
        not expected_head_ids
        or readback_head_ids[:len(expected_head_ids)] == expected_head_ids
    )

    if not readback.get("success") or not storage_meta["head_order_matches"]:
        payload = await _record_failure(
            env,
            previous,
            trigger,
            "READBACK_MISMATCH",
            "X 数据已持久化，但主存储回读结果与 X 收藏顺序不一致。",
            {
                "pulled_count": len(pulled),
                "fetch": fetch_meta,
                "storage": storage_meta,
                "storage_status": storage_status,
            },
        )
        return 500, payload

    completed_at = _utc_now_iso()
    removed_count = int(reconciliation.get("removed_count", 0) or 0)
    reconcile_suffix = ""
    if full_scan and reconciliation.get("complete"):
        reconcile_suffix = f"；完整对账移除 {removed_count} 条 X 已取消收藏"
    elif full_scan:
        reconcile_suffix = "；完整对账未完成，未执行删除"

    payload = {
        "success": True,
        "state": "success",
        "trigger": trigger,
        "sync_mode": "reconcile" if full_scan else "incremental",
        "started_at": started_at,
        "completed_at": completed_at,
        "last_attempt_at": completed_at,
        "last_success_at": completed_at,
        "last_reconcile_attempt_at": reconcile_attempt_at,
        "last_reconcile_success_at": reconcile_success_at,
        "message": f"X 拉取 {len(pulled)} 条；{storage_msg}{reconcile_suffix}",
        "pulled_count": len(pulled),
        "new_count": fetch_meta.get("discovered_new_count", storage_meta.get("d1_written", 0)),
        "removed_count": removed_count,
        "reconciliation": reconciliation,
        "fetch": fetch_meta,
        "storage": storage_meta,
        "storage_status": storage_status,
        "storage_profile": storage_meta.get("backend") or storage_status.get("active_backend"),
    }
    await save_sync_status(env, payload)
    return 200, payload

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static acceptance checks for Feed scope / Discovery state-machine contracts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

app = (ROOT / "public" / "js" / "app.js").read_text(encoding="utf-8")
render = (ROOT / "public" / "js" / "render.js").read_text(encoding="utf-8")
entry = (ROOT / "src" / "entry.py").read_text(encoding="utf-8")
discovery = (ROOT / "src" / "discovery.py").read_text(encoding="utf-8")
preferences = (ROOT / "src" / "preferences.py").read_text(encoding="utf-8")
sync_service = (ROOT / "src" / "sync_service.py").read_text(encoding="utf-8")

# Empty-state truth: filtering to zero is not the same as clearing the Discovery Inbox.
assert 'activeFeedScope === "discovery" && activeScopeTotal === 0' in app
assert "今日相关热点已全部阅毕" in app

# Infinite scroll must never overwrite the scope-aware count projection.
assert "(总 ${tweets.length})" not in app
assert "function updateVisibleCountBadge()" in app

# False-positive × is separate from semantic dislike.
assert "rejectDiscoveryCandidate" in app
assert 'recordTweetFeedback(tweetId, "reject_candidate"' in app
assert 'feedback_scope: "discovery_quality"' in app
assert "card-reject-candidate" in render
assert "不会降低你对该话题的兴趣" in render
assert 'feedback_scope")) == "discovery_quality"' in preferences

# Candidate promotion is two-phase: X accepts -> pending -> bookmark sync -> durable saved.
assert '"saved_pending"' in app
assert 'set_candidate_state(env, tweet_id, "saved_pending")' in entry
assert 'trigger="bookmark-create"' in entry
assert "reconcile_candidate_promotions" in sync_service
assert "'saved_pending'" in discovery

# Manual reject is terminal and reply leakage is gated before expensive AI.
assert '"reject_candidate": "rejected"' in entry
assert 'action == "reject_candidate"' in discovery
assert 'if item.get("is_reply")' in discovery
assert '"reply"' in discovery
assert "'rejected'" in discovery

print("feed/discovery contract checks: OK")

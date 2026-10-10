/**
 * Twitter Curated Portal - API Client
 * 统一后端 REST API 请求封装 (Cloudflare Workers / Local Python Server)
 */
const api = {
  // 获取 X 凭证配置状态
  async getAuthStatus() {
    const resp = await fetch("/api/auth/status", { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  },

  // 保存 X 凭证：本地 Server 支持；Cloudflare Worker 会明确返回不支持运行时写 Secret
  async saveAuth(authToken, ct0) {
    const resp = await fetch("/api/auth/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auth_token: authToken, ct0: ct0 })
    });
    let res;
    const contentType = resp.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      res = await resp.json();
    } else {
      const rawText = await resp.text();
      res = { success: resp.ok, message: rawText };
    }
    return { ok: resp.ok, data: res };
  },

  // 直接探测 D1/KV 持久化状态
  async getStorageStatus() {
    const resp = await fetch("/api/storage/status", { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  },

  // 获取最近一次自动/手动同步运行状态
  async getSyncStatus() {
    const resp = await fetch("/api/sync/status", { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  },

  // 获取阅读 Feed：durable bookmarks + 当日 discovery daily_feed。
  // /api/tweets 仍保留为纯书签知识库端点。
  async getTweets(fresh = false) {
    const url = fresh ? `/api/feed?fresh=1&_=${Date.now()}` : "/api/feed";
    const resp = await fetch(url, fresh ? { cache: "no-store" } : undefined);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  },

  // 从 X 线上书签同步；POST 表达“远端读取 + 本地持久化”的副作用
  async syncBookmarks() {
    const resp = await fetch("/api/bookmarks/sync", {
      method: "POST",
      cache: "no-store"
    });
    const contentType = resp.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      return await resp.json();
    }
    const rawText = await resp.text();
    return {
      success: false,
      error: `HTTP_${resp.status}`,
      message: rawText.slice(0, 300)
    };
  },

  // 记录训练信号。失败时进入浏览器小型待重试队列，不阻塞主交互。
  async recordFeedback(tweetId, action, context = {}) {
    // The X Bookmark timeline, not a browser click, owns terminal labels.
    if (action === "bookmark" || action === "unbookmark") {
      return { success: false, skipped: true, reason: "x_sync_only" };
    }
    const eventId = (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function")
      ? globalThis.crypto.randomUUID()
      : `fb_${Date.now()}_${Math.random().toString(36).slice(2)}`;

    const payload = {
      event_id: eventId,
      tweet_id: String(tweetId || ""),
      action: String(action || ""),
      context: context || {}
    };

    const send = async (body) => {
      const resp = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        keepalive: true
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return await resp.json();
    };

    try {
      return await send(payload);
    } catch (err) {
      try {
        const key = "xcollect_feedback_queue_v1";
        const queued = JSON.parse(localStorage.getItem(key) || "[]");
        queued.push(payload);
        localStorage.setItem(key, JSON.stringify(queued.slice(-200)));
      } catch (e) {}
      throw err;
    }
  },

  async flushFeedbackQueue() {
    const key = "xcollect_feedback_queue_v1";
    let queued = [];
    try {
      queued = JSON.parse(localStorage.getItem(key) || "[]");
    } catch (e) {
      queued = [];
    }
    if (!Array.isArray(queued) || queued.length === 0) return { flushed: 0 };

    // Old browser builds could enqueue synthetic bookmark feedback. Drop it;
    // retrying those events would fabricate conversions after the policy switch.
    const eligible = queued.filter(item => item && item.action !== "bookmark" && item.action !== "unbookmark");
    const batch = eligible.slice(0, 25);
    const remaining = eligible.slice(25);
    let flushed = 0;
    for (const payload of batch) {
      try {
        const resp = await fetch("/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          keepalive: true
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        flushed += 1;
      } catch (err) {
        remaining.push(payload);
      }
    }
    try {
      localStorage.setItem(key, JSON.stringify(remaining));
    } catch (e) {}
    return { flushed, remaining: remaining.length };
  },

  async getDiscoveryStatus() {
    const resp = await fetch("/api/discovery/status", { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  },

  async getWatches() {
    const r = await fetch("/api/watch", {cache:"no-store"});
    return await r.json();
  },

  async createWatch(topic) {
    const r = await fetch("/api/watch", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(topic)});
    return {ok:r.ok,data:await r.json()};
  },

  async setWatchState(id,state) {
    const r = await fetch("/api/watch/state", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id,state})});
    return {ok:r.ok,data:await r.json()};
  },

  async getWatchFeed(id) {
    const r = await fetch("/api/watch/feed?id="+encodeURIComponent(id),{cache:"no-store"});
    return {ok:r.ok,data:await r.json()};
  },

  async runDiscovery() {
    const resp = await fetch("/api/discovery/run", {
      method: "POST",
      cache: "no-store"
    });
    const data = await resp.json();
    return { ok: resp.ok, data };
  },

  async discoveryAction(tweetId, action) {
    const resp = await fetch("/api/discovery/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tweet_id: String(tweetId || ""), action: String(action || "") })
    });
    const data = await resp.json();
    return { ok: resp.ok, data };
  },

  // 触发边缘 AI 深度分类
  async classifyBookmarks() {
    const resp = await fetch("/api/bookmarks/classify", { method: "POST" });
    return await resp.json();
  }
};

window.api = api;


window.recordTweetFeedback = function(tweetId, action, context = {}) {
  if (!tweetId || !action) return;
  const item = Array.isArray(window.tweets)
    ? window.tweets.find(tweet => String(tweet.id) === String(tweetId))
    : null;
  const mergedContext = Object.assign({
    surface: context.surface || "feed",
    sort_mode: window.sortMode || "related_hot_desc",
    category: item ? (item.category || "") : "",
    sub_category: item ? (item.sub_category || "") : "",
    username: item ? (item.username || "") : "",
    author: item ? (item.author || "") : "",
    discovery_query: item ? (item.discovery_query || "") : "",
    discovery_source: item ? (item.discovery_source || "") : "",
    is_reply: item ? Boolean(item.is_reply) : false,
    reply_to_username: item ? (item.reply_to_username || "") : ""
  }, context || {});

  api.recordFeedback(tweetId, action, mergedContext).catch(() => {
    // Preference telemetry must never break reading/copy/bookmark interactions.
  });
};

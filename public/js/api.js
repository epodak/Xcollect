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

  // 获取聚合列表；fresh=true 时绕过 HTTP 缓存用于同步后的持久化层 read-back
  async getTweets(fresh = false) {
    const url = fresh ? `/api/tweets?fresh=1&_=${Date.now()}` : "/api/tweets";
    const resp = await fetch(url, fresh ? { cache: "no-store" } : undefined);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  },

  // X 书签添加/移除切换
  async toggleBookmark(tweetId, action) {
    const resp = await fetch("/api/bookmark/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tweet_id: tweetId, action: action })
    });
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

  // 触发边缘 AI 深度分类
  async classifyBookmarks() {
    const resp = await fetch("/api/bookmarks/classify", { method: "POST" });
    return await resp.json();
  }
};

window.api = api;

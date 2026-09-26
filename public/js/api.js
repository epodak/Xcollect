/**
 * Twitter Curated Portal - API Client
 * 统一后端 REST API 请求封装 (Cloudflare Workers / Local Python Server)
 */
const api = {
  // 获取 X 凭证配置状态
  async getAuthStatus() {
    const resp = await fetch("/api/auth/status");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  },

  // 保存 X 凭证 (auth_token & ct0)
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

  // 获取推文聚合列表 (D1 数据库)
  async getTweets() {
    const resp = await fetch("/api/tweets");
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

  // 从 X 线上书签增量同步
  async syncBookmarks() {
    const resp = await fetch("/api/bookmarks/sync");
    return await resp.json();
  },

  // 触发边缘 AI 深度分类
  async classifyBookmarks() {
    const resp = await fetch("/api/bookmarks/classify", { method: "POST" });
    return await resp.json();
  }
};

window.api = api;

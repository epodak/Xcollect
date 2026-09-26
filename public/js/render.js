/**
 * Twitter Curated Portal - Render Engine & Utilities
 * 负责纯展示渲染、Markdown 解析、卡片列表生成与模态框交互
 */

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function showToast(msg, isSuccess = true) {
  const toast = document.getElementById("toastMsg");
  if (!toast) return;
  toast.style.borderColor = isSuccess ? "rgb(var(--c-brand))" : "rgb(var(--c-danger))";
  toast.innerHTML = (isSuccess ? "✅ " : "⚠️ ") + msg;
  toast.style.display = "flex";
  setTimeout(() => {
    toast.style.display = "none";
  }, 3500);
}

function formatNumber(num) {
  if (!num) return "0";
  if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
  if (num >= 1000) return (num / 1000).toFixed(1) + "k";
  return num.toLocaleString();
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function cleanTitle(title) {
  if (!title) return title;
  return title.replace(/^【[^】]+】\s*/, "");
}

function cleanSnippet(snippet) {
  if (!snippet) return snippet;
  return snippet.replace(/^>\s*\*\*领域分类\*\*[:：]\s*`?【[^】]*】`?\s*/, "").trim();
}

function cleanBodyRaw(md) {
  if (!md) return md;
  let lines = md.split("\n");
  if (lines.length > 0 && lines[0].startsWith("# ")) {
    lines.shift();
  }
  return lines.join("\n").replace(/^>\s*\*\*领域分类\*\*[:：]\s*`?【[^】]*】`?\s*\n?/m, "").trim();
}

/**
 * 生成单张推文卡片的 HTML
 */
function generateTweetCardHtml(item, idx = 0) {
  const tweetId = item.id;
  const isSavedOnX = !(window.unbookmarkedIds && window.unbookmarkedIds.has(tweetId));
  const rawSubcat = (item.sub_category || "").trim();
  const displaySubcat = (rawSubcat.includes("/") ? rawSubcat.split("/").pop().trim() : rawSubcat) || (item.category || "").replace(/^\d+_/, "");
  const isBadgeActive = (window.activeSubCategory !== "ALL" && (window.activeSubCategory === rawSubcat || window.activeSubCategory === displaySubcat));
  const subcatBadge = `<span class="badge-subcat ${isBadgeActive ? 'active' : ''}" onclick="event.stopPropagation(); selectSubCategory('${escapeHtml(displaySubcat)}', '${escapeHtml(item.category)}')" title="点击在侧边栏筛选「${escapeHtml(displaySubcat)}」领域">${escapeHtml(displaySubcat)}</span>`;
  
  const hasImages = Array.isArray(item.images) && item.images.length > 0;
  const hasVideos = Array.isArray(item.videos) && item.videos.length > 0;
  const hasMedia = hasImages || hasVideos;

  let contentHtml = "";
  if (hasVideos) {
    contentHtml = `
      <div class="card-snippet media-mode" onclick="openDetail('${tweetId}')">
        ${cleanSnippet(item.snippet) || "暂无正文摘要"}
      </div>
      <div class="card-media-preview card-media-video" onclick="event.stopPropagation()">
        <video src="${item.videos[0]}" preload="metadata" controls playsinline></video>
        <div class="media-type-badge video-badge">▶ 视频</div>
      </div>
    `;
  } else if (hasImages) {
    contentHtml = `
      <div class="card-snippet media-mode" onclick="openDetail('${tweetId}')">
        ${cleanSnippet(item.snippet) || "暂无正文摘要"}
      </div>
      <div class="card-media-preview card-media-image" onclick="openDetail('${tweetId}')">
        <img src="${item.images[0]}" alt="推文配图" loading="lazy">
        ${item.images.length > 1 ? `<div class="media-type-badge img-badge">🖼️ 1/${item.images.length}</div>` : ''}
      </div>
    `;
  } else {
    // 纯文字版专属排版：释放 175px 媒体空间，展示 6~7 行深度干货摘要，视觉充实整齐绝不空洞
    contentHtml = `
      <div class="card-text-rich-wrap" onclick="openDetail('${tweetId}')" title="点击查看完整推文正文">
        <div class="card-text-rich-tag">📝 核心干货要点</div>
        <div class="card-snippet text-rich">
          ${cleanSnippet(item.snippet) || "暂无正文摘要"}
        </div>
      </div>
    `;
  }

  return `
    <div class="tweet-card ${hasMedia ? 'has-media' : 'is-text-only'}" data-key="${tweetId}" style="animation-delay: ${Math.min((idx % 18) * 30, 300)}ms;">
      <div class="card-main">
        <div class="card-top">
          <div class="author-info">
            <div class="author-avatar">
              ${(item.avatar || "")
                ? `<img class="author-avatar-img" src="${item.avatar}" alt="${(item.author || item.username || "?")}" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'; var fb=this.nextElementSibling; if(fb){fb.style.display='flex';}">
                   <span class="author-avatar-fallback" style="display:none">${(item.author || item.username || "?").charAt(0).toUpperCase()}</span>`
                : `<span class="author-avatar-fallback">${(item.author || item.username || "?").charAt(0).toUpperCase()}</span>`}
            </div>
            <div class="author-meta">
              <div class="author-name" title="${item.author || item.username}">${item.author || item.username}</div>
              <div class="author-handle">@${item.username || "anon"}${item.created_at ? " · " + formatDate(item.created_at) : ""}</div>
            </div>
          </div>
          ${subcatBadge}
        </div>

        <div class="card-title" onclick="openDetail('${tweetId}')" title="${cleanTitle(item.title) || item.filename}">
          ${cleanTitle(item.title) || item.filename}
        </div>

        <div class="card-body-content">
          ${contentHtml}
        </div>
      </div>

      <div class="card-footer">
        <div class="card-metrics">
          <span class="metric-item" title="点赞量">❤️ ${formatNumber(item.likes)}</span>
          <span class="metric-item" title="浏览量">👀 ${formatNumber(item.views)}</span>
        </div>

        <div class="card-buttons">
          <button class="btn-action btn-bookmark ${isSavedOnX ? 'saved' : 'unbookmarked'}" id="btn-toggle-${tweetId}" onclick="toggleXBookmark('${tweetId}')" title="${isSavedOnX ? '已收藏在 X，点击从云端移除' : '已从 X 移除，点击恢复收藏'}">
            <span>${isSavedOnX ? '★ 移出' : '☆ 收藏'}</span>
          </button>
          <a class="btn-action btn-twitter" href="${item.url || 'https://x.com'}" target="_blank" rel="noopener noreferrer" title="前往 Twitter 页面查看或管理原推">
            <span>𝕏 原推 ↗</span>
          </a>
        </div>
      </div>
    </div>
  `;
}

/**
 * 渲染首屏呼吸微光骨架屏 (Skeleton Screen)
 * 首帧毫秒级展现卡片占位轮廓，彻底杜绝白屏等待
 */
function renderSkeletonCards(container, count = 6) {
  if (!container) return;
  let html = "";
  for (let i = 0; i < count; i++) {
    html += `
      <div class="tweet-card skeleton-card">
        <div class="card-main">
          <div class="card-top">
            <div class="author-info">
              <div class="skeleton-avatar skeleton-bone"></div>
              <div class="author-meta" style="width: 130px;">
                <div class="skeleton-line skeleton-bone" style="width: 80%; height: 12px; margin-bottom: 6px;"></div>
                <div class="skeleton-line skeleton-bone" style="width: 50%; height: 10px;"></div>
              </div>
            </div>
            <div class="skeleton-badge skeleton-bone"></div>
          </div>
          <div class="skeleton-line title skeleton-bone" style="margin-top: 1rem;"></div>
          <div class="skeleton-line title skeleton-bone" style="width: 60%; margin-bottom: 1rem;"></div>
          <div class="skeleton-line text skeleton-bone"></div>
          <div class="skeleton-line text short skeleton-bone"></div>
          <div class="skeleton-media skeleton-bone"></div>
        </div>
        <div class="skeleton-footer">
          <div class="skeleton-metric skeleton-bone"></div>
          <div class="skeleton-btn skeleton-bone"></div>
        </div>
      </div>
    `;
  }
  container.innerHTML = html;
}

/**
 * 分批流式渲染推文卡片（支持首次覆盖或触底追加）
 */
function renderTweetsBatch(container, list, startIndex, count, append = false) {
  if (!container) return;
  const emptyState = document.getElementById("emptyState");

  if (!list || list.length === 0) {
    container.innerHTML = "";
    if (emptyState) emptyState.style.display = "block";
    return;
  }
  if (emptyState) emptyState.style.display = "none";

  const slice = list.slice(startIndex, startIndex + count);
  const cardsHtml = slice.map((item, idx) => generateTweetCardHtml(item, startIndex + idx)).join("");

  if (append) {
    // 插入在哨兵元素之前，若无哨兵则追加到末尾
    const sentinel = document.getElementById("infiniteScrollSentinel");
    if (sentinel) {
      sentinel.insertAdjacentHTML("beforebegin", cardsHtml);
    } else {
      container.insertAdjacentHTML("beforeend", cardsHtml);
    }
  } else {
    container.innerHTML = cardsHtml;
  }
}

/**
 * 触底哨兵元素渲染与状态更新
 */
function renderSentinel(container, hasMore, currentCount, totalCount) {
  if (!container) return;
  let sentinel = document.getElementById("infiniteScrollSentinel");
  if (!sentinel) {
    sentinel = document.createElement("div");
    sentinel.id = "infiniteScrollSentinel";
    sentinel.className = "infinite-scroll-sentinel";
    container.appendChild(sentinel);
  }

  if (hasMore) {
    sentinel.innerHTML = `
      <div class="sentinel-loading">
        <div class="sentinel-spinner"></div>
        <span>正在极速流式呈现推文... (${currentCount} / ${totalCount})</span>
      </div>
    `;
  } else {
    sentinel.innerHTML = `
      <div class="sentinel-finished">
        <span>✨ 已加载全部 ${totalCount} 篇精选推文 · 完</span>
      </div>
    `;
  }
}

function updateModalBookmarkBtn() {
  if (!window.currentOpenTweet) return;
  const tweetId = window.currentOpenTweet.id;
  const isSaved = !(window.unbookmarkedIds && window.unbookmarkedIds.has(tweetId));
  const btn = document.getElementById("modalToggleBookmark");
  if (btn) {
    btn.className = `btn-action btn-bookmark ${isSaved ? 'saved' : 'unbookmarked'}`;
    btn.innerHTML = `<span>${isSaved ? '★ 从 𝕏 云端移出书签' : '☆ 恢复添加到 𝕏 书签'}</span>`;
  }
}

// 打开详情模态框
window.openDetail = function(tweetId) {
  const tweet = window.tweets && window.tweets.find(t => t.id === tweetId || t.filename === tweetId);
  if (!tweet) return;
  window.currentOpenTweet = tweet;

  const rawSub = (tweet.sub_category || "").trim();
  const displaySub = (rawSub.includes("/") ? rawSub.split("/").pop().trim() : rawSub) || (tweet.category || "").replace(/^\d+_/, "");
  document.getElementById("modalSubcat").textContent = displaySub;
  document.getElementById("modalAuthor").textContent = `${tweet.author} (@${tweet.username})`;
  document.getElementById("modalStats").textContent = `❤️ ${formatNumber(tweet.likes)} 赞 · 🔁 ${formatNumber(tweet.retweets)} 转 · 👀 ${formatNumber(tweet.views)} 阅`;
  document.getElementById("modalTwitterLink").href = tweet.url || "https://x.com";

  updateModalBookmarkBtn();
  document.getElementById("modalToggleBookmark").onclick = () => window.toggleXBookmark(tweetId);

  // 渲染 Markdown（剥离与徽章重复的【分类】前缀和「领域分类」引用行）
  const bodyContainer = document.getElementById("modalBody");
  const modalMd = tweet.body_raw ? cleanBodyRaw(tweet.body_raw) : cleanSnippet(tweet.snippet);
  bodyContainer.innerHTML = parseMarkdownToHtml(modalMd, tweet.images, tweet.videos);

  document.getElementById("detailModal").classList.add("active");
};

function closeModal() {
  document.getElementById("detailModal").classList.remove("active");
  window.currentOpenTweet = null;
}

// 简易 Markdown 解析器
function parseMarkdownToHtml(md, images, videos) {
  if (!md) return "<p>暂无内容</p>";
  let html = md
    .replace(/^### (.*$)/gim, '<h3>$1</h3>')
    .replace(/^## (.*$)/gim, '<h2>$1</h2>')
    .replace(/^# (.*$)/gim, '<h1>$1</h1>')
    .replace(/\*\*(.*)\*\*/gim, '<strong>$1</strong>')
    .replace(/\*(.*)\*/gim, '<em>$1</em>')
    .replace(/`([^`]+)`/gim, '<code style="background:rgb(var(--c-sunken));padding:2px 6px;border-radius:4px;color:rgb(var(--c-brand-bright));">$1</code>')
    .replace(/^\> (.*$)/gim, '<blockquote>$1</blockquote>')
    .replace(/!\[([^\]]*)\]\(([^)]+)\)/gim, '<div style="margin-top:1.2rem;border-radius:8px;overflow:hidden;border:1px solid rgb(var(--c-line));"><img src="$2" alt="$1" style="width:100%;display:block;border-radius:8px;" loading="lazy" referrerpolicy="no-referrer"></div>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/gim, '<a href="$2" target="_blank" style="color:rgb(var(--c-brand));">$1</a>')
    .replace(/\n\n/gim, '<br><br>');

  if (videos && videos.length > 0) {
    videos.forEach(vUrl => {
      html += `<div style="margin-top:1.5rem;border-radius:10px;overflow:hidden;background:#000;border:1px solid rgb(var(--c-line));"><video src="${vUrl}" controls playsinline preload="auto" style="width:100%;max-height:480px;display:block;outline:none;"></video></div>`;
    });
  } else if (images && images.length > 0) {
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(240px, 1fr));gap:0.75rem;margin-top:1.5rem;">';
    images.forEach(imgUrl => {
      html += `<div style="border-radius:8px;overflow:hidden;border:1px solid rgb(var(--c-line));"><img src="${imgUrl}" style="width:100%;height:220px;object-fit:cover;display:block;" loading="lazy" referrerpolicy="no-referrer"></div>`;
    });
    html += '</div>';
  }
  return html;
}

function openAuthModal() {
  const modal = document.getElementById("authModal");
  if (modal) modal.classList.add("active");
}

function closeAuthModal() {
  const modal = document.getElementById("authModal");
  if (modal) modal.classList.remove("active");
}

function exportBookmarks() {
  const activeBookmarks = (window.tweets || []).filter(t => !(window.unbookmarkedIds && window.unbookmarkedIds.has(t.id)));
  const blob = new Blob([JSON.stringify(activeBookmarks, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `twitter_active_bookmarks_${new Date().toISOString().slice(0,10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

// 显式挂载至全局 window，确保内联 onclick 与跨模块调用完全无阻
window.escapeHtml = escapeHtml;
window.formatNumber = formatNumber;
window.formatDate = formatDate;
window.cleanTitle = cleanTitle;
window.cleanSnippet = cleanSnippet;
window.cleanBodyRaw = cleanBodyRaw;
window.generateTweetCardHtml = generateTweetCardHtml;
window.renderSkeletonCards = renderSkeletonCards;
window.renderTweetsBatch = renderTweetsBatch;
window.renderSentinel = renderSentinel;
window.parseMarkdownToHtml = parseMarkdownToHtml;
window.showToast = showToast;
window.updateModalBookmarkBtn = updateModalBookmarkBtn;
window.closeModal = closeModal;
window.openAuthModal = openAuthModal;
window.closeAuthModal = closeAuthModal;
window.exportBookmarks = exportBookmarks;

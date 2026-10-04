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
  return String(md)
    .replace(/^>\s*\*\*领域分类\*\*[:：]\s*`?【[^】]*】`?\s*\n?/m, "")
    .trim();
}

function getVideoSource(video) {
  if (!video) return "";
  if (typeof video === "string") return video;
  if (typeof video === "object") return video.url || "";
  return "";
}

function safeExternalUrl(value) {
  try {
    const url = new URL(String(value || ""), window.location.origin);
    if (url.protocol === "http:" || url.protocol === "https:") return url.href;
  } catch (e) {
    return "";
  }
  return "";
}

function prepareReaderBody(tweet) {
  const body = tweet.body_raw ? cleanBodyRaw(tweet.body_raw) : cleanSnippet(tweet.snippet);
  const title = cleanTitle(tweet.title || "");
  if (!body || !title) return body || "";

  const lines = body.split("\n");
  const first = (lines[0] || "").replace(/^#{1,3}\s*/, "").trim();
  const normalizedTitle = title.replace(/\.\.\.$/, "").trim();

  // Article / Note Tweet 的首行常被同时投影成卡片标题；阅读器里避免重复一次。
  if (lines.length > 1 && normalizedTitle && first.startsWith(normalizedTitle)) {
    return lines.slice(1).join("\n").replace(/^\s+/, "");
  }
  return body;
}

/**
 * 将 canonical tweet 组装为可移植 Markdown。
 * body_raw 是正文真源；卡片 snippet 只在旧数据缺失正文时兜底。
 */
function buildTweetMarkdown(tweet) {
  if (!tweet) return "";

  const title = cleanTitle(tweet.title || "") || `X 推文 · @${tweet.username || "unknown"}`;
  const body = (prepareReaderBody(tweet) || cleanSnippet(tweet.snippet) || "").trim();
  const sourceUrl = safeExternalUrl(tweet.url || "");
  const author = (tweet.author || tweet.username || "").trim();
  const handle = tweet.username ? `@${tweet.username}` : "";
  const categoryPath = [tweet.category, tweet.sub_category]
    .map(value => String(value || "").trim())
    .filter(Boolean)
    .join(" / ");

  const parts = [`# ${title}`, ""];
  const metadata = [];

  if (author || handle) {
    const displayAuthor = [author, handle && handle !== author ? `(${handle})` : ""]
      .filter(Boolean)
      .join(" ");
    metadata.push(`作者：${displayAuthor}`);
  }
  if (tweet.created_at) metadata.push(`发布：${formatDate(tweet.created_at)}`);
  if (categoryPath) metadata.push(`分类：${categoryPath}`);
  if (sourceUrl) metadata.push(`原推：${sourceUrl}`);

  if (metadata.length) {
    parts.push(metadata.map(line => `> ${line}`).join("\n"), "");
  }

  if (body) parts.push(body);

  // 正文中没有显式引用的媒体，也一起带走，保证复制结果尽可能自包含。
  const mediaLines = [];
  const embeddedText = body;

  if (Array.isArray(tweet.images)) {
    tweet.images.forEach((image, index) => {
      const url = safeExternalUrl(image);
      if (!url || embeddedText.includes(url)) return;
      mediaLines.push(`![原推配图 ${index + 1}](${url})`);
    });
  }

  if (Array.isArray(tweet.videos)) {
    tweet.videos.forEach((video, index) => {
      const url = safeExternalUrl(getVideoSource(video));
      if (!url || embeddedText.includes(url)) return;
      mediaLines.push(`- [原推视频 ${index + 1}](${url})`);
    });
  }

  if (mediaLines.length) {
    parts.push("", "## 媒体", "", ...mediaLines);
  }

  return parts
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim() + "\n";
}

async function writeTextToClipboard(text) {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    await navigator.clipboard.writeText(text);
    return;
  }

  // Local Profile / 旧浏览器兜底。
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("clipboard copy command failed");
}

async function copyTweetMarkdown(tweetId, button = null) {
  const tweet = window.tweets && window.tweets.find(
    item => item.id === tweetId || item.filename === tweetId
  );
  if (!tweet) {
    showToast("未找到这条推文，无法复制", false);
    return;
  }

  const markdown = buildTweetMarkdown(tweet);
  if (!markdown) {
    showToast("这条推文没有可复制的 Markdown 内容", false);
    return;
  }

  const originalHtml = button ? button.innerHTML : "";
  if (button) {
    button.disabled = true;
    button.innerHTML = "<span>复制中…</span>";
  }

  let resetDelay = 0;
  try {
    await writeTextToClipboard(markdown);
    showToast("已复制 Markdown 到剪贴板");
    if (button) {
      button.innerHTML = "<span>✓ 已复制</span>";
      resetDelay = 1200;
    }
  } catch (error) {
    console.error("Copy tweet markdown failed:", error);
    showToast("复制失败，请检查浏览器剪贴板权限", false);
  } finally {
    if (button) {
      setTimeout(() => {
        button.disabled = false;
        button.innerHTML = originalHtml;
      }, resetDelay);
    }
  }
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
  const primaryVideoUrl = hasVideos ? safeExternalUrl(getVideoSource(item.videos[0])) : "";
  const primaryImageUrl = hasImages ? safeExternalUrl(item.images[0]) : "";
  const previewText = escapeHtml(cleanSnippet(item.snippet) || "暂无正文摘要");

  let contentHtml = "";
  if (hasVideos) {
    contentHtml = `
      <div class="card-snippet media-mode" onclick="openDetail('${tweetId}')">
        ${previewText}
      </div>
      <div class="card-media-preview card-media-video" onclick="event.stopPropagation()">
        <video src="${escapeHtml(primaryVideoUrl)}" preload="metadata" controls playsinline></video>
        <div class="media-type-badge video-badge">▶ 视频</div>
      </div>
    `;
  } else if (hasImages) {
    contentHtml = `
      <div class="card-snippet media-mode" onclick="openDetail('${tweetId}')">
        ${previewText}
      </div>
      <div class="card-media-preview card-media-image" onclick="openDetail('${tweetId}')">
        <img src="${escapeHtml(primaryImageUrl)}" alt="推文配图" loading="lazy">
        ${item.images.length > 1 ? `<div class="media-type-badge img-badge">🖼️ 1/${item.images.length}</div>` : ''}
      </div>
    `;
  } else {
    // 纯文字版专属排版：释放 175px 媒体空间，展示 6~7 行深度干货摘要，视觉充实整齐绝不空洞
    contentHtml = `
      <div class="card-text-rich-wrap" onclick="openDetail('${tweetId}')" title="点击查看完整推文正文">
        <div class="card-text-rich-tag">📝 内容预览</div>
        <div class="card-snippet text-rich">
          ${previewText}
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
                ? `<img class="author-avatar-img" src="${item.avatar}" alt="${escapeHtml(item.author || item.username || "?")}" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'; var fb=this.nextElementSibling; if(fb){fb.style.display='flex';}">
                   <span class="author-avatar-fallback" style="display:none">${(item.author || item.username || "?").charAt(0).toUpperCase()}</span>`
                : `<span class="author-avatar-fallback">${(item.author || item.username || "?").charAt(0).toUpperCase()}</span>`}
            </div>
            <div class="author-meta">
              <div class="author-name" title="${escapeHtml(item.author || item.username)}">${escapeHtml(item.author || item.username)}</div>
              <div class="author-handle">@${escapeHtml(item.username || "anon")}${item.created_at ? " · " + formatDate(item.created_at) : ""}</div>
            </div>
          </div>
          ${subcatBadge}
        </div>

        <div class="card-title" onclick="openDetail('${tweetId}')" title="${escapeHtml(cleanTitle(item.title) || item.filename)}">
          ${escapeHtml(cleanTitle(item.title) || item.filename)}
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
          <button type="button" class="btn-action btn-copy" onclick="event.stopPropagation(); copyTweetMarkdown('${tweetId}', this)" title="复制完整推文为 Markdown 到剪贴板" aria-label="复制推文 Markdown">
            <span>⧉ 复制</span>
          </button>
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

// 打开 Canonical Document 阅读器
window.openDetail = function(tweetId) {
  const tweet = window.tweets && window.tweets.find(t => t.id === tweetId || t.filename === tweetId);
  if (!tweet) return;
  window.currentOpenTweet = tweet;

  const rawSub = (tweet.sub_category || "").trim();
  const displaySub = (rawSub.includes("/") ? rawSub.split("/").pop().trim() : rawSub)
    || (tweet.category || "").replace(/^\d+_/, "");
  const title = cleanTitle(tweet.title || "") || "X 原文";
  const readerBody = prepareReaderBody(tweet);
  const hasCanonicalBody = Boolean((tweet.body_raw || "").trim());
  const likelyLegacyTruncation = !hasCanonicalBody
    || (/https:\/\/t\.co\/[A-Za-z0-9]+\s*$/.test(tweet.body_raw || "") && (tweet.body_raw || "").length < 600);

  document.getElementById("modalSubcat").textContent = displaySub;
  document.getElementById("modalAuthor").textContent = `${tweet.author || tweet.username || ""} (@${tweet.username || ""})`;
  document.getElementById("modalTitle").textContent = title;
  document.getElementById("modalPublished").textContent = [
    tweet.created_at ? `发布于 ${formatDate(tweet.created_at)}` : "",
    hasCanonicalBody ? `${String(tweet.body_raw).length.toLocaleString()} 字符` : ""
  ].filter(Boolean).join(" · ");

  const contentState = document.getElementById("modalContentState");
  if (contentState) {
    contentState.textContent = likelyLegacyTruncation
      ? "正文可能未完整同步"
      : "完整正文 · Canonical";
  }

  document.getElementById("modalStats").textContent =
    `❤️ ${formatNumber(tweet.likes)} 赞 · 🔁 ${formatNumber(tweet.retweets)} 转 · 👀 ${formatNumber(tweet.views)} 阅`;

  const sourceUrl = safeExternalUrl(tweet.url || "https://x.com") || "https://x.com";
  document.getElementById("modalTwitterLink").href = sourceUrl;

  updateModalBookmarkBtn();
  document.getElementById("modalToggleBookmark").onclick = () => window.toggleXBookmark(tweetId);

  const bodyContainer = document.getElementById("modalBody");
  let bodyHtml = "";
  if (likelyLegacyTruncation) {
    bodyHtml += `
      <div class="reader-incomplete">
        当前记录可能仍是旧版 legacy 预览，而不是完整 Note Tweet / X Article。
        点击“立即同步”会触发完整 reconciliation，并重新写入 canonical 正文；也可以直接在 X 查看原文。
      </div>
    `;
  }

  bodyHtml += parseMarkdownToHtml(
    readerBody || cleanSnippet(tweet.snippet) || "",
    tweet.images,
    tweet.videos
  );
  bodyContainer.innerHTML = bodyHtml;
  document.getElementById("detailModal").classList.add("active");
};

function closeModal() {
  document.getElementById("detailModal").classList.remove("active");
  window.currentOpenTweet = null;
}

// Canonical Markdown renderer：先转义源文本，再恢复有限、安全的 Markdown 语义。
function renderInlineMarkdown(text) {
  const tokens = [];
  const stash = (html) => {
    const marker = `@@XCOLLECT_TOKEN_${tokens.length}@@`;
    tokens.push(html);
    return marker;
  };

  let raw = String(text || "");

  raw = raw.replace(/!\[([^\]]*)\]\((https?:\/\/[^)\s]+)\)/g, (_, alt, url) => {
    const safe = safeExternalUrl(url);
    if (!safe) return alt || "";
    return stash(`<img src="${escapeHtml(safe)}" alt="${escapeHtml(alt || "")}" loading="lazy" referrerpolicy="no-referrer">`);
  });

  raw = raw.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (_, label, url) => {
    const safe = safeExternalUrl(url);
    if (!safe) return label;
    return stash(`<a href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`);
  });

  raw = raw.replace(/https?:\/\/[^\s<>()]+/g, (url) => {
    const safe = safeExternalUrl(url);
    if (!safe) return url;
    return stash(`<a href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a>`);
  });

  let html = escapeHtml(raw)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");

  html = html.replace(/@@XCOLLECT_TOKEN_(\d+)@@/g, (_, index) => tokens[Number(index)] || "");
  return html;
}

function parseMarkdownToHtml(md, images, videos) {
  if (!md) {
    return `<div class="canonical-prose"><p>暂无可渲染正文。请在 X 打开原文。</p></div>`;
  }

  const lines = String(md).replace(/\r\n/g, "\n").split("\n");
  const parts = [];
  let paragraph = [];
  let listType = null;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    parts.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br>")}</p>`);
    paragraph = [];
  };

  const closeList = () => {
    if (!listType) return;
    parts.push(`</${listType}>`);
    listType = null;
  };

  const openList = (type) => {
    if (listType === type) return;
    closeList();
    parts.push(`<${type}>`);
    listType = type;
  };

  for (const rawLine of lines) {
    const line = String(rawLine || "");

    if (!line.trim()) {
      flushParagraph();
      closeList();
      continue;
    }

    if (/^\s{4}/.test(line)) {
      flushParagraph();
      closeList();
      parts.push(`<pre><code>${escapeHtml(line.replace(/^\s{4}/, ""))}</code></pre>`);
      continue;
    }

    if (/^---+$/.test(line.trim())) {
      flushParagraph();
      closeList();
      parts.push("<hr>");
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length;
      parts.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      closeList();
      parts.push(`<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`);
      continue;
    }

    const unordered = line.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      flushParagraph();
      openList("ul");
      parts.push(`<li>${renderInlineMarkdown(unordered[1])}</li>`);
      continue;
    }

    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      openList("ol");
      parts.push(`<li>${renderInlineMarkdown(ordered[1])}</li>`);
      continue;
    }

    if (listType) closeList();
    paragraph.push(line);
  }

  flushParagraph();
  closeList();

  let html = `<div class="canonical-prose">${parts.join("")}</div>`;
  const bodyText = String(md);
  const mediaParts = [];

  if (Array.isArray(videos)) {
    for (const video of videos) {
      const src = safeExternalUrl(getVideoSource(video));
      if (!src) continue;
      const poster = video && typeof video === "object" ? safeExternalUrl(video.poster || "") : "";
      mediaParts.push(`<div class="canonical-media"><video src="${escapeHtml(src)}" ${poster ? `poster="${escapeHtml(poster)}"` : ""} controls playsinline preload="metadata"></video></div>`);
    }
  }

  if (Array.isArray(images)) {
    const remainingImages = images
      .map(safeExternalUrl)
      .filter(Boolean)
      .filter((url) => !bodyText.includes(url));

    if (remainingImages.length) {
      mediaParts.push(
        `<div class="canonical-media canonical-media-grid">` +
        remainingImages.map((url) => `<img src="${escapeHtml(url)}" alt="原推媒体" loading="lazy" referrerpolicy="no-referrer">`).join("") +
        `</div>`
      );
    }
  }

  return html + mediaParts.join("");
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
window.buildTweetMarkdown = buildTweetMarkdown;
window.copyTweetMarkdown = copyTweetMarkdown;
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

/**
 * Twitter Curated Portal - Application Controller
 * 全局状态管理、手风琴二级导航、筛选过滤管线与无感流式加载总线
 */

// 全局响应式状态变量
var tweets = [];
var currentFilteredList = [];
var renderedCount = 0;
const BATCH_SIZE = 18; // 首屏与每次触底流式渲染 18 张卡片 (6 行)，轻量秒开无长任务
const CACHE_KEY = "twitter_curated_tweets_cache_v5";

var searchQuery = "";
var activeCategory = "ALL";
var activeSubCategory = "ALL";
var sortMode = "related_hot_desc";
var filterBookmarked = false;
var filterHasMedia = false;
var filterHighLikes = false;
var filterHighViews = false;
var currentOpenTweet = null;
var isXConfigured = false;
var sentinelObserver = null;

const UNBOOKMARKED_KEY = "twitter_curated_unbookmarked_ids_v1";
var unbookmarkedIds = new Set(JSON.parse(localStorage.getItem(UNBOOKMARKED_KEY) || "[]"));

function saveUnbookmarked() {
  localStorage.setItem(UNBOOKMARKED_KEY, JSON.stringify(Array.from(unbookmarkedIds)));
}


const THEME_KEY = "xboard_theme_v1";

    function getTheme() {
      return document.documentElement.classList.contains("light") ? "light" : "dark";
    }

    function updateThemeToggleUI() {
      const btn = document.getElementById("themeToggleBtn");
      if (!btn) return;
      const isLight = getTheme() === "light";
      btn.querySelector("span").textContent = isLight ? "🌙" : "☀️";
      btn.title = isLight ? "切换到深色主题" : "切换到浅色主题";
    }

    function toggleTheme() {
      const next = getTheme() === "light" ? "dark" : "light";
      document.documentElement.classList.remove("light", "dark");
      document.documentElement.classList.add(next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
      updateThemeToggleUI();
    }

async function checkAuthStatus() {
  try {
    const data = await api.getAuthStatus();
    isXConfigured = Boolean(data.configured);
    const dot = document.getElementById("authStatusDot");
    const text = document.getElementById("authStatusText");
    const btn = document.getElementById("btnOpenAuthModal");

    if (isXConfigured) {
      if (dot) dot.className = "status-dot online";
      if (text) text.textContent = "𝕏 真实同步已就绪";
      if (btn) btn.className = "btn-auth authed";
      if (data.auth_token_preview) {
        const inputAuth = document.getElementById("inputAuthToken");
        const inputCt0 = document.getElementById("inputCt0");
        if (inputAuth && !inputAuth.value) inputAuth.placeholder = "已在 Cloudflare 边缘就绪 (" + data.auth_token_preview + ")";
        if (inputCt0 && !inputCt0.value) inputCt0.placeholder = "已在 Cloudflare 边缘安全就绪";
      }
    } else {
      if (dot) dot.className = "status-dot";
      if (text) text.textContent = "连接 𝕏 账户 (未配置)";
      if (btn) btn.className = "btn-auth";
    }
  } catch (e) {
    console.warn("无法检查凭证状态:", e);
  }
}

async function refreshDiscoveryStatusNotice() {
  const notice = document.getElementById("discoveryStateNotice");
  if (!notice) return;

  try {
    const status = await api.getDiscoveryStatus();
    if (!status.available) {
      notice.innerHTML = "💻 Global Discovery 仅在 Personal Cloud / D1 Profile 运行。";
      return;
    }

    const when = status.last_run_at
      ? new Date(status.last_run_at).toLocaleString()
      : "尚未运行";
    const feedCount = Number(status.daily_feed_count || 0);
    const states = status.states || {};
    notice.innerHTML =
      "🔥 <b>Personal Discovery</b><br>" +
      "最近运行：" + when + "<br>" +
      "今日 Feed " + feedCount + " · 候选 " + Number(states.candidate || 0) +
      " · 已评估 " + Number(states.judged || 0);
  } catch (e) {
    notice.innerHTML = "ℹ️ Discovery 状态暂不可用。";
  }
}

async function refreshSyncStatusNotice() {
  const notice = document.getElementById("syncStateNotice");
  if (!notice) return;

  try {
    const status = await api.getSyncStatus();

    if (status.storage_profile === "local") {
      notice.innerHTML = "💻 <b>Local Profile</b><br>本地服务按需同步；Personal Cloud 才使用 Cloudflare Cron 自动拉取。";
      return;
    }

    if (status.state === "success") {
      const when = status.last_success_at
        ? new Date(status.last_success_at).toLocaleString()
        : "未知时间";
      const trigger = String(status.trigger || "").startsWith("cron:")
        ? "后台定时"
        : "手动";
      const count = status.new_count != null ? ` · 新增 ${status.new_count}` : "";
      const removed = Number(status.removed_count || 0);
      const removedText = removed > 0 ? ` · 移除 ${removed}` : "";
      const mode = status.sync_mode === "reconcile" ? "完整对账" : "增量";
      notice.innerHTML = `✅ <b>${trigger}同步正常 · ${mode}</b><br>最近成功：${when}${count}${removedText}<br><span style="opacity:.8">页面只读取已持久化数据；“立即同步”会强制完整对账。</span>`;
      return;
    }

    if (status.state === "failed") {
      const when = status.last_attempt_at
        ? new Date(status.last_attempt_at).toLocaleString()
        : "未知时间";
      notice.innerHTML = `⚠️ <b>后台同步最近失败</b><br>${when} · ${status.error || "UNKNOWN"}<br>${status.message || ""}`;
      return;
    }

    if (status.state === "running") {
      notice.innerHTML = "⏳ 后台同步正在运行。页面继续展示上一版已持久化数据。";
      return;
    }

    notice.innerHTML = "ℹ️ 尚无后台同步记录。Cloud Profile 部署后应由 Cron Trigger 周期拉取；本地模式可使用“立即同步”。";
  } catch (e) {
    // Local Profile may not expose the cloud scheduler endpoint.
    notice.innerHTML = "ℹ️ 当前未发现 Cloud Cron 状态。Local Profile 按需运行；Personal Cloud 应配置 Cron Trigger 自动同步。";
  }
}

/**
 * 现代 Feed 流初始化：SWR 本地秒开 + 骨架屏 + 后台并发网络更新
 */
async function initApp() {
  const container = document.getElementById("tweetsContainer");
  const brandSub = document.querySelector(".brand-sub");

  // 1. 尝试从本地存储读取离线/历史推文缓存（实现 0ms 瞬间秒出首屏）
  let hasValidCache = false;
  try {
    const cachedStr = localStorage.getItem(CACHE_KEY);
    if (cachedStr) {
      const cachedData = JSON.parse(cachedStr);
      if (Array.isArray(cachedData) && cachedData.length > 0) {
        tweets = cachedData;
        window.tweets = tweets;
        hasValidCache = true;
        if (brandSub) {
          brandSub.textContent = `Curated Knowledge Portal · ${tweets.length} 篇推文 (本地秒开)`;
        }
        renderCategories();
        applyFiltersAndRender(false);
      }
    }
  } catch (err) {
    console.debug("读取本地推文缓存跳过:", err);
  }

  // 2. 若无缓存（首次访问），首帧立即呈现微光呼吸骨架屏，彻底消灭白屏等待
  if (!hasValidCache) {
    renderSkeletonCards(container, 6);
  }

  // 3. 异步并发绑定事件与检查凭证
  setupEventListeners();
  const authStatusPromise = checkAuthStatus();
  const syncStatusPromise = refreshSyncStatusNotice();
  const discoveryStatusPromise = refreshDiscoveryStatusNotice();
  api.flushFeedbackQueue().catch(() => {});

  // 4. 后台发起真实网络请求（非阻塞），实现推特级 Stale-While-Revalidate
  try {
    const storageData = await api.getTweets();
    if (storageData && storageData.success && Array.isArray(storageData.data)) {
      const newTweets = storageData.data;
      tweets = newTweets;
      window.tweets = tweets;

      // 写入持久化高速缓存
      try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(tweets));
      } catch (e) { /* 配额溢出时静默忽略 */ }

      if (brandSub) {
        brandSub.textContent = `Curated Knowledge Portal · ${tweets.length} 篇推文`;
      }

      // 无论篇数是否变化，只要从当前持久化层拉取到最新数据均重新渲染
      renderCategories();
      applyFiltersAndRender(false);
    }
  } catch (e) {
    console.warn("后台拉取最新推文失败:", e);
    // 若既无缓存又网络失败，清空骨架屏并显示空状态
    if (!hasValidCache && container) {
      container.innerHTML = "";
      const emptyState = document.getElementById("emptyState");
      if (emptyState) emptyState.style.display = "block";
    }
  }

  // 5. 页面是观察面，不是后台任务触发器。
  // Cloud Profile 由 Cron Trigger 自动同步；这里只等待状态请求完成。
  await authStatusPromise;
  await syncStatusPromise;
  await discoveryStatusPromise;
}

function renderCategories() {
      const categoryMap = { "ALL": tweets.length };
      const categorySubMap = {};

      tweets.forEach(t => {
        categoryMap[t.category] = (categoryMap[t.category] || 0) + 1;
        
        const cat = t.category;
        if (!categorySubMap[cat]) categorySubMap[cat] = {};
        let sub = (t.sub_category || "").trim();
        if (sub.includes("/")) sub = sub.split("/").pop().trim();
        if (sub && sub !== "精选") {
          categorySubMap[cat][sub] = (categorySubMap[cat][sub] || 0) + 1;
        }
      });

      const catContainer = document.getElementById("categoryList");
      const mobileCatBar = document.getElementById("mobileCategoryBar");
      catContainer.innerHTML = "";
      if (mobileCatBar) mobileCatBar.innerHTML = "";

      // 1. 全部选项
      const allBtn = document.createElement("button");
      allBtn.className = `category-btn ${activeCategory === "ALL" ? "active" : ""}`;
      allBtn.innerHTML = `
        <div class="category-title-wrap">
          <span class="category-arrow">•</span>
          <span>全部分类汇总</span>
        </div>
        <span class="category-count">${tweets.length}</span>
      `;
      allBtn.onclick = () => {
        activeCategory = "ALL";
        activeSubCategory = "ALL";
        renderCategories();
        applyFiltersAndRender();
        closeDrawer();
      };
      catContainer.appendChild(allBtn);

      if (mobileCatBar) {
        const mobAllChip = document.createElement("button");
        mobAllChip.className = `mobile-cat-chip ${activeCategory === "ALL" ? "active" : ""}`;
        mobAllChip.innerHTML = `<span>全部</span><span class="count">${tweets.length}</span>`;
        mobAllChip.onclick = () => {
          activeCategory = "ALL";
          activeSubCategory = "ALL";
          renderCategories();
          applyFiltersAndRender();
        };
        mobileCatBar.appendChild(mobAllChip);
      }

      // 2. 6 大具体一级专区（带二级折叠手风琴树）
      Object.keys(categoryMap).filter(k => k !== "ALL").sort().forEach(cat => {
        const subCounts = categorySubMap[cat] || {};
        const subList = Object.keys(subCounts).sort((a, b) => subCounts[b] - subCounts[a]);
        const isOpen = activeCategory === cat;
        const displayName = cat.replace(/^\d+_/, "");

        const groupDiv = document.createElement("div");
        groupDiv.className = `category-group ${isOpen ? "open" : ""}`;
        groupDiv.dataset.category = cat;

        // 一级专区主按钮
        const catBtn = document.createElement("button");
        catBtn.className = `category-btn ${isOpen ? "active" : ""}`;
        catBtn.innerHTML = `
          <div class="category-title-wrap">
            <span class="category-arrow">${subList.length > 0 ? "▸" : "•"}</span>
            <span>${displayName}</span>
          </div>
          <span class="category-count">${categoryMap[cat]}</span>
        `;

        catBtn.onclick = () => {
          if (activeCategory === cat && activeSubCategory === "ALL") {
            // 已在当前专区且处于全部子领域，折叠回全部分类
            activeCategory = "ALL";
            activeSubCategory = "ALL";
          } else {
            activeCategory = cat;
            activeSubCategory = "ALL";
          }
          renderCategories();
          applyFiltersAndRender();
          closeDrawer();
        };
        groupDiv.appendChild(catBtn);

        // 二级细分子领域折叠列表 (仅在当前专区激活展开)
        if (subList.length > 0) {
          const subListDiv = document.createElement("div");
          subListDiv.className = "subcategory-list";

          // "全部子领域" 快捷选项
          const allSubBtn = document.createElement("button");
          allSubBtn.className = `subcategory-btn ${isOpen && activeSubCategory === "ALL" ? "active" : ""}`;
          allSubBtn.innerHTML = `
            <span>全部子领域</span>
            <span class="subcategory-count">${categoryMap[cat]}</span>
          `;
          allSubBtn.onclick = (e) => {
            e.stopPropagation();
            activeCategory = cat;
            activeSubCategory = "ALL";
            renderCategories();
            applyFiltersAndRender();
            closeDrawer();
          };
          subListDiv.appendChild(allSubBtn);

          // 具体各子领域项
          subList.forEach(sub => {
            const isSubActive = isOpen && activeSubCategory === sub;
            const subBtn = document.createElement("button");
            subBtn.className = `subcategory-btn ${isSubActive ? "active" : ""}`;
            subBtn.innerHTML = `
              <span>${escapeHtml(sub)}</span>
              <span class="subcategory-count">${subCounts[sub]}</span>
            `;
            subBtn.onclick = (e) => {
              e.stopPropagation();
              activeCategory = cat;
              activeSubCategory = sub;
              renderCategories();
              applyFiltersAndRender();
              closeDrawer();
            };
            subListDiv.appendChild(subBtn);
          });

          groupDiv.appendChild(subListDiv);
        }

        catContainer.appendChild(groupDiv);

        // 移动端横向滑动 Chip
        if (mobileCatBar) {
          const mobChip = document.createElement("button");
          mobChip.className = `mobile-cat-chip ${activeCategory === cat ? "active" : ""}`;
          mobChip.innerHTML = `<span>${displayName}</span><span class="count">${categoryMap[cat]}</span>`;
          mobChip.onclick = () => {
            activeCategory = (activeCategory === cat) ? "ALL" : cat;
            activeSubCategory = "ALL";
            renderCategories();
            applyFiltersAndRender();
          };
          mobileCatBar.appendChild(mobChip);
        }
      });
    }

    // 选中/切换二级细分子领域 (可由侧边栏点击或卡片右上角 Badge 点击触发)
    window.selectSubCategory = function(sub, parentCategory) {
      if (parentCategory && activeCategory !== parentCategory) {
        activeCategory = parentCategory;
      }
      activeSubCategory = sub || "ALL";
      renderCategories();
      applyFiltersAndRender();

      // 平滑滚动侧边栏中的激活项到可视区域
      setTimeout(() => {
        const activeItem = document.querySelector(".subcategory-btn.active") || document.querySelector(".category-btn.active");
        if (activeItem) {
          activeItem.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      }, 50);
    };

function openDrawer() {
      const drawer = document.getElementById("sidebarDrawer");
      const backdrop = document.getElementById("sidebarBackdrop");
      if (drawer) drawer.classList.add("mobile-open");
      if (backdrop) backdrop.classList.add("active");
      document.body.style.overflow = "hidden";
    }

    function closeDrawer() {
      const drawer = document.getElementById("sidebarDrawer");
      const backdrop = document.getElementById("sidebarBackdrop");
      if (drawer) drawer.classList.remove("mobile-open");
      if (backdrop) backdrop.classList.remove("active");
      document.body.style.overflow = "";
    }

function setupEventListeners() {
      // 移动端抽屉开关
      const openDrawerBtn = document.getElementById("openDrawerBtn");
      const closeDrawerBtn = document.getElementById("closeDrawerBtn");
      const sidebarBackdrop = document.getElementById("sidebarBackdrop");
      if (openDrawerBtn) openDrawerBtn.onclick = openDrawer;
      if (closeDrawerBtn) closeDrawerBtn.onclick = closeDrawer;
      if (sidebarBackdrop) sidebarBackdrop.onclick = closeDrawer;

      // 移动端按钮智能显示与隐藏
      function checkResponsiveControls() {
        if (window.innerWidth <= 900) {
          if (openDrawerBtn) openDrawerBtn.style.display = "inline-flex";
        } else {
          if (openDrawerBtn) openDrawerBtn.style.display = "none";
          closeDrawer();
        }
      }
      checkResponsiveControls();
      window.addEventListener("resize", checkResponsiveControls);

      // 主题切换按钮
      const themeToggleBtn = document.getElementById("themeToggleBtn");
      if (themeToggleBtn) themeToggleBtn.onclick = toggleTheme;
      updateThemeToggleUI();

      // 搜索防抖
      const searchInput = document.getElementById("searchInput");
      searchInput.addEventListener("input", (e) => {
        searchQuery = e.target.value.toLowerCase().trim();
        applyFiltersAndRender();
      });

      // 排序平铺胶囊与下拉框事件联动
      const sortPills = document.querySelectorAll(".sort-pill");
      const sortSelect = document.getElementById("sortSelect");

      function updateSortMode(newSort, scrollIntoCenter = false) {
        if (!newSort) return;
        sortMode = newSort;
        window.sortMode = sortMode;
        sortPills.forEach(pill => {
          const isMatch = pill.dataset.sort === newSort;
          pill.classList.toggle("active", isMatch);
          pill.setAttribute("aria-checked", isMatch ? "true" : "false");
          if (isMatch && scrollIntoCenter) {
            try {
              pill.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
            } catch (e) {}
          }
        });
        if (sortSelect && sortSelect.value !== newSort) {
          sortSelect.value = newSort;
        }
        applyFiltersAndRender();
      }

      sortPills.forEach(pill => {
        pill.addEventListener("click", () => {
          const chosenSort = pill.dataset.sort;
          if (chosenSort && chosenSort !== sortMode) {
            updateSortMode(chosenSort, true);
          }
        });
      });

      if (sortSelect) {
        sortSelect.addEventListener("change", (e) => {
          updateSortMode(e.target.value, true);
        });
      }

      // 过滤复选框
      document.getElementById("filterBookmarked").addEventListener("change", (e) => {
        filterBookmarked = e.target.checked;
        applyFiltersAndRender();
      });
      document.getElementById("filterHasMedia").addEventListener("change", (e) => {
        filterHasMedia = e.target.checked;
        applyFiltersAndRender();
      });
      document.getElementById("filterHighLikes").addEventListener("change", (e) => {
        filterHighLikes = e.target.checked;
        applyFiltersAndRender();
      });
      document.getElementById("filterHighViews").addEventListener("change", (e) => {
        filterHighViews = e.target.checked;
        applyFiltersAndRender();
      });

      // 视图切换
      document.getElementById("btnGridView").addEventListener("click", () => {
        document.getElementById("btnGridView").classList.add("active");
        document.getElementById("btnCompactView").classList.remove("active");
        document.getElementById("btnListView").classList.remove("active");
        document.getElementById("tweetsContainer").className = "tweets-container grid-view";
      });
      document.getElementById("btnCompactView").addEventListener("click", () => {
        document.getElementById("btnCompactView").classList.add("active");
        document.getElementById("btnGridView").classList.remove("active");
        document.getElementById("btnListView").classList.remove("active");
        document.getElementById("tweetsContainer").className = "tweets-container compact-view";
      });
      document.getElementById("btnListView").addEventListener("click", () => {
        document.getElementById("btnListView").classList.add("active");
        document.getElementById("btnGridView").classList.remove("active");
        document.getElementById("btnCompactView").classList.remove("active");
        document.getElementById("tweetsContainer").className = "tweets-container list-view";
      });

      // 模态框关闭
      document.getElementById("modalCloseBtn").onclick = closeModal;
      document.getElementById("detailModal").onclick = (e) => {
        if (e.target.id === "detailModal") closeModal();
      };
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          closeModal();
          closeAuthModal();
          closeDrawer();
        }
      });

      // 认证配置弹窗
      document.getElementById("btnOpenAuthModal").onclick = openAuthModal;
      document.getElementById("authModalClose").onclick = closeAuthModal;
      document.getElementById("authModal").onclick = (e) => {
        if (e.target.id === "authModal") closeAuthModal();
      };

      // 保存凭证
      document.getElementById("btnSaveCredentials").onclick = async () => {
        const authToken = document.getElementById("inputAuthToken").value.trim();
        const ct0 = document.getElementById("inputCt0").value.trim();
        if (!authToken || !ct0) {
          alert("请完整填写 auth_token 和 ct0");
          return;
        }

        try {
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
            res = { success: resp.ok, message: rawText.slice(0, 100) };
          }

          if (res.success) {
            showToast("𝕏 凭证配置成功！已开启双向真实书签操作");
            closeAuthModal();
            await checkAuthStatus();
          } else {
            alert("保存提示: " + (res.error || res.message || "请求异常"));
          }
        } catch (err) {
          alert("请求失败: " + err);
        }
      };

      // 手动 force-sync：正常情况下 Cloud Profile 已由 Cron 在后台持续同步
      document.getElementById("btnSyncFromX").onclick = async () => {
        if (!isXConfigured) {
          openAuthModal();
          showToast("请先在右上角配置 𝕏 凭证 (auth_token 与 ct0)", false);
          return;
        }

        const icon = document.getElementById("syncBtnIcon");
        const text = document.getElementById("syncBtnText");
        const btn = document.getElementById("btnSyncFromX");
        
        btn.disabled = true;
        icon.style.animation = "spin 1s linear infinite";
        text.textContent = "正在向 𝕏 云端拉取...";

        try {
          const result = await api.syncBookmarks();
          if (result.success) {
            // 同步成功之后强制从当前 Storage Profile 再读一次，以持久化结果作为唯一权威。
            const fresh = await api.getTweets(true);
            if (!fresh.success || !Array.isArray(fresh.data)) {
              throw new Error("同步已返回成功，但持久化层 fresh read-back 失败");
            }

            const existingIds = new Set(tweets.map(t => t.id));
            tweets = fresh.data;
            window.tweets = tweets;
            const newItems = tweets.filter(t => !existingIds.has(t.id));
            try { localStorage.setItem(CACHE_KEY, JSON.stringify(tweets)); } catch(e){}

            const brandSub = document.querySelector(".brand-sub");
            if (brandSub) {
              brandSub.textContent = `Curated Knowledge Portal · ${tweets.length} 篇推文`;
            }

            renderCategories();
            applyFiltersAndRender();

            const backend = result.storage_profile
              || (result.storage && result.storage.backend)
              || fresh.storage_profile
              || fresh.source
              || "storage";
            const storedNew = result.new_count != null
              ? result.new_count
              : (result.storage && Number.isFinite(result.storage.d1_written)
                ? result.storage.d1_written
                : newItems.length);
            const storedTotal = result.count != null
              ? result.count
              : (result.storage_status && result.storage_status.d1_row_count != null
                ? result.storage_status.d1_row_count
                : tweets.length);
            const removed = Number(result.removed_count || 0);
            const removedText = removed > 0 ? `，移除 ${removed} 条 X 已取消收藏` : "";
            showToast(`同步完成：X 拉取 ${result.pulled_count || result.count || 0}，${backend} 新增 ${storedNew}${removedText}，总计 ${storedTotal}`);
            await refreshSyncStatusNotice();
            await refreshDiscoveryStatusNotice();
          } else {
            showToast(result.message || result.error || "从 X 拉取书签失败", false);
            await refreshSyncStatusNotice();
          }
        } catch (err) {
          showToast("网络请求异常: " + err, false);
        } finally {
          btn.disabled = false;
          icon.style.animation = "none";
          text.textContent = "立即同步";
        }
      };

      const btnDiscover = document.getElementById("btnDiscover");
      if (btnDiscover) {
        btnDiscover.onclick = async () => {
          if (!isXConfigured) {
            openAuthModal();
            showToast("请先配置 𝕏 凭证后再运行 Global Discovery", false);
            return;
          }

          const text = document.getElementById("discoverBtnText");
          const icon = document.getElementById("discoverBtnIcon");
          btnDiscover.disabled = true;
          if (icon) icon.style.animation = "spin 1s linear infinite";
          if (text) text.textContent = "正在发现...";

          try {
            const result = await api.runDiscovery();
            if (!result.ok || !result.data || !result.data.success) {
              throw new Error((result.data && (result.data.message || result.data.error)) || "Discovery failed");
            }

            const fresh = await api.getTweets(true);
            if (fresh.success && Array.isArray(fresh.data)) {
              tweets = fresh.data;
              window.tweets = tweets;
              try { localStorage.setItem(CACHE_KEY, JSON.stringify(tweets)); } catch (e) {}
              renderCategories();
              applyFiltersAndRender();
            }

            const d = result.data;
            showToast(
              "Discovery 完成：候选 " + Number(d.raw_candidates || 0) +
              "，筛后 " + Number(d.accepted_candidates || 0) +
              "，今日 Feed " + Number(d.daily_feed_count || 0)
            );
            await refreshDiscoveryStatusNotice();
          } catch (err) {
            showToast("Discovery 运行失败: " + err, false);
          } finally {
            btnDiscover.disabled = false;
            if (icon) icon.style.animation = "none";
            if (text) text.textContent = "立即发现";
          }
        };
      }
      // 一键 AI 智能分类与专区归档
      const btnClassify = document.getElementById("btnClassify");
      if (btnClassify) {
        btnClassify.onclick = async () => {
          const icon = document.getElementById("classifyBtnIcon");
          const text = document.getElementById("classifyBtnText");
          btnClassify.disabled = true;
          icon.style.animation = "spin 1s linear infinite";
          text.textContent = "AI 正在分析归类...";

          try {
            const resp = await fetch("/api/bookmarks/classify", { method: "POST" });
            const result = await resp.json();
            if (result.success) {
              showToast(result.message);
              // 重新拉取当前持久化层最新数据并刷新界面
              try {
                const d1Data = await api.getTweets(true);
                if (d1Data.success && Array.isArray(d1Data.data)) {
                  tweets = d1Data.data;
                  window.tweets = tweets;
                  renderCategories();
                  applyFiltersAndRender();
                } else {
                  setTimeout(() => location.reload(), 1200);
                }
              } catch (e) {
                setTimeout(() => location.reload(), 1200);
              }
            } else {
              showToast(result.message || result.error || "智能分类未能完成", false);
            }
          } catch (err) {
            showToast("智能分类请求异常: " + err, false);
          } finally {
            btnClassify.disabled = false;
            icon.style.animation = "none";
            text.textContent = "AI 智能归类";
          }
        };
      }

      // 导出保留书签
      document.getElementById("exportBookmarkBtn").onclick = exportBookmarks;
    }

/**
 * 过滤与排序核心管线（计算出当前匹配的所有推文集合）
 */
function applyFiltersAndRender(resetScroll = true) {
  currentFilteredList = tweets.filter(item => {
    const tweetId = item.id;
    const isCurrentlyBookmarkedOnX =
      item.is_bookmark !== false &&
      item.source_kind !== "discovery" &&
      !unbookmarkedIds.has(tweetId);

    // 主分类筛选
    if (activeCategory !== "ALL" && item.category !== activeCategory) {
      return false;
    }

    // 二级细分子领域过滤
    if (activeSubCategory !== "ALL") {
      let itemSub = (item.sub_category || "").trim();
      if (itemSub.includes("/")) itemSub = itemSub.split("/").pop().trim();
      if (itemSub !== activeSubCategory) return false;
    }
    
    // 筛选仅看仍在 X 收藏的推文
    if (filterBookmarked && !isCurrentlyBookmarkedOnX) return false;

    // 多媒体
    if (filterHasMedia && !item.has_media) return false;

    // 高赞与高曝光
    if (filterHighLikes && (item.likes || 0) < 1000) return false;
    if (filterHighViews && (item.views || 0) < 100000) return false;

    // 搜索匹配
    if (searchQuery) {
      const matchTitle = (item.title || "").toLowerCase().includes(searchQuery);
      const matchAuthor = (item.author || "").toLowerCase().includes(searchQuery) || (item.username || "").toLowerCase().includes(searchQuery);
      const matchSubcat = (item.sub_category || "").toLowerCase().includes(searchQuery);
      const matchBody = (item.snippet || "").toLowerCase().includes(searchQuery);
      if (!matchTitle && !matchAuthor && !matchSubcat && !matchBody) return false;
    }

    return true;
  });

  // 排序
  currentFilteredList.sort((a, b) => {
    if (sortMode === "related_hot_desc") {
      const scoreDiff = Number(b.related_hot_score || 0) - Number(a.related_hot_score || 0);
      if (scoreDiff !== 0) return scoreDiff;
      // 同分时优先更近收藏，保持排序稳定且符合用户已有时间感。
      return (a.bookmark_position ?? Number.MAX_SAFE_INTEGER) - (b.bookmark_position ?? Number.MAX_SAFE_INTEGER);
    }
    // bookmark_position 来自 X Bookmarks timeline；0 表示最近收藏。
    if (sortMode === "bookmark_desc") return (a.bookmark_position ?? Number.MAX_SAFE_INTEGER) - (b.bookmark_position ?? Number.MAX_SAFE_INTEGER);
    if (sortMode === "likes_desc") return (b.likes || 0) - (a.likes || 0);
    if (sortMode === "views_desc") return (b.views || 0) - (a.views || 0);
    if (sortMode === "retweets_desc") return (b.retweets || 0) - (a.retweets || 0);
    if (sortMode === "date_desc") return new Date(b.created_at || 0) - new Date(a.created_at || 0);
    if (sortMode === "date_asc") return new Date(a.created_at || 0) - new Date(b.created_at || 0);
    return 0;
  });

  // 更新总数指示器
  const visibleBadge = document.getElementById("visibleCountBadge");
  if (visibleBadge) {
    visibleBadge.textContent = `显示 ${currentFilteredList.length} / ${tweets.length} 篇`;
  }

  const container = document.getElementById("tweetsContainer");
  if (!container) return;

  // 首次只流式渲染首批 18 条卡片 (BATCH_SIZE)，其余由触底无感加载追加
  renderedCount = 0;
  const initialBatchCount = Math.min(BATCH_SIZE, currentFilteredList.length);
  renderTweetsBatch(container, currentFilteredList, 0, initialBatchCount, false);
  renderedCount = initialBatchCount;

  // 挂载触底哨兵
  setupInfiniteScroll();

  if (resetScroll && window.scrollY > 300) {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

/**
 * 触底无限滚动哨兵 (IntersectionObserver)
 * 提前 350px 预加载下一批，滚动体验与 Twitter / X 完全一致
 */
function setupInfiniteScroll() {
  const container = document.getElementById("tweetsContainer");
  if (!container) return;

  // 清除旧的 observer
  if (sentinelObserver) {
    sentinelObserver.disconnect();
    sentinelObserver = null;
  }

  const hasMore = renderedCount < currentFilteredList.length;
  renderSentinel(container, hasMore, renderedCount, currentFilteredList.length);

  if (!hasMore) return;

  const sentinel = document.getElementById("infiniteScrollSentinel");
  if (!sentinel) return;

  sentinelObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting && renderedCount < currentFilteredList.length) {
        // 用户接近底部，流式追加下一批 18 条
        const nextBatchCount = Math.min(BATCH_SIZE, currentFilteredList.length - renderedCount);
        renderTweetsBatch(container, currentFilteredList, renderedCount, nextBatchCount, true);
        renderedCount += nextBatchCount;

        const stillHasMore = renderedCount < currentFilteredList.length;
        renderSentinel(container, stillHasMore, renderedCount, currentFilteredList.length);

        // 更新计数指示器
        const visibleBadge = document.getElementById("visibleCountBadge");
        if (visibleBadge) {
          visibleBadge.textContent = `显示 ${renderedCount} / ${currentFilteredList.length} (总 ${tweets.length}) 篇`;
        }

        if (!stillHasMore && sentinelObserver) {
          sentinelObserver.disconnect();
          sentinelObserver = null;
        }
      }
    }
  }, {
    root: null,
    rootMargin: "350px 0px", // 提前 350 像素触发，滑到前就已完成拼接，绝无卡顿
    threshold: 0.05
  });

  sentinelObserver.observe(sentinel);
}

window.dismissDiscovery = async function(tweetId) {
  const item = tweets.find(t => String(t.id) === String(tweetId));
  if (!item || item.source_kind !== "discovery") return;

  try {
    const result = await api.discoveryAction(tweetId, "not_interested");
    if (!result.ok || !result.data || !result.data.success) {
      throw new Error((result.data && (result.data.message || result.data.error)) || "隐藏失败");
    }

    recordTweetFeedback(tweetId, "not_interested", {
      surface: "feed",
      category: item.category || "",
      sub_category: item.sub_category || "",
      username: item.username || "",
      author: item.author || ""
    });

    tweets = tweets.filter(t => String(t.id) !== String(tweetId));
    window.tweets = tweets;
    try { localStorage.setItem(CACHE_KEY, JSON.stringify(tweets)); } catch (e) {}
    renderCategories();
    applyFiltersAndRender(false);
    showToast("已标记为不感兴趣，后续推荐会降低类似内容权重");
  } catch (err) {
    showToast("无法隐藏这条发现内容: " + err, false);
  }
};

window.toggleXBookmark = async function(tweetId) {
      if (!isXConfigured) {
        openAuthModal();
        showToast("请先在右上角配置 𝕏 凭证 (auth_token 与 ct0)", false);
        return;
      }

      const btn = document.getElementById(`btn-toggle-${tweetId}`);
      if (btn) btn.disabled = true;
      const feedbackItem = tweets.find(t => String(t.id) === String(tweetId));
      const isDiscoveryCandidate = Boolean(
        feedbackItem &&
        feedbackItem.source_kind === "discovery" &&
        feedbackItem.is_bookmark !== true
      );

      const currentlySaved = !isDiscoveryCandidate && !unbookmarkedIds.has(tweetId);
      const action = currentlySaved ? "delete" : "create";

      try {
        const resp = await fetch("/api/bookmark/toggle", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tweet_id: tweetId,
            action: action,
            source_kind: feedbackItem ? (feedbackItem.source_kind || "bookmark") : "bookmark"
          })
        });
        const result = await resp.json();

        if (result.success) {
          if (action === "delete") {
            unbookmarkedIds.add(tweetId);
            // 同步从当前页面内存列表中剔除
            tweets = tweets.filter(t => t.id !== tweetId);
            const brandSub = document.querySelector(".brand-sub");
            if (brandSub) {
              brandSub.textContent = `Curated Knowledge Portal · ${tweets.length} 篇推文`;
            }
            renderCategories();
            showToast(`已成功从 𝕏 云端移出书签并从 D1 数据库移除 #${tweetId}`);
          } else {
            unbookmarkedIds.delete(tweetId);
            if (feedbackItem) {
              feedbackItem.source_kind = "bookmark";
              feedbackItem.is_bookmark = true;
            }
            showToast(
              isDiscoveryCandidate
                ? `已将发现内容收藏到 𝕏 #${tweetId}`
                : `已成功重新添加至 𝕏 云端书签 #${tweetId}`
            );
          }
          saveUnbookmarked();
          recordTweetFeedback(tweetId, action === "delete" ? "unbookmark" : "bookmark", {
            surface: currentOpenTweet && currentOpenTweet.id === tweetId ? "reader" : "feed",
            category: feedbackItem ? (feedbackItem.category || "") : "",
            sub_category: feedbackItem ? (feedbackItem.sub_category || "") : "",
            username: feedbackItem ? (feedbackItem.username || "") : "",
            author: feedbackItem ? (feedbackItem.author || "") : ""
          });
          applyFiltersAndRender();

          if (currentOpenTweet && currentOpenTweet.id === tweetId) {
            updateModalBookmarkBtn();
          }
        } else {
          showToast(result.message || "X 平台接口同步失败", false);
        }
      } catch (err) {
        showToast("与本地后台服务通信异常: " + err, false);
      } finally {
        if (btn) btn.disabled = false;
      }
    };

// 挂载核心交互函数至全局 window
window.tweets = tweets;
window.unbookmarkedIds = unbookmarkedIds;
window.saveUnbookmarked = saveUnbookmarked;
window.getTheme = getTheme;
window.updateThemeToggleUI = updateThemeToggleUI;
window.toggleTheme = toggleTheme;
window.checkAuthStatus = checkAuthStatus;
window.refreshSyncStatusNotice = refreshSyncStatusNotice;
window.refreshDiscoveryStatusNotice = refreshDiscoveryStatusNotice;
window.renderCategories = renderCategories;
window.openDrawer = openDrawer;
window.closeDrawer = closeDrawer;
window.applyFiltersAndRender = applyFiltersAndRender;
window.setupInfiniteScroll = setupInfiniteScroll;
window.sortMode = sortMode;
window.activeCategory = activeCategory;
window.activeSubCategory = activeSubCategory;

// 页面 DOM 加载完毕后自动启动
document.addEventListener("DOMContentLoaded", initApp);

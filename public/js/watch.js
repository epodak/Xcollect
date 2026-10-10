// Active Research: one intent-driven workspace, not a second bookmark database.
// DOM text uses textContent; discoveries reuse xcollect's canonical card and reader.
(() => {
  "use strict";
  const el = id => document.getElementById(id);
  const state = {
    topics: [], selected: null, items: [], status: null,
    loading: false, sequence: 0, initialized: false,
  };
  window.watchReaderItems = [];
  window.watchTopicCount = 0;

  function notice(message) {
    const target = el("watchNotice");
    if (target) target.textContent = message || "";
  }
  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = String(content);
    return element;
  }
  function readSelection() {
    try { return localStorage.getItem("xcollect_watch_selected_v1"); }
    catch (_) { return null; }
  }
  function persistSelection(id) {
    try { localStorage.setItem("xcollect_watch_selected_v1", id); }
    catch (_) {}
  }
  function friendlyDate(raw) {
    if (!raw) return "尚无运行记录";
    const d = new Date(raw);
    return Number.isFinite(d.getTime()) ? d.toLocaleString() : "尚无运行记录";
  }
  function statusMessage(message, className) {
    const label = node("span", className || "", message);
    return label;
  }
  function reportForTopic(topicId) {
    const run = (state.status && state.status.summary) || {};
    const queries = Array.isArray(run.queries) ? run.queries : [];
    return queries.filter(q => String(q.topic_id) === String(topicId));
  }
  function selectedTopic() {
    return state.topics.find(t => t.id === state.selected) || null;
  }
  function renderRail() {
    const list = el("watchList");
    if (!list) return;
    list.replaceChildren();
    el("watchTopicCount").textContent = String(state.topics.length);
    const badge = el("watchScopeCount");
    const active = state.topics.filter(t => t.state === "active").length;
    window.watchTopicCount = state.topics.length;
    if (badge) badge.textContent = String(state.topics.length);
    if (window.activeFeedScope === "watch") {
      const count = el("visibleCountBadge");
      if (count) count.textContent = "主动探寻 · " + state.topics.length + " 个研究主题";
    }
    if (!state.topics.length) {
      list.append(node("p", "watch-rail-desc", "尚无研究任务。用上方按钮创建第一个问题。"));
      return;
    }
    for (const topic of state.topics) {
      const button = node("button", "watch-topic" + (topic.id === state.selected ? " active" : ""));
      button.type = "button";
      button.setAttribute("aria-pressed", topic.id === state.selected ? "true" : "false");
      const heading = node("div", "watch-topic-title");
      heading.append(node("span", "watch-dot" + (topic.state === "paused" ? " paused" : "")));
      heading.append(node("span", "watch-topic-title-text", topic.title));
      button.append(heading, node("div", "watch-topic-intent", topic.intent));
      button.addEventListener("click", () => selectTopic(topic.id));
      list.append(button);
    }
  }
  function renderTopicHeader() {
    const topic = selectedTopic();
    el("watchDetailOverline").textContent = topic ? "RESEARCH INTENT · " + (topic.state === "active" ? "追踪中" : "已暂停") : "SELECT A RESEARCH TOPIC";
    el("watchDetailTitle").textContent = topic ? topic.title : "选择一个研究主题";
    el("watchDetailIntent").textContent = topic ? topic.intent : "在左侧选择任务，查看它持续找到的新线索。";
    const tags = el("watchDirectionTags");
    tags.replaceChildren();
    if (topic) {
      for (const direction of topic.directions || []) {
        tags.append(node("span", "watch-tag", direction));
      }
    }
    const pause = el("watchPause");
    pause.hidden = !topic;
    if (topic) pause.textContent = topic.state === "active" ? "暂停追踪" : "恢复追踪";
  }
  function renderRunStatus() {
    const strip = el("watchStatusStrip");
    strip.replaceChildren();
    const topic = selectedTopic();
    if (!topic) return;
    if (topic.state === "paused") {
      strip.append(statusMessage("追踪已暂停 · 历史线索仍按 24 小时规则更新", "watch-status-failure"));
      return;
    }
    const summary = (state.status && state.status.summary) || {};
    const reports = reportForTopic(topic.id);
    const when = (state.status && state.status.last_attempt_at) || summary.attempted_at;
    strip.append(statusMessage("最近调度 " + friendlyDate(when)));
    if (!summary.attempted_at) {
      strip.append(statusMessage("等待首次调度", ""));
      return;
    }
    if (!reports.length) {
      strip.append(statusMessage("轮询按主题轮转 · 此主题尚未在最近一轮执行"));
      return;
    }
    const successful = reports.filter(r => !r.error);
    const pulled = reports.reduce((sum, r) => sum + Number(r.pulled_count || 0), 0);
    const accepted = reports.reduce((sum, r) => sum + Number(r.accepted_count || 0), 0);
    if (!successful.length) {
      strip.append(statusMessage("最近搜索失败", "watch-status-failure"));
      const firstError = reports.find(r => r.error);
      if (firstError) strip.append(statusMessage(String(firstError.error).slice(0, 150)));
    } else {
      strip.append(statusMessage("搜索 " + successful.length + "/" + reports.length + " 条查询成功", successful.length === reports.length ? "watch-status-good" : ""));
      strip.append(statusMessage("获取 " + pulled + " 条 · 通过初筛 " + accepted + " 条"));
      if (successful.length < reports.length) strip.append(statusMessage("部分查询失败", "watch-status-failure"));
    }
  }
  function getFilteredItems() {
    const phrase = (el("watchSearchInput").value || "").trim().toLowerCase();
    const sort = el("watchSort").value;
    const list = state.items.filter(item => {
      if (!phrase) return true;
      return [item.title, item.author, item.username, item.snippet, item.body_raw]
        .some(value => String(value || "").toLowerCase().includes(phrase));
    });
    list.sort((a, b) => {
      if (sort === "newest") return Date.parse(b.created_at || "") - Date.parse(a.created_at || "") || 0;
      if (sort === "popular") return Number(b.likes || 0) - Number(a.likes || 0);
      return Number(b.related_hot_score || 0) - Number(a.related_hot_score || 0);
    });
    return list;
  }
  function renderResults() {
    const container = el("watchResults");
    const empty = el("watchResultEmpty");
    if (!container || !empty) return;
    const topic = selectedTopic();
    const sorted = topic ? getFilteredItems() : [];
    el("watchResultCount").textContent = sorted.length + " 条" + (state.items.length !== sorted.length ? " / " + state.items.length : "");
    container.replaceChildren();
    empty.replaceChildren();
    empty.hidden = true;
    if (!topic) {
      empty.hidden = false;
      empty.append(node("strong", "", "从一个问题开始"));
      empty.append(node("p", "", "选择左侧的研究主题，或创建一个新的探索目标。"));
      return;
    }
    if (!sorted.length) {
      empty.hidden = false;
      if (state.items.length) {
        empty.append(node("strong", "", "没有符合筛选条件的线索"));
        empty.append(node("p", "", "清空筛选文本，或切换排序查看全部结果。"));
      } else if (topic.state === "paused") {
        empty.append(node("strong", "", "这个任务已暂停"));
        empty.append(node("p", "", "恢复追踪后将继续搜寻新内容；这里不会把过期推文当作持久收藏。"));
      } else {
        const reports = reportForTopic(topic.id);
        const failed = reports.length && reports.every(r => r.error);
        const fetched = reports.reduce((sum, r) => sum + Number(r.pulled_count || 0), 0);
        empty.append(node("strong", "", failed ? "最近一次搜索未成功" : "当前没有符合条件的新线索"));
        empty.append(node("p", "", failed
          ? "请查看上方的搜索状态；这不是已经确认的零结果。"
          : fetched > 0
            ? "近期原始结果曾被抓取，但可能因发布时间、回复或内容质量等规则被过滤。"
            : "研究任务会持续轮询。暂时没有结果不代表没有研究价值，也不代表已经收藏。"));
      }
      return;
    }
    // Canonical cards preserve images, videos, markdown copy, original links,
    // dislikes and the existing full-body reader. No second reader implementation.
    const fragment = document.createDocumentFragment();
    sorted.forEach((item, index) => {
      const template = document.createElement("template");
      template.innerHTML = generateTweetCardHtml(item, index);
      const card = template.content.firstElementChild;
      if (!card) return;
      if (item.discovery_query) {
        const details = node("details", "watch-evidence");
        const summary = node("summary", "", "检索命中依据");
        const query = node("code", "", item.discovery_query);
        details.append(summary, query);
        const main = card.querySelector(".card-main");
        if (main) main.append(details);
      }
      fragment.append(card);
    });
    container.replaceChildren(fragment);
    if (typeof window.observeTweetImpressions === "function") window.observeTweetImpressions(container);
  }
  async function selectTopic(id) {
    if (!state.topics.some(t => t.id === id)) return;
    state.selected = id;
    persistSelection(id);
    state.items = [];
    window.watchReaderItems = [];
    el("watchSearchInput").value = "";
    renderRail();
    renderTopicHeader();
    renderRunStatus();
    renderResults();
    notice("正在读取该主题的最新线索…");
    const seq = ++state.sequence;
    try {
      const response = await api.getWatchFeed(id);
      if (seq !== state.sequence || id !== state.selected) return;
      if (!response.ok || !response.data || !response.data.success) {
        throw new Error(response.data && response.data.error || "研究线索不可用");
      }
      state.items = Array.isArray(response.data.data) ? response.data.data : [];
      window.watchReaderItems = state.items;
      try { state.status = await api.getWatchStatus(); } catch (_) {}
      if (seq !== state.sequence || id !== state.selected) return;
      notice("");
      renderRunStatus();
      renderResults();
    } catch (error) {
      if (seq !== state.sequence) return;
      notice("读取主题失败：" + String(error.message || error));
      renderResults();
    }
  }
  async function refreshWatches(preferId) {
    const result = await api.getWatches();
    if (!result.success) throw new Error(result.error || "无法读取研究任务");
    state.topics = Array.isArray(result.topics) ? result.topics : [];
    if (!state.topics.some(t => t.id === state.selected)) state.selected = null;
    renderRail();
    const next = preferId || state.selected || readSelection() || (state.topics[0] && state.topics[0].id);
    if (next && state.topics.some(t => t.id === next)) await selectTopic(next);
    else {
      state.selected = null;
      state.items = [];
      window.watchReaderItems = [];
      renderTopicHeader();
      renderRunStatus();
      renderResults();
    }
  }
  function setCreateOpen(open) {
    el("watchCreatePanel").hidden = !open;
    el("watchCreateToggle").setAttribute("aria-expanded", open ? "true" : "false");
    if (open) el("watchTitle").focus();
  }
  async function togglePause() {
    const topic = selectedTopic();
    if (!topic) return;
    const button = el("watchPause");
    button.disabled = true;
    try {
      const newState = topic.state === "active" ? "paused" : "active";
      const res = await api.setWatchState(topic.id, newState);
      if (!res.ok || !res.data || !res.data.success) throw new Error(res.data && res.data.error || "状态更新失败");
      await refreshWatches(topic.id);
      notice(newState === "paused" ? "研究任务已暂停" : "研究任务已恢复，将在下一次调度继续寻找线索");
    } catch (err) { notice("切换追踪状态失败：" + String(err.message || err)); }
    finally { button.disabled = false; }
  }
  function bind() {
    if (state.initialized) return;
    state.initialized = true;
    el("watchCreateToggle").addEventListener("click", () => setCreateOpen(el("watchCreatePanel").hidden));
    el("watchCreateClose").addEventListener("click", () => setCreateOpen(false));
    el("watchPause").addEventListener("click", togglePause);
    el("watchSearchInput").addEventListener("input", renderResults);
    el("watchSort").addEventListener("change", renderResults);
    el("watchCreate").addEventListener("submit", async event => {
      event.preventDefault();
      const submit = el("watchSubmit");
      submit.disabled = true;
      try {
        const title = el("watchTitle").value.trim();
        const intent = el("watchIntent").value.trim();
        const directions = [...el("watchCreate").querySelectorAll('input[name="watchDirection"]:checked')].map(input => input.value);
        const res = await api.createWatch({title, intent, directions, mode:"balanced"});
        if (!res.ok || !res.data || !res.data.success) throw new Error(res.data && res.data.error || "创建失败");
        el("watchCreate").reset();
        setCreateOpen(false);
        await refreshWatches(res.data.topic.id);
        notice("研究主题已创建 · 搜索将在下一轮调度自动执行");
      } catch (err) { notice("创建失败：" + String(err.message || err)); }
      finally { submit.disabled = false; }
    });
  }
  window.watchDropItem = id => {
    if (!state.items.some(item => String(item.id) === String(id))) return;
    state.items = state.items.filter(item => String(item.id) !== String(id));
    window.watchReaderItems = state.items;
    renderResults();
  };
  window.addEventListener("xcollect:watch-open", () => {
    bind();
    refreshWatches(state.selected).catch(err => notice("加载研究工作台失败：" + String(err.message || err)));
  });
  document.addEventListener("DOMContentLoaded", () => {
    bind();
    // Fetch topic metadata only. A user opening the page does not launch X polling.
    api.getWatches().then(data => {
      if (!data.success) return;
      state.topics = Array.isArray(data.topics) ? data.topics : [];
      renderRail();
      if (window.activeFeedScope === "watch") refreshWatches().catch(() => {});
    }).catch(() => {});
  });
})();
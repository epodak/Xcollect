// Topic Watch UI: self-contained overlay on top of the existing Discovery app.
// Text is always inserted with textContent, never with untrusted HTML.
(() => {
  const el = id => document.getElementById(id);
  let selected = null;
  let watches = [];

  function note(message) { const n=el("watchNotice"); if(n) n.textContent=message; }
  function button(text, callback) {
    const b=document.createElement("button");
    b.type="button";b.textContent=text;b.className="btn-action";b.addEventListener("click",callback);
    return b;
  }
  async function refresh() {
    const result=await api.getWatches();
    if(!result.success) throw new Error(result.error || "Topic Watch unavailable");
    watches=result.topics || [];
    const list=el("watchList");list.replaceChildren();
    for(const watch of watches) {
      const wrap=document.createElement("div");wrap.className="topic-watch-chip";
      const open=button(watch.title,()=>openWatch(watch.id));
      if(watch.id===selected)open.classList.add("active");
      wrap.append(open);
      const toggle=button(watch.state==="active"?"暂停":"恢复",async()=>{
        const r=await api.setWatchState(watch.id,watch.state==="active"?"paused":"active");
        if(!r.ok){note(r.data.error || "Failed to update");return;}
        await refresh();
      });
      wrap.append(toggle);list.append(wrap);
    }
    if(!watches.length)note("尚未创建追踪主题。");
    else if(!selected)note("选择一个主题查看最近 24 小时的发现。");

  }
  async function openWatch(id) {
    selected=id;await refresh();
    const r=await api.getWatchFeed(id);
    if(!r.ok){note(r.data.error||"无法读取主题");return;}
    const results=el("watchResults");results.replaceChildren();
    const items=r.data.data||[];
    let statusText = "最近 24 小时匹配 " + items.length + " 条；这里只展示候选，不是 X 收藏。";
    try {
      const state = await api.getWatchStatus();
      const run = state.summary || {};
      if (run.state === "failed") {
        const failure = (run.queries || []).find(q => q.error);
        statusText += " 最近搜索失败：" + (run.error || (failure && failure.error) || "未知错误");
      } else if (run.state === "partial") {
        statusText += " 部分搜索失败，成功查询 " + run.successful_queries + "/" + run.total_queries + "。";
      } else if (run.attempted_at) {
        statusText += " 最近检查：" + new Date(run.attempted_at).toLocaleString()
          + "；成功查询 " + (run.successful_queries || 0) + "/" + (run.total_queries || 0) + "。";
        if (items.length === 0) {
          const forTopic = (run.queries || []).filter(q => q.topic_id === id);
          if (forTopic.length) {
            const fetched = forTopic.reduce((n, q) => n + (Number(q.pulled_count) || 0), 0);
            const admitted = forTopic.reduce((n, q) => n + (Number(q.accepted_count) || 0), 0);
            statusText += " 本轮原始结果 " + fetched + " 条，通过初筛 " + admitted + " 条。";
          }
        }
      }
    } catch (err) {
      statusText += " 运行状态暂不可用：" + String(err.message || err);
    }
    note(statusText);
    for(const item of items){
      const card=document.createElement("article");card.className="topic-watch-result";
      const h=document.createElement("h4");h.textContent=item.title||item.snippet||"Untitled";
      const summary=document.createElement("p");summary.textContent=(item.snippet||item.body_raw||"").slice(0,450);
      const actions=document.createElement("div");actions.className="topic-watch-actions";
      actions.append(button("复制",()=>{navigator.clipboard.writeText(item.body_raw||item.snippet||item.url||"").catch(err=>note(String(err)));}));
      if(/^https:\/\/x\.com\//.test(item.url||"") || /^https:\/\/twitter\.com\//.test(item.url||"")){
        const orig=document.createElement("a");orig.className="btn-action";orig.textContent="原推";
        orig.href=item.url;orig.target="_blank";orig.rel="noopener noreferrer";actions.append(orig);
      }
      actions.append(button("不想看",async()=>{
        const r=await api.discoveryAction(item.id,"not_interested");
        if(r.ok)card.remove();else note(r.data.error||"操作失败");
      }));
      card.append(h,summary,actions);results.append(card);
    }
  }
  document.addEventListener("DOMContentLoaded",()=>{
    const toggle=el("btnWatch");const panel=el("watchPanel");
    if(!toggle||!panel)return;
    toggle.addEventListener("click",()=>{
      panel.hidden=!panel.hidden;
      if(!panel.hidden)refresh().catch(e=>note(e.message));
    });
    el("watchCreate").addEventListener("submit",async event=>{
      event.preventDefault();
      const title=el("watchTitle").value.trim(),intent=el("watchIntent").value.trim();
      const checked=[...panel.querySelectorAll('input[name="watchDirection"]:checked')].map(x=>x.value);
      try{
        const r=await api.createWatch({title,intent,directions:checked,mode:"balanced"});
        if(!r.ok)throw new Error(r.data.error||"创建失败");
        el("watchCreate").reset();await refresh();await openWatch(r.data.topic.id);
      }catch(err){note(String(err.message||err));}
    });
  });
})();

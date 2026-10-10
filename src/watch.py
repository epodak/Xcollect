# -*- coding: utf-8 -*-
"""Persistent user intent over ephemeral Discovery observations.

Watch definitions and aggregate counters persist; unbookmarked source records do not.
All records are stored in the same authoritative D1 as Discovery.
"""
import json
import re
import uuid
from datetime import datetime, timezone

def _now():
    return datetime.now(timezone.utc).isoformat()

def _value(row, name, default=None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)

async def ensure_watch_schema(env):
    if not hasattr(env, "DB"):
        raise RuntimeError("Topic Watch requires D1")
    for sql in (
        "CREATE TABLE IF NOT EXISTS watch_topics (id TEXT PRIMARY KEY, title TEXT NOT NULL, intent TEXT NOT NULL, directions_json TEXT NOT NULL DEFAULT '[]', mode TEXT NOT NULL DEFAULT 'balanced', state TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS watch_queries (topic_id TEXT NOT NULL, query TEXT NOT NULL, PRIMARY KEY(topic_id,query))",
        "CREATE TABLE IF NOT EXISTS watch_candidate_matches (topic_id TEXT NOT NULL, tweet_id TEXT NOT NULL, query TEXT NOT NULL, matched_at TEXT NOT NULL, PRIMARY KEY(topic_id,tweet_id))",
        "CREATE INDEX IF NOT EXISTS idx_watch_match_tweet ON watch_candidate_matches(tweet_id)",
    ):
        await env.DB.prepare(sql).run()

def validate_watch(data):
    title = str(data.get("title", "") or "").strip()
    intent = str(data.get("intent", "") or "").strip()
    if not (2 <= len(title) <= 100 and 4 <= len(intent) <= 500):
        raise ValueError("title must be 2-100 characters; intent 4-500")
    if any(c in title for c in "\r\n"):
        raise ValueError("title must be one line")
    mode = str(data.get("mode", "balanced") or "balanced")
    if mode not in ("balanced", "strict", "explore"):
        raise ValueError("invalid watch mode")
    directions = data.get("directions", [])
    if not isinstance(directions, list) or len(directions) > 5 or any(not isinstance(x, str) or len(x)>48 for x in directions):
        raise ValueError("invalid directions")
    return title, intent, directions, mode

def query_seeds(title, directions):
    # X SearchTimeline queries are not instructions; escape syntax in user titles.
    escaped = re.sub(r'[^\w\s.\-]', ' ', title, flags=re.UNICODE).strip()
    escaped = re.sub(r"\s+", " ", escaped)[:90]
    if not escaped:
        return []
    root = '"' + escaped + '"'
    suffix = " -filter:replies -filter:retweets"
    # One broad query + one outcome-directed query; no arbitrary LLM query injection.
    variants = [root + suffix]
    if directions:
        terms = {
            "实际应用": "(built OR made OR app OR demo)",
            "开源项目": "(github OR open-source)",
            "技术演示": "(demo OR video OR showcase)",
            "测评比较": "(benchmark OR comparison OR test)",
            "行业观点": "(review OR analysis OR opinion)",
        }
        q = " OR ".join(terms.get(x, "") for x in directions if x in terms)
        if q:
            variants.append(root + " (" + q + ")" + suffix)
    return list(dict.fromkeys(variants))

async def create_watch(env, data):
    await ensure_watch_schema(env)
    title, intent, directions, mode = validate_watch(data)
    topic_id = uuid.uuid4().hex
    now = _now()
    await env.DB.prepare(
        "INSERT INTO watch_topics(id,title,intent,directions_json,mode,state,created_at,updated_at) VALUES(?,?,?,?,?,'active',?,?)"
    ).bind(topic_id,title,intent,json.dumps(directions,ensure_ascii=False),mode,now,now).run()
    for q in query_seeds(title, directions):
        await env.DB.prepare("INSERT INTO watch_queries(topic_id,query) VALUES(?,?)").bind(topic_id,q).run()
    return {"id":topic_id,"title":title,"intent":intent,"directions":directions,"mode":mode,"state":"active"}

async def list_watches(env):
    await ensure_watch_schema(env)
    rs = await env.DB.prepare("SELECT * FROM watch_topics ORDER BY created_at DESC").all()
    return [{
        "id":str(_value(r,"id","")),"title":str(_value(r,"title","")),
        "intent":str(_value(r,"intent","")),
        "directions":json.loads(_value(r,"directions_json","[]") or "[]"),
        "mode":str(_value(r,"mode","balanced")),"state":str(_value(r,"state","active"))
    } for r in rs.results]

async def set_watch_state(env, topic_id, state):
    await ensure_watch_schema(env)
    if state not in ("active","paused") or not re.fullmatch(r"[a-f0-9]{32}",str(topic_id)):
        raise ValueError("invalid watch state/id")
    await env.DB.prepare("UPDATE watch_topics SET state=?,updated_at=? WHERE id=?").bind(state,_now(),topic_id).run()
    return {"id":topic_id,"state":state}

async def watch_query_plan(env, limit=2):
    await ensure_watch_schema(env)
    rows = (await env.DB.prepare(
        "SELECT q.topic_id,q.query,t.title,t.intent,t.mode FROM watch_queries q "
        "JOIN watch_topics t ON t.id=q.topic_id WHERE t.state='active' ORDER BY q.topic_id,q.query"
    ).all()).results
    if not rows:
        return []
    # Independent round-robin cursor: the global taxonomy budget is untouched.
    from discovery import _meta_get, _meta_set
    cursor = int(await _meta_get(env,"watch:query_cursor","0") or "0") % len(rows)
    picked = [rows[(cursor+i)%len(rows)] for i in range(min(limit,len(rows)))]
    await _meta_set(env,"watch:query_cursor",(cursor+len(picked))%len(rows))
    return [{"topic_id":_value(r,"topic_id"),"query":_value(r,"query"),
             "intent":_value(r,"intent"),"mode":_value(r,"mode"),
             "category":"01_人工智能与Agent","sub_category":"用户主题追踪"} for r in picked]

async def save_matches(env, matches):
    await ensure_watch_schema(env)
    for topic_id, tweet_id, query in sorted(set(matches)):
        await env.DB.prepare(
            "INSERT OR IGNORE INTO watch_candidate_matches(topic_id,tweet_id,query,matched_at) VALUES(?,?,?,?)"
        ).bind(topic_id,tweet_id,query,_now()).run()

async def watch_feed(env, topic_id):
    await ensure_watch_schema(env)
    from discovery import _within_retention, _row_get, _json_obj
    rs = await env.DB.prepare(
        "SELECT d.*,m.query AS matched_query FROM watch_candidate_matches m "
        "JOIN discovery_candidates d ON d.tweet_id=m.tweet_id "
        "WHERE m.topic_id=? AND d.state NOT IN ('hidden','rejected','saved_pending','saved') "
        "ORDER BY d.final_score DESC LIMIT 200"
    ).bind(topic_id).all()
    items=[]
    for row in rs.results:
        if not _within_retention(_row_get(row,"created_at",""),_row_get(row,"first_seen_at","")):
            continue
        item=_json_obj(_row_get(row,"payload_json","{}"))
        item.update({
            "id":_row_get(row,"tweet_id",""),"title":_row_get(row,"title",""),
            "snippet":_row_get(row,"snippet",""),"body_raw":_row_get(row,"body_raw",""),
            "url":_row_get(row,"url",""),"author":_row_get(row,"author",""),
            "username":_row_get(row,"username",""),"created_at":_row_get(row,"created_at",""),
            "category":_row_get(row,"category",""),"sub_category":_row_get(row,"sub_category",""),
            "source_kind":"discovery","is_bookmark":False,
            "discovery_state":_row_get(row,"state",""),
            "related_hot_score":float(_row_get(row,"final_score",0) or 0),
            "discovery_query":_row_get(row,"matched_query",""),
            "topic_id":topic_id
        })
        items.append(item)
    return items

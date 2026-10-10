-- Cloudflare D1 Schema for Xcollect
-- 适用于 Twitter / X 书签智能看板数据持久化

CREATE TABLE IF NOT EXISTS tweets (
    id TEXT PRIMARY KEY,
    filename TEXT,
    category TEXT,
    sub_category TEXT,
    title TEXT,
    author TEXT,
    username TEXT,
    url TEXT,
    created_at TEXT,
    likes INTEGER DEFAULT 0,
    retweets INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    has_media INTEGER DEFAULT 0,
    media_type TEXT,
    images TEXT,
    videos TEXT,
    snippet TEXT,
    body_raw TEXT,
    body_html TEXT,
    avatar TEXT,
    classify_status TEXT DEFAULT 'settled'
);

CREATE INDEX IF NOT EXISTS idx_tweets_category ON tweets (category);
CREATE INDEX IF NOT EXISTS idx_tweets_likes ON tweets (likes DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_created_at ON tweets (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_classify_status ON tweets (classify_status);

-- 键值元数据表 (用于存储全局拓扑基准、重整化版本等)
CREATE TABLE IF NOT EXISTS meta_kv (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);



-- Append-only preference signals for the Personal Discovery Engine.
-- Ranking jobs aggregate this table; source content remains immutable.
CREATE TABLE IF NOT EXISTS feedback_events (
    event_id TEXT PRIMARY KEY,
    tweet_id TEXT NOT NULL,
    action TEXT NOT NULL,
    weight REAL NOT NULL,
    context TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_tweet ON feedback_events (tweet_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_action ON feedback_events (action);


-- Discovery Plane: ephemeral candidates are separate from durable bookmarks.
CREATE TABLE IF NOT EXISTS discovery_candidates (
    tweet_id TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    discovery_date TEXT NOT NULL,
    discovery_source TEXT,
    discovery_query TEXT,
    author TEXT,
    username TEXT,
    url TEXT,
    created_at TEXT,
    category TEXT,
    sub_category TEXT,
    title TEXT,
    snippet TEXT,
    body_raw TEXT,
    likes INTEGER DEFAULT 0,
    retweets INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    relevance_score REAL,
    quality_score REAL,
    novelty_score REAL,
    engagement_velocity REAL,
    source_score REAL,
    freshness_score REAL,
    penalty_score REAL,
    final_score REAL,
    ai_reason TEXT,
    ai_model TEXT,
    rank_version TEXT,
    state TEXT DEFAULT 'candidate',
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_discovery_date_score
    ON discovery_candidates (discovery_date, final_score DESC);
CREATE INDEX IF NOT EXISTS idx_discovery_state
    ON discovery_candidates (state);
CREATE INDEX IF NOT EXISTS idx_discovery_category
    ON discovery_candidates (category, sub_category);

-- Materialized daily attention budget. A row here means "selected to show",
-- not "saved to the user's permanent bookmark knowledge base".
CREATE TABLE IF NOT EXISTS daily_feed (
    feed_date TEXT NOT NULL,
    tweet_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    final_score REAL NOT NULL,
    category TEXT,
    sub_category TEXT,
    selected_at TEXT NOT NULL,
    PRIMARY KEY (feed_date, tweet_id)
);

CREATE INDEX IF NOT EXISTS idx_daily_feed_rank
    ON daily_feed (feed_date, rank ASC);


-- Resumable discovery state machine. Cron invocations advance durable stages
-- instead of requiring search + AI + publication to finish in one request.
CREATE TABLE IF NOT EXISTS discovery_runs (
    run_id TEXT PRIMARY KEY,
    discovery_date TEXT NOT NULL,
    state TEXT NOT NULL,
    trigger TEXT,
    query_plan_json TEXT,
    candidate_ids_json TEXT,
    batch_request_id TEXT,
    batch_model TEXT,
    raw_count INTEGER DEFAULT 0,
    accepted_count INTEGER DEFAULT 0,
    rejected_count INTEGER DEFAULT 0,
    selected_count INTEGER DEFAULT 0,
    error TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_discovery_runs_state
    ON discovery_runs (state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_discovery_runs_date
    ON discovery_runs (discovery_date, updated_at DESC);

-- Persistent Topic Watch intent; candidates retain the Discovery 24h TTL.
CREATE TABLE IF NOT EXISTS watch_topics (id TEXT PRIMARY KEY, title TEXT NOT NULL, intent TEXT NOT NULL, directions_json TEXT NOT NULL DEFAULT '[]', mode TEXT NOT NULL DEFAULT 'balanced', state TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watch_queries (topic_id TEXT NOT NULL, query TEXT NOT NULL, PRIMARY KEY(topic_id,query));
CREATE TABLE IF NOT EXISTS watch_candidate_matches (topic_id TEXT NOT NULL, tweet_id TEXT NOT NULL, query TEXT NOT NULL, matched_at TEXT NOT NULL, PRIMARY KEY(topic_id,tweet_id));
CREATE INDEX IF NOT EXISTS idx_watch_match_tweet ON watch_candidate_matches(tweet_id);

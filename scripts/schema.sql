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


-- D1: 仅为永久书签 tweets 建立外部内容 FTS5 索引。
-- 不触碰 discovery_candidates，也不制造新的事实真源。
CREATE VIRTUAL TABLE IF NOT EXISTS bookmark_fts USING fts5(
    title, body_raw, content='tweets', content_rowid='rowid', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS bookmark_fts_insert AFTER INSERT ON tweets BEGIN
    INSERT INTO bookmark_fts(rowid, title, body_raw)
    VALUES (new.rowid, new.title, new.body_raw);
END;

CREATE TRIGGER IF NOT EXISTS bookmark_fts_delete AFTER DELETE ON tweets BEGIN
    INSERT INTO bookmark_fts(bookmark_fts, rowid, title, body_raw)
    VALUES ('delete', old.rowid, old.title, old.body_raw);
END;

CREATE TRIGGER IF NOT EXISTS bookmark_fts_update AFTER UPDATE OF title, body_raw ON tweets BEGIN
    INSERT INTO bookmark_fts(bookmark_fts, rowid, title, body_raw)
    VALUES ('delete', old.rowid, old.title, old.body_raw);
    INSERT INTO bookmark_fts(rowid, title, body_raw)
    VALUES (new.rowid, new.title, new.body_raw);
END;

-- 补全历史书签；重复执行不会更改用户收藏内容。
INSERT INTO bookmark_fts(bookmark_fts) VALUES ('rebuild');

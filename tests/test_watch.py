# -*- coding: utf-8 -*-
"""Fast deterministic Topic Watch contract checks (no credentials needed)."""
from src.watch import validate_watch, query_seeds
from pathlib import Path

def test_watch_validation():
    title,intent,directions,mode=validate_watch({"title":"Claude Opus 5.5","intent":"Find real applications","directions":["实际应用","开源项目"]})
    assert title=="Claude Opus 5.5"
    assert mode=="balanced"
    assert len(query_seeds(title,directions))==2
    assert all("-filter:replies" in q for q in query_seeds(title,directions))

def test_watch_query_escape():
    queries=query_seeds('Opus 5.5" OR from:admin',["开源项目"])
    assert all('from:admin' not in q for q in queries)
    assert all('-filter:retweets' in q for q in queries)

def test_watch_invariants():
    schema=(Path(__file__).parents[1]/"scripts/schema.sql").read_text(encoding="utf-8")
    assert "PRIMARY KEY(topic_id,tweet_id)" in schema
    discovery=(Path(__file__).parents[1]/"src/discovery.py").read_text(encoding="utf-8")
    assert "purge_expired_discovery(env)" in discovery
    assert "await save_matches(env, topic_matches)" in discovery

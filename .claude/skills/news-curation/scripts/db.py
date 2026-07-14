#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""공용 DB 헬퍼 + 스키마. SQLite(stdlib) 사용 — 무의존, Windows 안정.

DB 경로 기본값: 프로젝트루트/data/news.db (환경변수 NEWS_DB로 override).
스키마:
  articles         — 수집 기사(중복 병합 후 1행/스토리)
  collection_runs  — 수집 실행 이력
"""
import os, sqlite3


def project_root():
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        if os.path.isdir(os.path.join(here, ".claude")) or os.path.isdir(os.path.join(here, "data")):
            return here
        here = os.path.dirname(here)
    return os.getcwd()


def db_path():
    return os.environ.get("NEWS_DB") or os.path.join(project_root(), "data", "news.db")


def connect():
    p = db_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
  id               TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  description      TEXT,
  url              TEXT,
  naver_url        TEXT,
  source           TEXT,
  source_tier      INTEGER DEFAULT 3,
  pub_date         TEXT,
  category         TEXT,
  keywords_matched TEXT,          -- JSON array
  methods          TEXT,          -- JSON array: api|web|crawl|blog (교차출처)
  corroboration    INTEGER DEFAULT 1,  -- 몇 개 소스/방법이 같은 스토리를 다뤘나
  score            REAL DEFAULT 0,
  relevance        INTEGER DEFAULT 1,  -- 검색어가 실제 제목/본문에 존재(1) 여부
  watch_hits       TEXT DEFAULT '[]',  -- JSON: 매칭된 관심물건 [{id,name,term}]
  first_seen       TEXT,
  last_seen        TEXT,
  raw              TEXT           -- JSON
);
CREATE INDEX IF NOT EXISTS idx_articles_cat  ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_pub  ON articles(pub_date);
CREATE INDEX IF NOT EXISTS idx_articles_score ON articles(score);

CREATE TABLE IF NOT EXISTS collection_runs (
  run_id      TEXT PRIMARY KEY,
  started_at  TEXT,
  finished_at TEXT,
  new_count   INTEGER DEFAULT 0,
  merged_count INTEGER DEFAULT 0,
  total_after INTEGER DEFAULT 0,
  notes       TEXT
);

-- 관심물건↔뉴스 매칭 알림 큐 (중복 알림 방지)
CREATE TABLE IF NOT EXISTS alerts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  property_id   TEXT,
  property_name TEXT,
  article_id    TEXT,
  matched_term  TEXT,
  created_at    TEXT,
  notified      INTEGER DEFAULT 0,
  UNIQUE(property_id, article_id)
);
"""


def _migrate(con):
    """기존 DB에 신규 컬럼이 없으면 추가."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(articles)").fetchall()}
    if "relevance" not in cols:
        con.execute("ALTER TABLE articles ADD COLUMN relevance INTEGER DEFAULT 1")
    if "watch_hits" not in cols:
        con.execute("ALTER TABLE articles ADD COLUMN watch_hits TEXT DEFAULT '[]'")


def init(con):
    con.executescript(SCHEMA)
    _migrate(con)
    con.commit()


if __name__ == "__main__":
    con = connect()
    init(con)
    print("DB ready:", db_path())

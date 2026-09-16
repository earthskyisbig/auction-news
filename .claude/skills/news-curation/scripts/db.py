#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""공용 DB 헬퍼 + 스키마. SQLite(stdlib) 사용 — 무의존, Windows 안정.

DB 경로 기본값: 프로젝트루트/data/news.db (환경변수 NEWS_DB로 override).
스키마:
  articles         — 수집 기사(중복 병합 후 1행/스토리)
  collection_runs  — 수집 실행 이력
"""
import gzip, json, os, shutil, sqlite3, sys


def project_root():
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        if os.path.isdir(os.path.join(here, ".claude")) or os.path.isdir(os.path.join(here, "data")):
            return here
        here = os.path.dirname(here)
    return os.getcwd()


def db_path():
    return os.environ.get("NEWS_DB") or os.path.join(project_root(), "data", "news.db")


def gz_path():
    return db_path() + ".gz"


def inflate_if_needed():
    """저장소에는 news.db.gz만 커밋된다(원본 SQLite가 GitHub 100MB 한도를 넘어 2026-09-10부터
    푸시가 7일간 실패했었다). 작업용 news.db가 없거나 .gz보다 오래됐으면 .gz에서 풀어 쓴다.
    이렇게 해야 git pull 뒤 예전 로컬 DB를 정본으로 착각하는 사고가 안 난다."""
    p, g = db_path(), gz_path()
    if not os.path.isfile(g):
        return
    if os.path.isfile(p) and os.path.getmtime(p) >= os.path.getmtime(g):
        return
    sys.stderr.write("INFO: news.db.gz가 더 최신 → 작업용 news.db 재생성\n")
    with gzip.open(g, "rb") as src, open(p + ".tmp", "wb") as dst:
        shutil.copyfileobj(src, dst)
    for ext in ("-wal", "-shm"):
        try:
            os.remove(p + ext)
        except FileNotFoundError:
            pass
    os.replace(p + ".tmp", p)


def deflate():
    """작업용 news.db → 커밋용 news.db.gz. WAL을 본 파일로 합친 뒤 압축한다."""
    p, g = db_path(), gz_path()
    con = sqlite3.connect(p)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    with open(p, "rb") as src, gzip.open(g + ".tmp", "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)
    os.replace(g + ".tmp", g)
    return os.path.getsize(g)


# 적재 후에도 계속 쓰는 raw 키. 나머지(네이버 원본 item 등)는 감사용이라 일주일이면 충분하다.
RAW_KEEP = {"trusted", "official", "section", "press_id", "blog_id", "domain"}


def slim_raw(con, older_than_days=7):
    """오래된 행의 raw를 플래그만 남기고 비운다. raw가 DB의 절반을 차지해 100MB 한도를 넘겼다.
    배지·relevance 판단에 쓰는 키는 남기므로 리포트 동작은 변하지 않는다."""
    rows = con.execute(
        "SELECT id, raw FROM articles WHERE pub_date < date('now', ?) AND length(raw) > 80",
        (f"-{older_than_days} days",)).fetchall()
    for r in rows:
        try:
            d = json.loads(r["raw"] or "{}")
        except Exception:
            d = {}
        slim = {k: v for k, v in d.items() if k in RAW_KEEP}
        con.execute("UPDATE articles SET raw=? WHERE id=?", (json.dumps(slim, ensure_ascii=False), r["id"]))
    con.commit()
    return len(rows)


def connect():
    p = db_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    inflate_if_needed()
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

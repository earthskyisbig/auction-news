#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""데일리 뉴스 빌드 엔트리포인트 (수집 → 적재 → 리포트). CI/로컬 공용.

키는 환경변수(GitHub Secrets 또는 로컬 .env)에서 읽는다:
  NAVER_CLIENT_ID, NAVER_CLIENT_SECRET  (없으면 API·블로그 채널 건너뜀)
텔레그램 발송은 별도(send_digest.py) — 이 스크립트는 '빌드'만 담당.

무의존(Python stdlib만). GitHub Actions ubuntu-latest에서 pip install 없이 동작.
"""
import os, subprocess, sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")
RUN_ID = datetime.now(KST).strftime("ci-%Y-%m-%dT%H%M")

NAVER = ".claude/skills/naver-news-api/scripts"
CUR = ".claude/skills/news-curation/scripts"
REP = ".claude/skills/news-report/scripts"


def load_env():
    """로컬 .env 로드(이미 설정된 값 유지). CI에선 .env 없이 env 변수 그대로 사용."""
    env = os.path.join(ROOT, ".env")
    if os.path.isfile(env):
        for line in open(env, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run(args, required=False):
    print(f"▶ {' '.join(args)}", flush=True)
    r = subprocess.run([PY] + args, cwd=ROOT)
    if r.returncode != 0:
        msg = f"단계 실패: {args[0]}"
        if required:
            sys.exit(f"ERROR(필수): {msg}")
        print(f"WARN(계속): {msg}", flush=True)


def main():
    load_env()
    has_naver = bool(os.environ.get("NAVER_CLIENT_ID") and os.environ.get("NAVER_CLIENT_SECRET"))
    inputs = []

    if has_naver:
        run([f"{NAVER}/naver_news_search.py", "--config", "config/keywords.json",
             "--watchlist", "config/watchlist.json", "--out", "_workspace/api_raw.json"])
        run([f"{NAVER}/naver_blog_search.py", "--config", "config/keywords.json",
             "--watchlist", "config/watchlist.json", "--out", "_workspace/blog_raw.json"])
        inputs = ["_workspace/api_raw.json", "_workspace/blog_raw.json"]
    else:
        print("WARN: NAVER 키 없음 → API·블로그 수집 건너뜀 (기존 DB로 리포트만)", flush=True)

    if inputs:
        run([f"{CUR}/ingest.py", "--inputs", *inputs, "--sources", "config/sources.json",
             "--watchlist", "config/watchlist.json", "--run-id", RUN_ID], required=True)

    # 리포트 2종
    run([f"{REP}/build_report.py", "--days", "7", "--min-score", "45", "--relevant-only",
         "--out", f"reports/news_briefing_{TODAY}.html"])
    run([f"{REP}/build_report.py", "--days", "3650", "--min-score", "0",
         "--out", f"reports/news_archive_{TODAY}.html"])
    print(f"✅ 빌드 완료: {TODAY}", flush=True)


if __name__ == "__main__":
    main()

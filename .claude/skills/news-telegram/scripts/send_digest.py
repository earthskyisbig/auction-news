#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이제스트 1회 발송 (cron/Task Scheduler·봇 스케줄러·수동 공용).

사용:
  python send_digest.py                # DB에서 바로 다이제스트 발송
  python send_digest.py --collect      # 발송 전 네이버 API 수집→적재 후 발송(완전 자동)

--collect: 아침 자동 발송용. API 채널만 수집(무의존·빠름). 웹/크롤 보강은 대화형 실행에서.
"""
import argparse, os, subprocess, sys
from datetime import datetime
import tg_common as T


def run_collection():
    """API 수집 → 3(있는)채널 적재. 헤드리스 자동화 경로."""
    root = T.project_root()
    py = sys.executable
    ws = os.path.join(root, "_workspace")
    api_out = os.path.join(ws, "api_raw.json")
    blog_out = os.path.join(ws, "blog_raw.json")
    cfgk = os.path.join(root, "config/keywords.json")
    wl = os.path.join(root, "config/watchlist.json")
    steps = [
        # 카테고리 + 워치리스트 키워드 함께 수집
        [py, os.path.join(root, ".claude/skills/naver-news-api/scripts/naver_news_search.py"),
         "--config", cfgk, "--watchlist", wl, "--out", api_out],
        [py, os.path.join(root, ".claude/skills/naver-news-api/scripts/naver_blog_search.py"),
         "--config", cfgk, "--watchlist", wl, "--out", blog_out],
        [py, os.path.join(root, ".claude/skills/news-curation/scripts/ingest.py"),
         "--inputs", api_out, blog_out, "--sources", os.path.join(root, "config/sources.json"),
         "--watchlist", wl, "--run-id", datetime.now().strftime("auto-%Y-%m-%dT%H%M")],
    ]
    for cmd in steps:
        r = subprocess.run(cmd, capture_output=True, text=True)
        sys.stderr.write(r.stderr[-400:] if r.stderr else "")
        if r.returncode != 0:
            sys.stderr.write(f"WARN: 수집 단계 실패(계속): {cmd[1]}\n")
    # 관심물건 매칭 즉시 알림(다이제스트와 별개)
    try:
        subprocess.run([py, os.path.join(root, ".claude/skills/news-telegram/scripts/watch_alert.py")])
    except Exception as e:
        sys.stderr.write(f"watch_alert 경고: {e}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true", help="발송 전 API 수집·적재")
    args = ap.parse_args()

    token, chat = T.creds()
    if not token or not chat:
        sys.stderr.write("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정 (.env)\n")
        sys.exit(2)

    if args.collect:
        run_collection()

    cfg = T.load_config()
    chunks, n = T.build_digest_chunks(cfg)
    ok_all = True
    for i, text in enumerate(chunks):
        res = T.send_message(token, chat, text)
        if not res.get("ok"):
            ok_all = False
            sys.stderr.write(f"청크 {i+1}/{len(chunks)} 실패: {res}\n")
    sys.stderr.write(f"{'OK' if ok_all else 'FAIL'}: 다이제스트 발송 ({n}개 헤드라인, {len(chunks)}개 메시지) → chat {chat}\n")
    if not ok_all:
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""텔레그램 공용 헬퍼 (stdlib 전용). 토큰 로드·config·DB 조회·다이제스트 텍스트 구성."""
import json, os, sqlite3, sys, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

CATS = [
    ("watch", "관심 지역·물건", "⭐"),
    ("policy", "정책·규제·세제", "🔴"),
    ("market", "시장·시세 동향", "🔵"),
    ("auction", "경매·공매", "🟠"),
    ("redevelopment", "재개발·재건축", "🟢"),
    ("subscription", "분양·청약", "🩷"),
    ("urban_plan", "도시계획·공공주택", "🟣"),
    ("industrial", "산업단지·신도시·뉴타운", "🔷"),
    ("local", "지역단지·호재", "🟩"),
]
CAT_LABEL = {c: l for c, l, _ in CATS}
CAT_EMOJI = {c: e for c, _, e in CATS}
KST = timezone(timedelta(hours=9))


def project_root():
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        if os.path.isdir(os.path.join(here, ".claude")):
            return here
        here = os.path.dirname(here)
    return os.getcwd()


def load_env():
    root = project_root()
    env = os.path.join(root, ".env")
    if os.path.isfile(env):
        for line in open(env, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def creds():
    load_env()
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    return tok, chat


def config_path():
    return os.path.join(project_root(), "config", "telegram.json")


def load_config():
    return json.load(open(config_path(), encoding="utf-8"))


def save_config(cfg):
    with open(config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def db_path():
    return os.environ.get("NEWS_DB") or os.path.join(project_root(), "data", "news.db")


def api(token, method, params=None, timeout=35):
    """Telegram Bot API 호출 (stdlib)."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def send_message(token, chat_id, text, disable_preview=True):
    return api(token, "sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "true" if disable_preview else "false",
    }, timeout=20)


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


MAX_BYTES = 3800  # 텔레그램 4096 제한 안전 여유. 줄 단위로만 분할(태그 절단 방지).


def _blocks(cfg):
    """(header, [category_block_lines...], footer, total) 구성. 각 블록은 완결된 줄 목록."""
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    days = cfg.get("days", 1)
    min_score = cfg.get("min_score", 45)
    top_n = cfg.get("top_n", 5)
    rel_only = cfg.get("relevant_only", True)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rel_sql = " AND relevance=1" if rel_only else ""

    header = [f"🏢 <b>부동산 뉴스 브리핑</b>",
              f"📅 {datetime.now(KST).strftime('%Y년 %m월 %d일')} 기준 · 최근 {days}일 · 스코어 {min_score}+", ""]
    blocks, total = [], 0
    for c, label, emoji in CATS:
        if not cfg.get("categories", {}).get(c, True):
            continue
        rows = con.execute(
            "SELECT title,url,naver_url,source,score,corroboration FROM articles "
            f"WHERE category=? AND (pub_date>=? OR pub_date='') AND score>=?{rel_sql} "
            "ORDER BY score DESC, pub_date DESC LIMIT ?",
            (c, since, min_score, top_n)).fetchall()
        if not rows:
            continue
        cnt = con.execute(
            f"SELECT COUNT(*) FROM articles WHERE category=? AND (pub_date>=? OR pub_date='') AND score>=?{rel_sql}",
            (c, since, min_score)).fetchone()[0]
        blk = [f"{emoji} <b>{esc(label)}</b> ({cnt}건)"]
        for r in rows:
            total += 1
            link = r["url"] or r["naver_url"] or ""
            t = esc(r["title"][:60])
            corr = f" 🔗{r['corroboration']}" if r["corroboration"] and r["corroboration"] >= 2 else ""
            title_html = f'<a href="{esc(link)}">{t}</a>' if link else t
            blk.append(f"  <b>{r['score']:.0f}</b> {title_html}{corr} <i>{esc(r['source'])}</i>")
        blk.append("")
        blocks.append(blk)
    footer = ["──────────",
              "⚙️ /status 설정확인 · /time 발송시간 · /categories 카테고리 · /now 지금발송"]
    return header, blocks, footer, total


def build_digest_chunks(cfg):
    """4096 제한을 넘지 않도록 카테고리 블록을 여러 메시지로 안전 분할.
    반환: (chunks: list[str], total: int). 줄/태그를 절대 중간에서 자르지 않는다."""
    header, blocks, footer, total = _blocks(cfg)
    if total == 0:
        return ["\n".join(header + ["📭 해당 조건에 새 기사가 없습니다."] + footer)], 0

    chunks, cur = [], list(header)

    def size(lines):
        return len("\n".join(lines).encode("utf-8"))

    for blk in blocks:
        if size(cur + blk) > MAX_BYTES and len(cur) > len(header):
            chunks.append(cur)
            cur = list(blk)
        else:
            cur += blk
        # 단일 블록이 예산 초과 시 줄 단위로 강제 분할
        while size(cur) > MAX_BYTES and len(cur) > 1:
            spill = cur.pop()
            if size(cur) <= MAX_BYTES:
                chunks.append(cur)
                cur = [spill]
    chunks.append(cur)
    # footer는 마지막 청크에 (작으므로 실제 한도 4096 여유까지 허용)
    if size(chunks[-1] + footer) <= 4050:
        chunks[-1] += footer
    else:
        chunks.append(footer)
    texts = ["\n".join(ch).rstrip() for ch in chunks]
    return texts, total


def build_digest(cfg):
    """단일 텍스트 호환용(첫 청크 반환). 다중 발송은 build_digest_chunks 사용."""
    texts, total = build_digest_chunks(cfg)
    return texts[0], total

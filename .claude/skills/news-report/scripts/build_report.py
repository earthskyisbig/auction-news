#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite(news.db)에서 기사를 읽어 부동산 뉴스 브리핑 HTML 리포트 생성.

사용:
  python build_report.py --days 7 --out reports/news_2026-07-14.html
  python build_report.py --since 2026-07-01 --min-score 30 --out reports/report.html

구성: 대형 기준일 헤더 → sticky 카테고리 네비(클릭 시 해당 섹션 이동) →
      카테고리별 요약(톱 헤드라인) → 카테고리별 전체 카드(스코어순).
디자인: 지식베이스 표준(다크 네비 #1e293b, 화이트 콘텐츠, 카테고리 색상코딩).
"""
import argparse, html, json, os, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "news-curation", "scripts"))
import db as D

# (key, 라벨, 색상) — 순서가 네비·섹션 순서
CATS = [
    ("watch", "⭐ 관심 지역·물건", "#e11d48"),
    ("policy", "정책·규제·세제", "#dc2626"),
    ("market", "시장·시세 동향", "#3b82f6"),
    ("auction", "경매·공매", "#d97706"),
    ("redevelopment", "재개발·재건축", "#16a34a"),
    ("subscription", "분양·청약", "#db2777"),
    ("urban_plan", "도시계획·공공주택", "#7c3aed"),
    ("industrial", "산업단지·신도시·뉴타운", "#0891b2"),
    ("local", "지역단지·호재", "#0d9488"),
]


def esc(s):
    return html.escape(s or "")


def fetch(con, since_iso, min_score, relevant_only=False):
    q = "SELECT * FROM articles WHERE (pub_date>=? OR pub_date='') AND score>=?"
    if relevant_only:
        q += " AND relevance=1"
    q += " ORDER BY score DESC, pub_date DESC"
    rows = con.execute(q, (since_iso, min_score)).fetchall()
    return [dict(r) for r in rows]


def fmt_date(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%m/%d %H:%M")
    except Exception:
        return iso or "-"


def latest_pubdate(articles):
    ds = [a["pub_date"] for a in articles if a.get("pub_date")]
    if not ds:
        return None
    try:
        return max(datetime.fromisoformat(d.replace("Z", "+00:00")) for d in ds)
    except Exception:
        return None


def card(a):
    methods = json.loads(a["methods"] or "[]")
    kws = json.loads(a["keywords_matched"] or "[]")
    badge = ""
    if a["corroboration"] and a["corroboration"] >= 2:
        badge = f'<span class="badge corr">교차출처 {a["corroboration"]}</span>'
    tier_b = f'<span class="badge tier{a["source_tier"]}">T{a["source_tier"]}</span>'
    method_b = "".join(f'<span class="m">{esc(m)}</span>' for m in methods)
    kw_b = "".join(f'<span class="kw">{esc(k)}</span>' for k in kws[:4])
    link = a["url"] or a["naver_url"] or ""
    title_html = (f'<a class="title" href="{esc(link)}" target="_blank" rel="noopener">{esc(a["title"])}</a>'
                  if link else f'<span class="title">{esc(a["title"])}</span>')
    return f"""
    <div class="card">
      <div class="card-top"><span class="score">{a['score']:.0f}</span>{title_html}</div>
      <p class="desc">{esc(a['description'])[:220]}</p>
      <div class="meta">
        <span class="src">{esc(a['source']) or '출처미상'}</span>
        <span class="dt">{fmt_date(a['pub_date'])}</span>
        {tier_b}{badge}{method_b}
      </div>
      <div class="kws">{kw_b}</div>
    </div>"""


def build(articles, meta):
    by_cat = {}
    for a in articles:
        by_cat.setdefault(a["category"], []).append(a)
    present = [(c, l, col) for c, l, col in CATS if by_cat.get(c)]

    # sticky 네비 버튼 (클릭 시 해당 섹션으로 이동)
    nav = "".join(
        f'<a class="navbtn" href="#cat-{c}" style="--c:{col}"><span class="nb-n">{len(by_cat.get(c, []))}</span>{esc(l)}</a>'
        for c, l, col in present)

    # 카테고리별 요약 (톱 헤드라인 3개)
    summ = ""
    for c, l, col in present:
        items = by_cat[c]
        tops = ""
        for a in items[:3]:
            link = a["url"] or a["naver_url"] or ""
            t = esc(a["title"])
            corr = f' <em class="s-corr">교차{a["corroboration"]}</em>' if a["corroboration"] >= 2 else ""
            row = (f'<a href="{esc(link)}" target="_blank" rel="noopener">{t}</a>' if link else f'<span>{t}</span>')
            tops += f'<li><b class="s-score">{a["score"]:.0f}</b>{row}{corr}<span class="s-src">{esc(a["source"])}</span></li>'
        summ += f"""
      <div class="scard" style="--c:{col}">
        <a class="s-head" href="#cat-{c}"><span class="dot"></span>{esc(l)}<span class="s-cnt">{len(items)}건</span></a>
        <ul class="s-list">{tops}</ul>
        <a class="s-more" href="#cat-{c}">전체 {len(items)}건 보기 ↓</a>
      </div>"""

    # 카테고리별 전체 섹션
    sections = ""
    for c, l, col in present:
        items = by_cat[c]
        cards = "".join(card(a) for a in items)
        sections += f"""
      <section id="cat-{c}" class="cat" style="--c:{col}">
        <h2><span class="dot"></span>{esc(l)} <span class="cnt">{len(items)}건</span>
          <a class="top-link" href="#top">↑ 맨 위로</a></h2>
        <div class="grid">{cards}</div>
      </section>"""

    return f"""<!doctype html><html lang="ko"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>부동산 뉴스 브리핑 · {meta['date_kr']}</title>
<style>
:root{{--nav:#1e293b;--bg:#f1f5f9;--card:#fff;--tx:#0f172a;--mut:#64748b}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{font-family:'Malgun Gothic',-apple-system,sans-serif;background:var(--bg);color:var(--tx);line-height:1.5}}
a{{color:inherit}}
/* 대형 기준일 헤더 */
header{{background:linear-gradient(135deg,#1e293b,#334155);color:#fff;padding:38px 32px 30px}}
header .asof{{font-size:15px;color:#93c5fd;font-weight:700;letter-spacing:.5px}}
header h1{{font-size:34px;font-weight:800;margin:6px 0 10px;line-height:1.2}}
header h1 .em{{color:#60a5fa}}
header .sub{{color:#cbd5e1;font-size:13px}}
header .stat{{display:inline-block;margin-right:14px;color:#e2e8f0}}
header .stat b{{color:#fff}}
/* sticky 카테고리 네비 */
.nav{{position:sticky;top:0;z-index:20;background:#fff;border-bottom:1px solid #e2e8f0;
  padding:12px 20px;display:flex;flex-wrap:wrap;gap:8px;box-shadow:0 2px 8px rgba(0,0,0,.04)}}
.navbtn{{display:inline-flex;align-items:center;gap:7px;padding:7px 14px;border-radius:20px;
  background:#f8fafc;border:1px solid #e2e8f0;border-left:4px solid var(--c);
  font-size:13px;font-weight:700;text-decoration:none;color:#334155;transition:.15s;cursor:pointer}}
.navbtn:hover{{background:var(--c);color:#fff;border-color:var(--c)}}
.navbtn:hover .nb-n{{color:#fff}}
.nb-n{{color:var(--c);font-weight:800;font-size:15px}}
main{{max-width:1120px;margin:0 auto;padding:24px 20px 60px}}
/* 카테고리별 요약 */
.summary-h{{font-size:20px;font-weight:800;margin:6px 0 16px;display:flex;align-items:center;gap:8px}}
.summary{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px;margin-bottom:40px}}
.scard{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px;border-top:4px solid var(--c)}}
.s-head{{display:flex;align-items:center;gap:8px;font-size:16px;font-weight:800;text-decoration:none;color:var(--tx)}}
.s-head:hover{{color:var(--c)}}
.s-head .dot{{width:11px;height:11px;border-radius:50%;background:var(--c)}}
.s-head .s-cnt{{margin-left:auto;font-size:12px;color:var(--mut);font-weight:700}}
.s-list{{list-style:none;margin:12px 0 8px}}
.s-list li{{display:flex;align-items:baseline;gap:7px;padding:5px 0;font-size:13px;border-bottom:1px dashed #eef2f6}}
.s-list li:last-child{{border:0}}
.s-score{{flex:none;background:var(--c);color:#fff;font-size:11px;font-weight:800;padding:1px 6px;border-radius:5px}}
.s-list a,.s-list span{{text-decoration:none;color:#334155}}
.s-list a:hover{{color:var(--c);text-decoration:underline}}
.s-corr{{flex:none;background:#fef3c7;color:#b45309;font-size:10px;font-style:normal;font-weight:700;padding:1px 5px;border-radius:4px}}
.s-src{{flex:none;margin-left:auto;color:#94a3b8;font-size:11px}}
.s-more{{display:inline-block;font-size:12px;font-weight:700;color:var(--c);text-decoration:none;margin-top:4px}}
.s-more:hover{{text-decoration:underline}}
/* 전체 섹션 */
.cat{{margin-bottom:34px;scroll-margin-top:64px}}
.cat h2{{display:flex;align-items:center;gap:10px;font-size:19px;margin-bottom:14px;
  padding-bottom:8px;border-bottom:2px solid var(--c)}}
.cat h2 .dot{{width:12px;height:12px;border-radius:50%;background:var(--c)}}
.cat h2 .cnt{{font-size:13px;color:var(--mut);font-weight:600}}
.cat h2 .top-link{{margin-left:auto;font-size:12px;color:var(--mut);text-decoration:none;font-weight:600}}
.cat h2 .top-link:hover{{color:var(--c)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}}
.card{{background:var(--card);border:1px solid #e2e8f0;border-radius:12px;padding:16px;border-top:3px solid var(--c);transition:.15s}}
.card:hover{{box-shadow:0 6px 20px rgba(0,0,0,.08);transform:translateY(-2px)}}
.card-top{{display:flex;gap:10px;align-items:flex-start}}
.score{{flex:none;background:var(--c);color:#fff;font-weight:800;font-size:13px;padding:3px 8px;border-radius:6px;min-width:32px;text-align:center}}
.title{{font-weight:700;font-size:15px;color:var(--tx);text-decoration:none}}
a.title:hover{{color:var(--c)}}
.desc{{color:var(--mut);font-size:13px;margin:10px 0}}
.meta{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:12px;color:var(--mut)}}
.src{{font-weight:600;color:#475569}}
.badge{{padding:2px 7px;border-radius:5px;font-size:11px;font-weight:700}}
.corr{{background:#fef3c7;color:#b45309}}
.tier1{{background:#dcfce7;color:#166534}}.tier2{{background:#dbeafe;color:#1e40af}}.tier3{{background:#f1f5f9;color:#64748b}}
.m{{background:#ede9fe;color:#6d28d9;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:700}}
.kws{{margin-top:10px;display:flex;flex-wrap:wrap;gap:5px}}
.kw{{background:#f8fafc;border:1px solid #e2e8f0;color:#64748b;padding:2px 7px;border-radius:10px;font-size:11px}}
footer{{text-align:center;color:var(--mut);font-size:12px;padding:24px}}
</style></head><body id="top">
<header>
  <div class="asof">📅 {meta['asof']} 기준</div>
  <h1>🏢 <span class="em">부동산 뉴스</span> 브리핑</h1>
  <div class="sub">
    <span class="stat">기간 <b>{meta['window']}</b></span>
    <span class="stat">총 <b>{meta['count']}</b>건</span>
    <span class="stat">스코어 <b>{meta['min_score']}</b>점 이상</span>
    <span class="stat">최신기사 <b>{meta['latest']}</b></span>
    <span class="stat">생성 {meta['gen']}</span>
  </div>
</header>
<nav class="nav">{nav}</nav>
<main>
  <div class="summary-h">📋 카테고리별 요약</div>
  <div class="summary">{summ}</div>
  {sections or '<p style="padding:40px;text-align:center;color:#64748b">해당 기간·조건에 기사가 없습니다.</p>'}
</main>
<footer>네이버 뉴스 API + WebSearch/WebFetch + 브라우저 크롤링 통합 수집 · 스코어 = 출처신뢰도+교차출처+최신성+키워드 · SQLite 누적 DB</footer>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int)
    ap.add_argument("--since")
    ap.add_argument("--min-score", type=float, default=0)
    ap.add_argument("--relevant-only", action="store_true", help="검색어가 실제 본문에 있는 기사만")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.since:
        since = args.since
        window = f"{args.since} 이후"
    else:
        days = args.days or 7
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        window = f"최근 {days}일"

    con = D.connect(); D.init(con)
    arts = fetch(con, since, args.min_score, args.relevant_only)
    lp = latest_pubdate(arts)
    now = datetime.now()
    meta = {
        "asof": now.strftime("%Y년 %m월 %d일"),
        "date_kr": now.strftime("%Y-%m-%d"),
        "window": window, "count": len(arts), "min_score": int(args.min_score),
        "latest": lp.astimezone().strftime("%m/%d %H:%M") if lp else "-",
        "gen": now.strftime("%Y-%m-%d %H:%M"),
    }
    html_out = build(arts, meta)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html_out)
    sys.stderr.write(f"OK: {len(arts)}건 → {args.out}\n")
    print(args.out)


if __name__ == "__main__":
    main()

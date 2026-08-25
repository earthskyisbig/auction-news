#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite(news.db)에서 기사를 읽어 부동산 뉴스 브리핑 HTML 리포트 생성.

사용:
  python build_report.py --days 7 --out reports/news_2026-07-14.html
  python build_report.py --since 2026-07-01 --min-score 30 --out reports/report.html

구성: 대형 기준일 헤더 → sticky 카테고리 네비(클릭 시 해당 섹션 이동) →
      카테고리별 요약(톱 헤드라인) → 카테고리별 전체 카드(스코어순) → 🏘 현장 목소리(블로그).

블로그는 tier3 고정이라 뉴스 기준(min-score 45)을 구조적으로 못 넘긴다. 묻어두면 워치리스트
현장글(매물·호가·구역 동향)이 영영 안 보이므로 별도 섹션에 낮은 임계(blog_channel.report_min_score)로
싣고, 중개업소 글은 ⚠광고 배지를 단다(판단 재료로는 쓰되 포지션이 걸린 글임을 표시).
디자인: 지식베이스 표준(다크 네비 #1e293b, 화이트 콘텐츠, 카테고리 색상코딩).
"""
import argparse, html, json, os, re, sys
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


BLOG_COLOR = "#a16207"

# blog_channel 기본값 — --sources 미지정 시 사용
BLOG_DEFAULT = {"report_min_score": 25, "ad_markers": []}


def esc(s):
    return html.escape(s or "")


def load_blog_channel(path):
    if not path or not os.path.isfile(path):
        return dict(BLOG_DEFAULT)
    try:
        cfg = json.load(open(path, encoding="utf-8")).get("blog_channel") or {}
    except Exception as e:
        sys.stderr.write(f"WARN: blog_channel 로드 실패({e}) → 기본값\n")
        return dict(BLOG_DEFAULT)
    out = dict(BLOG_DEFAULT); out.update({k: cfg[k] for k in out if k in cfg})
    return out


def ad_matcher(markers):
    """블로거명이 중개업소·분양대행으로 보이면 True. 컴파일 실패한 패턴은 건너뛴다."""
    pats = []
    for m in markers:
        try:
            pats.append(re.compile(m))
        except re.error as e:
            sys.stderr.write(f"WARN: ad_marker 무시 '{m}' ({e})\n")
    return lambda src: any(p.search(src or "") for p in pats)


def fetch(con, since_iso, min_score, relevant_only=False):
    q = "SELECT * FROM articles WHERE (pub_date>=? OR pub_date='') AND score>=?"
    if relevant_only:
        q += " AND relevance=1"
    q += " ORDER BY score DESC, pub_date DESC"
    rows = con.execute(q, (since_iso, min_score)).fetchall()
    return [dict(r) for r in rows]


def fetch_blog(con, since_iso, min_score, exclude_ids):
    """블로그(검색)·RSS(신뢰 블로거) 단독 수집분. 뉴스와 병합된 것·뉴스 섹션에 이미 실린 것은 제외."""
    q = ("SELECT * FROM articles WHERE (pub_date>=? OR pub_date='') AND score>=? AND relevance=1 "
         "AND (methods LIKE '%\"blog\"%' OR methods LIKE '%\"rss\"%') AND methods NOT LIKE '%\"api\"%' "
         # 신뢰 블로거(RSS 구독분)와 워치리스트 현장글은 점수가 낮아도 상한(--blog-top)에 잘리면 안 된다
         "ORDER BY (raw LIKE '%\"trusted\": true%') DESC, (category='watch') DESC, score DESC, pub_date DESC")
    rows = con.execute(q, (since_iso, min_score)).fetchall()
    return [dict(r) for r in rows if r["id"] not in exclude_ids]


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


def _raw(a):
    try:
        return json.loads(a["raw"] or "{}")
    except Exception:
        return {}


def is_trusted(a):
    return bool(_raw(a).get("trusted"))


def is_official(a):
    """기관 보도자료 원문 — 언론 보도가 아니라 1차 출처다."""
    return bool(_raw(a).get("official"))


def card(a, is_ad=False):
    methods = json.loads(a["methods"] or "[]")
    kws = json.loads(a["keywords_matched"] or "[]")
    badge = ""
    if a["corroboration"] and a["corroboration"] >= 2:
        badge = f'<span class="badge corr">교차출처 {a["corroboration"]}</span>'
    tier_b = f'<span class="badge tier{a["source_tier"]}">T{a["source_tier"]}</span>'
    if is_official(a):
        badge += '<span class="badge official" title="기관 보도자료 원문(1차 출처)">🏛공식</span>'
    elif is_trusted(a):
        # 직접 등록한 구독 필자다. 상호에 전화번호가 들어가도 광고로 깎지 않는다.
        badge += '<span class="badge trust" title="config/blogs.json에 등록한 신뢰 블로거">⭐신뢰</span>'
    elif is_ad:
        badge += '<span class="badge ad" title="중개업소·분양대행 블로그 — 포지션이 걸린 글">⚠광고</span>'
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


def build(articles, meta, blogs=None, is_ad=lambda s: False):
    by_cat = {}
    for a in articles:
        by_cat.setdefault(a["category"], []).append(a)
    present = [(c, l, col) for c, l, col in CATS if by_cat.get(c)]

    blogs = blogs or []

    # sticky 네비 버튼 (클릭 시 해당 섹션으로 이동)
    nav = "".join(
        f'<a class="navbtn" href="#cat-{c}" style="--c:{col}"><span class="nb-n">{len(by_cat.get(c, []))}</span>{esc(l)}</a>'
        for c, l, col in present)
    if blogs:
        nav += (f'<a class="navbtn" href="#blog" style="--c:{BLOG_COLOR}">'
                f'<span class="nb-n">{len(blogs)}</span>🏘 현장 목소리</a>')

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

    if blogs:
        tr_n = sum(1 for b in blogs if is_trusted(b))
        ad_n = sum(1 for b in blogs if not is_trusted(b) and is_ad(b["source"]))
        trunc_note = (f'<br><b>표시 {len(blogs)}건 / 조건 충족 {meta["blog_total"]}건</b> — 스코어 상위만 실었다.'
                      if meta["blog_total"] > len(blogs) else "")
        blog_cards = "".join(card(b, is_ad(b["source"])) for b in blogs)
        sections += f"""
      <section id="blog" class="cat blog" style="--c:{BLOG_COLOR}">
        <h2><span class="dot"></span>🏘 현장 목소리 <span class="cnt">{len(blogs)}건</span>
          <a class="top-link" href="#top">↑ 맨 위로</a></h2>
        <p class="blog-note">블로그 단독 수집분. 언론이 다루지 않는 <b>매물·호가·구역 동향·사업성 분석</b>이 주 가치다.
          <b>{tr_n}건</b>은 직접 등록한 구독 필자(<span class="badge trust">⭐신뢰</span>)이고 나머지는 검색으로 걸린 글이다.
          <b>{ad_n}건</b>은 중개업소·분양대행 글(<span class="badge ad">⚠광고</span>). 어느 쪽이든 검증되지 않은 개인 견해다.
          뉴스보다 낮은 스코어 기준({meta['blog_min_score']}점)으로 실었으니 교차확인 후 판단할 것.
          {trunc_note}</p>
        <div class="grid">{blog_cards}</div>
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
.ad{{background:#fee2e2;color:#b91c1c}}
.trust{{background:#dcfce7;color:#15803d}}
.official{{background:#e0e7ff;color:#3730a3}}
.blog-note{{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:11px 14px;
  font-size:12.5px;color:#78350f;margin-bottom:14px;line-height:1.6}}
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
    <span class="stat">현장 목소리 <b>{meta['blog_count']}</b>건</span>
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
    ap.add_argument("--sources", help="sources.json — blog_channel(현장 목소리 임계·광고 판정) 적용")
    ap.add_argument("--blog-min-score", type=float, help="현장 목소리 섹션 임계(미지정 시 blog_channel.report_min_score)")
    ap.add_argument("--no-blog-section", action="store_true", help="현장 목소리(블로그) 섹션 생략")
    ap.add_argument("--blog-top", type=int, default=80, help="현장 목소리 최대 표시 건수(0=전체)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.since:
        since = args.since
        window = f"{args.since} 이후"
    else:
        days = args.days or 7
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        window = f"최근 {days}일"

    ch = load_blog_channel(args.sources)
    blog_min = args.blog_min_score if args.blog_min_score is not None else ch["report_min_score"]

    con = D.connect(); D.init(con)
    arts = fetch(con, since, args.min_score, args.relevant_only)
    blogs = [] if args.no_blog_section else fetch_blog(con, since, blog_min, {a["id"] for a in arts})
    blog_total = len(blogs)
    if args.blog_top and blog_total > args.blog_top:
        blogs = blogs[:args.blog_top]
    lp = latest_pubdate(arts + blogs)
    now = datetime.now()
    meta = {
        "asof": now.strftime("%Y년 %m월 %d일"),
        "date_kr": now.strftime("%Y-%m-%d"),
        "window": window, "count": len(arts), "min_score": int(args.min_score),
        "blog_min_score": int(blog_min), "blog_count": len(blogs), "blog_total": blog_total,
        "latest": lp.astimezone().strftime("%m/%d %H:%M") if lp else "-",
        "gen": now.strftime("%Y-%m-%d %H:%M"),
    }
    html_out = build(arts, meta, blogs, ad_matcher(ch["ad_markers"]))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html_out)
    sys.stderr.write(f"OK: 뉴스 {len(arts)}건 + 현장 목소리 {len(blogs)}/{blog_total}건 → {args.out}\n")
    print(args.out)


if __name__ == "__main__":
    main()

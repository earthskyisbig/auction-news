#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""신뢰 블로거 RSS 구독 수집기 (stdlib 전용, API 키 불필요).

네이버 블로그 *검색*(naver_blog_search.py)은 키워드에 걸린 글만 가져온다. 좋은 필자의 글도
검색어와 표현이 어긋나면 영영 안 들어온다. 이 수집기는 반대로 간다 — config/blogs.json에
등록한 블로거의 RSS를 통째로 받아 최신 글을 전부 적재한다.

  https://rss.blog.naver.com/{id}.xml  → item: title, link, description, category, tag, pubDate

카테고리 분류는 **제목+태그+RSS자체분류**만 본다(본문 1,200자를 넣으면 '아파트 분양' 같은
조합이 아무 글에나 걸린다). keywords.json 키워드 적중 1점 + 아래 CAT_TOKENS 단일어 적중 2점으로
합산해 최고점 카테고리를 고른다. keywords.json은 '재건축 안전진단'처럼 구(句) 위주라
'재건축'만 있는 블로그 제목을 못 잡기 때문에 단일어 표를 따로 둔다.

사용:
  python naver_blog_rss.py --blogs config/blogs.json --config config/keywords.json \
    --watchlist config/watchlist.json --out _workspace/rss_raw.json

출력: ingest.py 호환 dict 배열. collection_method="rss", raw.trusted=true.
"""
import argparse, hashlib, html, json, os, re, sys, urllib.error, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

RSS = "https://rss.blog.naver.com/{}.xml"

# 블로그 제목에 흔한 단일어 → 카테고리. keywords.json의 구(句) 매칭이 놓치는 것을 메운다.
CAT_TOKENS = {
    "redevelopment": ["재건축", "재개발", "정비사업", "정비구역", "정비계획", "조합", "신속통합", "모아타운",
                      "추정분담금", "관리처분", "사업시행인가", "조합원", "입주권", "리모델링"],
    "auction": ["경매", "공매", "낙찰", "권리분석", "말소기준", "명도", "유치권", "경락"],
    "subscription": ["청약", "분양권", "특별공급", "청약통장", "무순위", "줍줍", "견본주택"],
    "policy": ["대책", "규제지역", "토지거래허가", "세제", "종부세", "양도세", "취득세", "DSR", "LTV",
               "대출규제", "임대차", "전매제한"],
    "market": ["시황", "매매가", "전세가", "거래량", "시세", "실거래", "매물", "호가", "전세가율", "미분양"],
    "urban_plan": ["도시계획", "지구단위", "그린벨트", "역세권", "공공주택", "도시개발", "택지지구", "개발제한구역"],
    "industrial": ["산업단지", "신도시", "반도체", "클러스터", "국가산단"],
}
TAG_RE = re.compile(r"<[^>]+>")
UA = {"User-Agent": "Mozilla/5.0 (compatible; auction-news/1.0)"}


def clean(t):
    return html.unescape(TAG_RE.sub(" ", t or "")).strip()


def article_id(title, url):
    return hashlib.sha1((clean(title) + "|" + (url or "")).encode("utf-8")).hexdigest()[:16]


def canon_link(url):
    """?fromRss=true&trackingCode=rss 추적 파라미터를 떼어야 검색분과 중복 병합된다."""
    return (url or "").split("?")[0]


def fetch(blog_id, timeout=15):
    try:
        with urllib.request.urlopen(urllib.request.Request(RSS.format(blog_id), headers=UA), timeout=timeout) as r:
            return ET.fromstring(r.read())
    except urllib.error.HTTPError as e:
        sys.stderr.write("WARN: %s HTTP %s\n" % (blog_id, e.code))
    except Exception as e:
        sys.stderr.write("WARN: %s %s\n" % (blog_id, e))
    return None


def pubdate_iso(s):
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat()
    except Exception:
        return ""


def load_keyword_map(config, watchlist):
    """(카테고리, 키워드) 목록. 긴 키워드를 먼저 봐야 '재건축'이 '재건축 초과이익환수'를 가린다."""
    pairs = []
    if config and os.path.isfile(config):
        cats = json.load(open(config, encoding="utf-8"))["categories"]
        for cat, spec in cats.items():
            for kw in spec["keywords"]:
                pairs.append((cat, kw))
    if watchlist and os.path.isfile(watchlist):
        for kw in json.load(open(watchlist, encoding="utf-8")).get("keywords", []):
            pairs.append(("watch", kw))
    return sorted(pairs, key=lambda p: -len(p[1]))


def classify(hay, pairs, fallback):
    """제목+태그+RSS분류에 대한 가중 투표. keywords.json 구 적중 1점, 단일어 적중 2점.
    동점이면 watch(관심 지역)가 이긴다."""
    score, matched = {}, []
    for cat, kw in pairs:
        toks = [t for t in kw.split() if len(t) >= 2]
        if toks and all(t in hay for t in toks):
            score[cat] = score.get(cat, 0) + 1
            matched.append(kw)
    for cat, toks in CAT_TOKENS.items():
        for t in toks:
            if t in hay:
                score[cat] = score.get(cat, 0) + 2
    if not score:
        return fallback, []
    best = max(score.items(), key=lambda kv: (kv[1], kv[0] == "watch"))[0]
    return best, sorted(set(matched))[:6]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blogs", default="config/blogs.json")
    ap.add_argument("--config", help="keywords.json (카테고리 분류용)")
    ap.add_argument("--watchlist", help="watchlist.json (watch 분류용)")
    ap.add_argument("--out")
    ap.add_argument("--limit", type=int, help="피드당 최대 글 수(미지정 시 blogs.json)")
    args = ap.parse_args()

    if not os.path.isfile(args.blogs):
        sys.stderr.write("WARN: %s 없음 → RSS 채널 건너뜀\n" % args.blogs)
        return
    cfg = json.load(open(args.blogs, encoding="utf-8"))
    if not cfg.get("enabled", True):
        sys.stderr.write("INFO: blogs.json enabled=false → RSS 채널 건너뜀\n")
        return

    tier = int(cfg.get("tier", 2))
    limit = args.limit or int(cfg.get("per_feed_limit", 30))
    max_age = int(cfg.get("max_age_days", 30))
    fallback = cfg.get("fallback_category", "local")
    skip_pats = [re.compile(p) for p in cfg.get("skip_category_patterns", [])]
    skip_titles = [re.compile(p) for p in cfg.get("skip_title_patterns", [])]
    pairs = load_keyword_map(args.config, args.watchlist)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age)

    results, seen = [], set()
    stat = {"skip_cat": 0, "skip_title": 0, "aged": 0, "dead": 0}
    for feed in cfg.get("feeds", []):
        bid = feed["id"]
        root = fetch(bid)
        if root is None:
            stat["dead"] += 1
            continue
        ch = root.find("channel")
        blog_name = feed.get("name") or (ch.findtext("title") if ch is not None else bid) or bid
        taken = 0
        for it in (ch.findall("item") if ch is not None else []):
            if taken >= limit:
                break
            rss_cat = (it.findtext("category") or "").strip()
            if any(p.search(rss_cat) for p in skip_pats):
                stat["skip_cat"] += 1
                continue
            pub = pubdate_iso(it.findtext("pubDate") or "")
            if pub and datetime.fromisoformat(pub) < cutoff:
                stat["aged"] += 1
                continue
            title = clean(it.findtext("title"))
            if any(p.search(title) for p in skip_titles):
                stat["skip_title"] += 1
                continue
            desc = clean(it.findtext("description"))[:1200]
            tags = clean(it.findtext("tag"))
            url = canon_link(it.findtext("link") or it.findtext("guid"))
            if not title or not url:
                continue
            aid = article_id(title, url)
            if aid in seen:
                continue
            seen.add(aid)
            cat, matched = classify(" ".join([title, tags, rss_cat]), pairs, fallback)
            results.append({
                "id": aid, "title": title, "description": desc, "url": url, "naver_url": "",
                "source": blog_name, "pub_date": pub, "category": cat,
                "keywords_matched": matched, "collection_method": "rss",
                # trusted → ingest가 tier를 고정하고 relevance 필터를 면제한다(구독 콘텐츠)
                "source_tier_hint": tier,
                "raw": {"trusted": True, "blog_id": bid, "rss_category": rss_cat,
                        "note": feed.get("note", ""), "domain": "blog.naver.com"},
            })
            taken += 1

    silent = [f["id"] for f in cfg.get("feeds", []) if not any(r["raw"]["blog_id"] == f["id"] for r in results)]
    sys.stderr.write("INFO: 피드 %d개 / 제외 — 카테고리 %d, 제목 %d, %d일 초과 %d, 응답없음 %d\n"
                     % (len(cfg.get("feeds", [])), stat["skip_cat"], stat["skip_title"], max_age, stat["aged"], stat["dead"]))
    if silent:
        # 조용히 0건이 되면 휴면 블로그인지 필터가 과한지 알 수 없다 → 반드시 이름을 찍는다
        sys.stderr.write("WARN: 수집 0건 피드 %d개 → %s\n" % (len(silent), ", ".join(silent)))

    payload = json.dumps(results, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        open(args.out, "w", encoding="utf-8").write(payload)
        sys.stderr.write("OK: RSS %d건 → %s\n" % (len(results), args.out))
    else:
        print(payload)


if __name__ == "__main__":
    main()

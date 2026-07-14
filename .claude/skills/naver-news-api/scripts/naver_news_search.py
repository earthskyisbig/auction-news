#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""네이버 뉴스 검색 오픈 API 수집기 (stdlib 전용, 외부 의존 없음).

인증: 환경변수 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET (.env 자동 로드).
사용:
  python naver_news_search.py --config ../../../config/keywords.json --out _workspace/api_raw.json
  python naver_news_search.py --query "부동산 대책" --category policy --display 100

출력: 정규화된 기사 dict 배열(JSON). curator의 ingest.py가 그대로 받는다.
필드: id,title,description,url,naver_url,source,pub_date,category,keywords_matched,collection_method,raw
"""
import argparse, hashlib, html, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

API = "https://openapi.naver.com/v1/search/news.json"
TAG_RE = re.compile(r"<[^>]+>")


def load_env():
    """프로젝트 루트의 .env를 찾아 환경변수로 로드(이미 설정된 값은 유지)."""
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        env = os.path.join(here, ".env")
        if os.path.isfile(env):
            with open(env, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return
        here = os.path.dirname(here)


def clean(text):
    return html.unescape(TAG_RE.sub("", text or "")).strip()


def domain_of(url):
    try:
        return urllib.parse.urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def norm_pubdate(s):
    # 네이버 pubDate: 'Mon, 14 Jul 2026 09:30:00 +0900'
    for fmt in ("%a, %d %b %Y %H:%M:%S %z",):
        try:
            return datetime.strptime(s, fmt).astimezone(timezone.utc).isoformat()
        except Exception:
            pass
    return s or ""


def article_id(title, url):
    key = (clean(title) + "|" + (url or "")).encode("utf-8")
    return hashlib.sha1(key).hexdigest()[:16]


def search(query, display=100, sort="date"):
    cid = os.environ.get("NAVER_CLIENT_ID")
    sec = os.environ.get("NAVER_CLIENT_SECRET")
    if not cid or not sec:
        sys.stderr.write("ERROR: NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 미설정 (.env 확인)\n")
        sys.exit(2)
    params = urllib.parse.urlencode({"query": query, "display": display, "sort": sort})
    req = urllib.request.Request(API + "?" + params, headers={
        "X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec,
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8")).get("items", [])
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"WARN: '{query}' HTTP {e.code} {e.reason}\n")
        return []
    except Exception as e:
        sys.stderr.write(f"WARN: '{query}' {e}\n")
        return []


def normalize(item, category, query):
    url = item.get("originallink") or item.get("link") or ""
    title = clean(item.get("title", ""))
    return {
        "id": article_id(title, url),
        "title": title,
        "description": clean(item.get("description", "")),
        "url": url,
        "naver_url": item.get("link", ""),
        "source": domain_of(url),
        "pub_date": norm_pubdate(item.get("pubDate", "")),
        "category": category,
        "keywords_matched": [query],
        "collection_method": "api",
        "raw": item,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="keywords.json 경로")
    ap.add_argument("--watchlist", help="watchlist.json 경로 (keywords를 category=watch로 추가 수집)")
    ap.add_argument("--query")
    ap.add_argument("--category", default="uncategorized")
    ap.add_argument("--display", type=int, default=100)
    ap.add_argument("--sort", default="date", choices=["date", "sim"])
    ap.add_argument("--out", help="결과 저장 경로(미지정 시 stdout)")
    args = ap.parse_args()

    load_env()
    queries = []  # (category, query)
    if args.config:
        cfg = json.load(open(args.config, encoding="utf-8"))
        for cat, spec in cfg["categories"].items():
            for kw in spec["keywords"]:
                queries.append((cat, kw))
    if args.watchlist and os.path.isfile(args.watchlist):
        wl = json.load(open(args.watchlist, encoding="utf-8"))
        for kw in wl.get("keywords", []):
            queries.append(("watch", kw))
    if not queries and args.query:
        queries.append((args.category, args.query))
    if not queries:
        ap.error("--config, --watchlist, --query 중 하나는 필요")

    seen, results = set(), []
    for cat, q in queries:
        for it in search(q, args.display, args.sort):
            a = normalize(it, cat, q)
            if a["id"] in seen:
                continue
            seen.add(a["id"])
            results.append(a)
        time.sleep(0.12)  # rate-limit 여유

    payload = json.dumps(results, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        sys.stderr.write(f"OK: {len(results)}건 → {args.out}\n")
    else:
        print(payload)


if __name__ == "__main__":
    main()

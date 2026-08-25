#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""네이버 블로그 검색 오픈 API 수집기 (stdlib 전용).

참조: https://developers.naver.com/docs/serviceapi/search/blog/blog.md
뉴스 API와 인증·구조 동일. 응답 item: title, link, description, bloggername, bloggerlink, postdate(YYYYMMDD).
블로그는 현장 후기·호가·분위기 보강용. 뉴스와 겹치는 제도 요약 재탕글이 노이즈의 대부분이라
sources.json의 blog_channel로 수집 카테고리를 좁히고(기본 local·redevelopment + watch),
최신순(sort=date)·게시일 상한(max_age_days)으로 과거 글 유입을 막는다.

사용:
  python naver_blog_search.py --config ../../../config/keywords.json --sources ../../../config/sources.json --out _workspace/blog_raw.json
  python naver_blog_search.py --query "3기 신도시" --category industrial --display 20

출력: curator ingest.py 호환 dict 배열. collection_method="blog".
"""
import argparse, hashlib, html, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

API = "https://openapi.naver.com/v1/search/blog.json"
TAG_RE = re.compile(r"<[^>]+>")
KST = timezone(timedelta(hours=9))


def load_env():
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        env = os.path.join(here, ".env")
        if os.path.isfile(env):
            for line in open(env, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return
        here = os.path.dirname(here)


def clean(t):
    return html.unescape(TAG_RE.sub("", t or "")).strip()


def domain_of(url):
    try:
        return urllib.parse.urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def norm_postdate(s):
    # 'YYYYMMDD' → ISO(KST 00:00)
    if s and len(s) == 8 and s.isdigit():
        try:
            return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), tzinfo=KST).astimezone(timezone.utc).isoformat()
        except Exception:
            return ""
    return ""


def load_blog_channel(path):
    """sources.json의 blog_channel 설정. 파일·키가 없으면 기존 동작(전 카테고리·sim)."""
    default = {"categories": None, "always_watch": True, "sort": None, "max_age_days": 0}
    if not path or not os.path.isfile(path):
        return default
    try:
        cfg = json.load(open(path, encoding="utf-8")).get("blog_channel") or {}
    except Exception as e:
        sys.stderr.write(f"WARN: blog_channel 로드 실패({e}) → 기본값\n")
        return default
    default.update({k: cfg[k] for k in default if k in cfg})
    return default


def too_old(pub_iso, max_age_days):
    """게시일이 상한을 넘으면 True. 날짜 미상은 통과시킨다(버리면 손실이 더 크다)."""
    if not max_age_days or not pub_iso:
        return False
    try:
        dt = datetime.fromisoformat(pub_iso)
    except Exception:
        return False
    return (datetime.now(timezone.utc) - dt).days > max_age_days


def article_id(title, url):
    return hashlib.sha1((clean(title) + "|" + (url or "")).encode("utf-8")).hexdigest()[:16]


def search(query, display, sort):
    cid, sec = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if not cid or not sec:
        sys.stderr.write("ERROR: NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 미설정 (.env)\n")
        sys.exit(2)
    params = urllib.parse.urlencode({"query": query, "display": display, "sort": sort})
    req = urllib.request.Request(API + "?" + params, headers={
        "X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8")).get("items", [])
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"WARN: '{query}' HTTP {e.code} {e.reason}\n"); return []
    except Exception as e:
        sys.stderr.write(f"WARN: '{query}' {e}\n"); return []


def normalize(item, category, query):
    url = item.get("link", "")
    title = clean(item.get("title", ""))
    blogger = clean(item.get("bloggername", ""))
    return {
        "id": article_id(title, url),
        "title": title,
        "description": clean(item.get("description", "")),
        "url": url,
        "naver_url": "",
        "source": blogger or domain_of(url),   # 블로거명 우선(없으면 도메인)
        "pub_date": norm_postdate(item.get("postdate", "")),
        "category": category,
        "keywords_matched": [query],
        "collection_method": "blog",
        "raw": {"bloggerlink": item.get("bloggerlink", ""), "domain": domain_of(url)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--watchlist", help="watchlist.json (keywords를 category=watch로 추가)")
    ap.add_argument("--query")
    ap.add_argument("--category", default="uncategorized")
    ap.add_argument("--display", type=int, default=20)
    ap.add_argument("--sources", help="sources.json — blog_channel(카테고리 제한·정렬·게시일 상한) 적용")
    ap.add_argument("--sort", choices=["sim", "date"], help="미지정 시 blog_channel.sort → sim")
    ap.add_argument("--all-categories", action="store_true", help="blog_channel의 카테고리 제한을 무시하고 전부 수집")
    ap.add_argument("--out")
    args = ap.parse_args()

    load_env()
    ch = load_blog_channel(args.sources)
    allow = None if args.all_categories else ch["categories"]
    sort = args.sort or ch["sort"] or "sim"

    queries, skipped = [], []
    if args.config:
        cfg = json.load(open(args.config, encoding="utf-8"))
        for cat, spec in cfg["categories"].items():
            if allow is not None and cat not in allow:
                skipped.append(cat)
                continue
            for kw in spec["keywords"]:
                queries.append((cat, kw))
    if skipped:
        sys.stderr.write(f"INFO: 블로그 제외 카테고리 {len(skipped)}개 → {', '.join(skipped)}\n")
    if args.watchlist and os.path.isfile(args.watchlist):
        if allow is None or ch["always_watch"] or "watch" in (allow or []):
            wl = json.load(open(args.watchlist, encoding="utf-8"))
            for kw in wl.get("keywords", []):
                queries.append(("watch", kw))
    if not queries and args.query:
        queries.append((args.category, args.query))
    if not queries:
        ap.error("--config, --watchlist, --query 필요")

    seen, results, aged = set(), [], 0
    for cat, q in queries:
        for it in search(q, args.display, sort):
            a = normalize(it, cat, q)
            if a["id"] in seen:
                continue
            if too_old(a["pub_date"], ch["max_age_days"]):
                aged += 1
                continue
            seen.add(a["id"]); results.append(a)
        time.sleep(0.12)
    if aged:
        sys.stderr.write(f"INFO: 게시일 {ch['max_age_days']}일 초과로 제외 {aged}건\n")

    payload = json.dumps(results, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        open(args.out, "w", encoding="utf-8").write(payload)
        sys.stderr.write(f"OK: 블로그 {len(results)}건 → {args.out}\n")
    else:
        print(payload)


if __name__ == "__main__":
    main()

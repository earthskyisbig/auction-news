#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""기관 보도자료·정비사업 전문지 수집기 (stdlib 전용, API 키·브라우저 불필요).

브라우저 크롤(news-crawl)은 GitHub Actions에서 못 돈다. 이 수집기는 순수 HTTP로 같은 원문을
가져와 정기 자동화에 태울 수 있게 한 것이다. 대상은 config/press.json.

  rss    표준 RSS            서울시 보도자료 · 하우징워치 · 하우징헤럴드
  molit  국토부 게시판 HTML   307 리다이렉트로 쿠키를 심은 뒤에야 목록이 나온다(CookieJar 필수)
  fsc    금융위 게시판 HTML   행에 날짜가 없어 첨부파일명 앞 YYMMDD에서 추정

정부·지자체 보도자료는 철도·보험·축제까지 전 분야라 topic_filter로 부동산 건만 남긴다.
정비사업 전문지는 전량이 주제 안이므로 filter=false.

사용:
  python press_feeds.py --press config/press.json --config config/keywords.json --out _workspace/press_raw.json

출력: ingest.py 호환 dict 배열. collection_method="press", raw.official=true.
"""
import argparse, hashlib, html, http.cookiejar, json, os, re, ssl, sys
import urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "news-curation", "scripts"))
import classify as C

TAG_RE = re.compile(r"<[^>]+>")
KST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
# 일부 기관 사이트는 중간 인증서 체인이 불완전하다. 공개 보도자료라 위험이 없다.
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def clean(t):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", t or ""))).strip()


def article_id(title, url):
    return hashlib.sha1((clean(title) + "|" + (url or "")).encode("utf-8")).hexdigest()[:16]


def opener():
    """쿠키를 유지하는 오프너. 국토부는 첫 요청이 307로 쿠키를 심고 되돌아온다."""
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        urllib.request.HTTPSHandler(context=CTX))
    op.addheaders = [("User-Agent", UA),
                     ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
                     ("Accept-Language", "ko-KR,ko;q=0.9")]
    return op


def get(url, retries=2):
    op = opener()
    for i in range(retries + 1):
        try:
            with op.open(url, timeout=20) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if i == retries:
                sys.stderr.write("WARN: %s HTTP %s\n" % (url[:60], e.code))
        except Exception as e:
            if i == retries:
                sys.stderr.write("WARN: %s %s\n" % (url[:60], e))
    return ""


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat() if dt else ""


DC_DATE = "{http://purl.org/dc/elements/1.1/}date"


def any_date(raw):
    """RSS 날짜는 표준을 안 지킨다. 서울시·전문지 모두 RFC822가 아니라 'YYYY-MM-DD HH:MM:SS'다.
    날짜를 못 읽으면 최신성 점수가 죽고 기간 필터도 통과해버리므로 형식을 넓게 받는다."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return iso(parsedate_to_datetime(raw))
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return iso(datetime.strptime(raw, fmt).replace(tzinfo=KST))
        except ValueError:
            continue
    return ""


def parse_rss(src):
    body = get(src["url"])
    if not body:
        return []
    try:
        ch = ET.fromstring(body.encode("utf-8")).find("channel")
    except ET.ParseError as e:
        sys.stderr.write("WARN: %s RSS 파싱 실패 %s\n" % (src["id"], e))
        return []
    out = []
    for it in (ch.findall("item") if ch is not None else []):
        pub = any_date(it.findtext("pubDate")) or any_date(it.findtext(DC_DATE))
        # 서울시 피드는 본문을 description이 아니라 <cn>에 담는다
        desc = it.findtext("description") or it.findtext("cn") or ""
        out.append({"title": clean(it.findtext("title")),
                    "url": (it.findtext("link") or "").strip(),
                    "desc": clean(desc)[:1000],
                    "pub": pub})
    return out


def paged(src, param):
    """게시판은 한 페이지에 10건뿐이다. 하루치를 놓치지 않으려면 몇 장 더 넘겨야 한다."""
    n = int(src.get("pages", 1))
    urls = [src["url"]]
    for i in range(2, n + 1):
        sep = "&" if "?" in src["url"] else "?"
        urls.append("%s%s%s=%d" % (src["url"], sep, param, i))
    return urls


def parse_molit(src):
    """<tr>에 번호·제목·분야·등록일이 들어있다. 분야는 카테고리 판단의 추가 단서로 쓴다."""
    body = "".join(get(u) for u in paged(src, "lcmspage"))
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
        a = re.search(r'href="(dtl\.jsp[^"]*)"[^>]*>(.*?)</a>', tr, re.S)
        if not a:
            continue
        date = re.search(r'class="bd_date">\s*(\d{4}-\d{2}-\d{2})', tr)
        field = re.search(r'class="bd_field">\s*([^<]*)', tr)
        href = urllib.parse.urljoin(src["url"], html.unescape(a.group(1)))
        out.append({"title": clean(a.group(2)), "url": href,
                    "desc": clean(field.group(1)) if field else "",
                    "pub": iso(datetime.strptime(date.group(1), "%Y-%m-%d").replace(tzinfo=KST)) if date else ""})
    return out


def parse_fsc(src):
    """행에 날짜가 없다 → 첨부파일명 앞 YYMMDD로 추정한다. 없으면 날짜 미상으로 둔다."""
    body = "".join(get(u) for u in paged(src, "curPage"))
    out = []
    for li in re.split(r"<li>", body):
        a = re.search(r'class="subject"\s*>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>', li, re.S)
        if not a:
            continue
        pub = ""
        d = re.search(r"(\d{4}[-.]\d{2}[-.]\d{2})", li) or re.search(r'name">(\d{6})\(', li)
        if d:
            raw = d.group(1)
            fmt = "%Y-%m-%d" if len(raw) == 10 else "%y%m%d"
            try:
                pub = iso(datetime.strptime(raw.replace(".", "-"), fmt).replace(tzinfo=KST))
            except ValueError:
                pub = ""
        dept = re.search(r"담당부서\s*:\s*([^<]*)", li)
        out.append({"title": clean(a.group(2)),
                    "url": urllib.parse.urljoin(src["url"], html.unescape(a.group(1))),
                    "desc": clean(dept.group(1)) if dept else "", "pub": pub})
    return out


def parse_incheon(src):
    """인천시 보도자료. <li> 블록에 /IC010205/view 링크·subject·요약·YYYY-MM-DD가 함께 있다."""
    body = "".join(get(u) for u in paged(src, "curPage"))
    out = []
    for li in re.split(r"<li>", body):
        m = re.search(r'href="(/IC010205/view[^"]+)".*?class="subject">([^<]+)</strong>(.*?)$', li, re.S)
        if not m:
            continue
        tail = TAG_RE.sub(" ", m.group(3))
        d = re.search(r"(\d{4}-\d{2}-\d{2})", tail)
        pub = ""
        if d:
            try:
                pub = iso(datetime.strptime(d.group(1), "%Y-%m-%d").replace(tzinfo=KST))
            except ValueError:
                pub = ""
        out.append({"title": clean(m.group(2)),
                    "url": urllib.parse.urljoin(src["url"], html.unescape(m.group(1))),
                    "desc": clean(tail)[:400], "pub": pub})
    return out


PARSERS = {"rss": parse_rss, "molit": parse_molit, "fsc": parse_fsc, "incheon": parse_incheon}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--press", default="config/press.json")
    ap.add_argument("--config", help="keywords.json (카테고리 분류용)")
    ap.add_argument("--watchlist", help="watchlist.json (watch 분류용)")
    ap.add_argument("--only", help="이 id의 소스만 수집(디버그)")
    ap.add_argument("--out")
    args = ap.parse_args()

    if not os.path.isfile(args.press):
        sys.stderr.write("WARN: %s 없음 → 보도자료 채널 건너뜀\n" % args.press)
        return
    cfg = json.load(open(args.press, encoding="utf-8"))
    if not cfg.get("enabled", True):
        sys.stderr.write("INFO: press.json enabled=false → 건너뜀\n")
        return

    pairs = C.load_keyword_map(args.config, args.watchlist)
    topic = cfg.get("topic_filter", [])
    limit = int(cfg.get("per_source_limit", 40))
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(cfg.get("max_age_days", 21)))

    results, seen, report = [], set(), []
    for src in cfg.get("sources", []):
        if args.only and src["id"] != args.only:
            continue
        parser = PARSERS.get(src.get("type"))
        if not parser:
            sys.stderr.write("WARN: %s 알 수 없는 type=%s\n" % (src["id"], src.get("type")))
            continue
        items = parser(src)
        kept = off = aged = 0
        for it in items:
            if kept >= limit:
                break
            if not it["title"] or not it["url"]:
                continue
            if it["pub"] and datetime.fromisoformat(it["pub"]) < cutoff:
                aged += 1
                continue
            hay = it["title"] + " " + it["desc"]
            if src.get("filter") and not C.is_on_topic(hay, topic):
                off += 1
                continue
            aid = article_id(it["title"], it["url"])
            if aid in seen:
                continue
            seen.add(aid)
            cat, matched = C.classify(hay, pairs, src.get("fallback_category", "policy"))
            results.append({
                "id": aid, "title": it["title"], "description": it["desc"], "url": it["url"],
                "naver_url": "", "source": src["name"], "pub_date": it["pub"], "category": cat,
                "keywords_matched": matched, "collection_method": "press",
                "source_tier_hint": int(src.get("tier", 2)),
                # official → ingest가 티어를 고정하고 relevance 필터를 면제한다(원문은 검색 노이즈가 아니다)
                "raw": {"trusted": True, "official": True, "press_id": src["id"],
                        "domain": urllib.parse.urlparse(it["url"]).netloc.replace("www.", "")},
            })
            kept += 1
        report.append("%s %d건(수신 %d·주제밖 %d·기간밖 %d)" % (src["id"], kept, len(items), off, aged))
        if not kept:
            sys.stderr.write("WARN: %s 수집 0건 — 사이트 구조 변경 여부 확인 필요\n" % src["id"])

    sys.stderr.write("INFO: " + " | ".join(report) + "\n")
    payload = json.dumps(results, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        open(args.out, "w", encoding="utf-8").write(payload)
        sys.stderr.write("OK: 보도자료 %d건 → %s\n" % (len(results), args.out))
    else:
        print(payload)


if __name__ == "__main__":
    main()

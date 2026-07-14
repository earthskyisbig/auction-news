#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""수집 원천(JSON 배열)들을 받아 중복제거·분류보정·스코어링 후 SQLite에 upsert.

사용:
  python ingest.py --inputs _workspace/api_raw.json _workspace/web_raw.json _workspace/crawl_raw.json \
                   --sources ../../../config/sources.json --run-id 2026-07-14T09

입력 기사 dict 최소 필드: title,url. 나머지(description,source,pub_date,category,
keywords_matched,collection_method,raw)는 있으면 사용, 없으면 보완.

중복 판정:
  1) canonical URL 동일 → 동일 스토리
  2) 정규화 제목 유사도 >= 0.86 (difflib) → 동일 스토리(교차출처로 병합)
병합 시 corroboration+1, methods 합집합, 상위 tier source 유지.

스코어(0~100):
  tier(최대40) + 교차출처(최대25) + 최신성(최대20) + 키워드매칭수(최대15)
"""
import argparse, difflib, json, re, sys, urllib.parse
from datetime import datetime, timezone
import db as D


def load_sources(path):
    if not path:
        return {}, []
    s = json.load(open(path, encoding="utf-8"))
    tier = {}
    for t, doms in s.get("source_tiers", {}).items():
        n = int(t.replace("tier", ""))
        for d in doms:
            tier[d] = n
    return tier, s.get("preferred_domains", [])


def load_watch(path):
    if not path or not __import__("os").path.isfile(path):
        return []
    return json.load(open(path, encoding="utf-8")).get("properties", [])


def compute_relevance(rec):
    """검색어(keywords_matched)의 핵심 토큰이 제목/본문에 실제 존재하면 1, 아니면 0.
    네이버 검색의 fuzzy 매칭 노이즈를 걸러낸다."""
    hay = (rec.get("title", "") + " " + rec.get("description", "")).lower()
    for kw in rec.get("keywords_matched", []):
        toks = [t for t in re.split(r"\s+", kw.lower()) if len(t) >= 2]
        if toks and all(t in hay for t in toks):
            return 1
        # 단일 토큰 키워드는 부분일치 허용
        if len(toks) == 1 and toks[0] in hay:
            return 1
    return 0


def match_watch(rec, properties):
    """관심물건 region 용어가 제목/본문에 걸리면 매칭 목록 반환."""
    hay = rec.get("title", "") + " " + rec.get("description", "")
    hits = []
    for p in properties:
        for term in p.get("region", []):
            if term and term in hay:
                hits.append({"id": p["id"], "name": p["name"], "term": term})
                break
    return hits


def source_tier(domain, tier_map):
    if not domain:
        return 3
    for d, n in tier_map.items():
        if d in domain:
            return n
    return 3


def canon_url(url):
    if not url:
        return ""
    try:
        p = urllib.parse.urlparse(url)
        return (p.netloc.replace("www.", "") + p.path).rstrip("/").lower()
    except Exception:
        return url.lower()


def norm_title(t):
    return re.sub(r"[^0-9a-z가-힣]", "", (t or "").lower())


def recency_points(pub_date):
    if not pub_date:
        return 5
    try:
        dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return 5
    if days <= 1:
        return 20
    if days <= 3:
        return 15
    if days <= 7:
        return 10
    if days <= 30:
        return 5
    return 2


def score(rec):
    tier_pts = {1: 40, 2: 28, 3: 16}.get(rec["source_tier"], 16)
    corrob = min(rec["corroboration"], 5) * 5          # 최대 25
    rec_pts = recency_points(rec["pub_date"])          # 최대 20
    kw = min(len(rec["keywords_matched"]), 5) * 3      # 최대 15
    return round(tier_pts + corrob + rec_pts + kw, 1)


def merge_group(items, tier_map):
    """동일 스토리로 묶인 items(list of dict)를 1개 레코드로 병합."""
    items = sorted(items, key=lambda a: source_tier(a.get("source", ""), tier_map))
    base = items[0]
    methods, kws = set(), set()
    for it in items:
        m = it.get("collection_method")
        if m:
            methods.add(m)
        for k in (it.get("keywords_matched") or []):
            kws.add(k)
    dom = base.get("source", "")
    return {
        "id": base.get("id") or D and __import__("hashlib").sha1((base["title"] + base.get("url", "")).encode()).hexdigest()[:16],
        "title": base["title"],
        "description": base.get("description", ""),
        "url": base.get("url", ""),
        "naver_url": base.get("naver_url", ""),
        "source": dom,
        "source_tier": source_tier(dom, tier_map),
        "pub_date": base.get("pub_date", ""),
        "category": base.get("category", "uncategorized"),
        "keywords_matched": sorted(kws),
        "methods": sorted(methods) or ["api"],
        "corroboration": len({canon_url(i.get("url", "")) or norm_title(i["title"]) for i in items}),
        "raw": base.get("raw", {}),
    }


def group_articles(articles):
    """canonical URL + 제목 유사도로 스토리 그룹핑."""
    groups, by_url = [], {}
    remaining = []
    for a in articles:
        cu = canon_url(a.get("url", ""))
        if cu and cu in by_url:
            by_url[cu].append(a)
        elif cu:
            by_url[cu] = [a]
            groups.append(by_url[cu])
        else:
            remaining.append(a)
    # 제목 유사도로 그룹 간 병합 (URL이 다른 교차출처 대응).
    # 대용량 대비: 정규화 제목 접두어(4자)로 버킷팅 후 버킷 내에서만 difflib 비교 → O(n²) 회피.
    final = []
    buckets = {}  # prefix -> [final_index, ...]
    for g in groups + [[r] for r in remaining]:
        nt = norm_title(g[0]["title"])
        key = nt[:4]
        merged = False
        for i in buckets.get(key, []):
            rt = final[i]["_nt"]
            if abs(len(nt) - len(rt)) <= 8 and difflib.SequenceMatcher(None, nt, rt).ratio() >= 0.86:
                final[i]["items"].extend(g)
                merged = True
                break
        if not merged:
            idx = len(final)
            final.append({"_nt": nt, "items": list(g)})
            buckets.setdefault(key, []).append(idx)
    return [f["items"] for f in final]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--sources")
    ap.add_argument("--watchlist", help="config/watchlist.json (관심물건 매칭)")
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()

    tier_map, _ = load_sources(args.sources)
    properties = load_watch(args.watchlist)
    incoming = []
    for path in args.inputs:
        try:
            data = json.load(open(path, encoding="utf-8"))
            incoming.extend(data if isinstance(data, list) else data.get("articles", []))
        except FileNotFoundError:
            sys.stderr.write(f"WARN: 입력 없음(건너뜀): {path}\n")
    sys.stderr.write(f"입력 기사 총 {len(incoming)}건\n")

    groups = group_articles(incoming)
    con = D.connect()
    D.init(con)
    now = datetime.now(timezone.utc).isoformat()
    new_c = merged_c = 0
    watch_c = 0
    for g in groups:
        rec = merge_group(g, tier_map)
        rec["score"] = score(rec)
        rel = compute_relevance(rec)
        hits = match_watch(rec, properties)
        if hits:
            watch_c += 1
        row = con.execute("SELECT id,corroboration,methods,keywords_matched,first_seen FROM articles WHERE id=?",
                          (rec["id"],)).fetchone()
        if row:  # 이미 있던 스토리 → 교차/키워드 갱신
            methods = sorted(set(json.loads(row["methods"] or "[]")) | set(rec["methods"]))
            kws = sorted(set(json.loads(row["keywords_matched"] or "[]")) | set(rec["keywords_matched"]))
            corrob = max(row["corroboration"], rec["corroboration"])
            rec["methods"], rec["keywords_matched"], rec["corroboration"] = methods, kws, corrob
            rec["score"] = score(rec)
            con.execute("""UPDATE articles SET methods=?,keywords_matched=?,corroboration=?,score=?,
                           relevance=?,watch_hits=?,last_seen=? WHERE id=?""",
                        (json.dumps(methods, ensure_ascii=False), json.dumps(kws, ensure_ascii=False),
                         corrob, rec["score"], rel, json.dumps(hits, ensure_ascii=False), now, rec["id"]))
            merged_c += 1
        else:
            con.execute("""INSERT INTO articles
                (id,title,description,url,naver_url,source,source_tier,pub_date,category,
                 keywords_matched,methods,corroboration,score,relevance,watch_hits,first_seen,last_seen,raw)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rec["id"], rec["title"], rec["description"], rec["url"], rec["naver_url"],
                 rec["source"], rec["source_tier"], rec["pub_date"], rec["category"],
                 json.dumps(rec["keywords_matched"], ensure_ascii=False),
                 json.dumps(rec["methods"], ensure_ascii=False), rec["corroboration"], rec["score"],
                 rel, json.dumps(hits, ensure_ascii=False),
                 now, now, json.dumps(rec["raw"], ensure_ascii=False)))
            new_c += 1
        # 관심물건 매칭 → 알림 큐 등록(관련도 있는 기사만, 중복 무시)
        if rel:
            for h in hits:
                con.execute("INSERT OR IGNORE INTO alerts (property_id,property_name,article_id,matched_term,created_at) "
                            "VALUES (?,?,?,?,?)", (h["id"], h["name"], rec["id"], h["term"], now))
    total = con.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
    con.execute("""INSERT OR REPLACE INTO collection_runs
        (run_id,started_at,finished_at,new_count,merged_count,total_after,notes)
        VALUES (?,?,?,?,?,?,?)""",
        (args.run_id, now, now, new_c, merged_c, total, f"inputs={len(args.inputs)}"))
    con.commit()
    sys.stderr.write(f"OK: 신규 {new_c} / 병합갱신 {merged_c} / 누적 {total} / 관심물건매칭 {watch_c}\n")
    print(json.dumps({"new": new_c, "merged": merged_c, "total": total, "watch_hits": watch_c, "run_id": args.run_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()

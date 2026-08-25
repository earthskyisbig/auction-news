#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""지역 온디맨드 뉴스 수집 — 경매물건·분석대상 지역이 정해진 시점에 그 자리에서 긁는다.

워치리스트(config/watchlist.json)는 '미리 등록한 지역'만 수집한다. 그런데 경매 물건은
뜬 뒤에야 지역이 정해지므로 사전등록 전제가 성립하지 않는다. 이 스크립트는 지역 인자를
받아 2단계 검색으로 그 지역의 개발호재를 즉석 수집·적재한다.

  [1차] 주소에서 바로 만들 수 있는 확정 검색어 (시군구·읍면동·단지명)
  [추출] 1차 결과 본문에서 고유명사 역추출 (○○지구 / ○○구역 / ○○선 / ○○신도시)
  [2차] 도출된 지구명·사업명으로 재검색   ← 여기서 진짜 호재가 잡힌다
  [적재] ingest.py로 news.db 병합 (run_id = od-{지역}-{날짜})
  [요약] 확정/계획/검토중 3단계 분류 + 동명이지 오탐 제외후보 보고

사용:
  python scripts/region_news.py --sigungu 시흥시 --dong 은행동 --complex 은계브리즈힐
  python scripts/region_news.py --sigungu 시흥시 --dong 은행동 --dry-run

무의존(Python stdlib만) — 프로젝트 규약을 따른다.
"""
import argparse, collections, json, os, re, subprocess, sys, time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAVER_DIR = os.path.join(ROOT, ".claude", "skills", "naver-news-api", "scripts")
INGEST = os.path.join(ROOT, ".claude", "skills", "news-curation", "scripts", "ingest.py")
KST = timezone(timedelta(hours=9))

sys.path.insert(0, NAVER_DIR)
import naver_news_search as nns  # noqa: E402  (load_env / search / normalize 재사용)

# ── 고유명사 역추출 패턴 ────────────────────────────────────────────────
# 주소만으로는 '은계지구'·'수도권 서남부 광역철도' 같은 이름을 만들 수 없다.
# 1차 검색 결과 본문에서 뽑아낸다.
EXTRACT_PATTERNS = [
    re.compile(r"[가-힣A-Za-z0-9]{2,8}(?:공공주택|택지개발|도시개발|재정비촉진)?지구"),
    re.compile(r"[가-힣A-Za-z0-9]{2,8}구역"),
    re.compile(r"[가-힣]{2,8}\s?(?:\d기\s?)?신도시"),
    re.compile(r"[가-힣A-Za-z0-9\s]{2,12}광역철도"),
    re.compile(r"GTX-[A-F]"),
    re.compile(r"[가-힣A-Za-z0-9]{2,9}선"),
]

# '○○선' 패턴이 잡아버리는 흔한 일반명사. 정규식으로는 거를 수 없어 명시 제외한다.
LINE_STOPWORDS = {
    "우선", "노선", "개선", "최우선", "이번선", "무선", "유선", "간선", "지선",
    "일직선", "직선", "곡선", "전선", "혼선", "복선", "단선", "차선", "시선",
    "본선", "관심선", "경계선", "기준선", "동일선", "생명선", "가이드라인선",
}
GENERIC_STOPWORDS = {"해당지구", "이번지구", "본구역", "해당구역", "일부구역", "전체구역"}

# '○○구역'이지만 고유 사업명이 아닌 규제·용도 구역. 2차 검색에 넣으면 전국 기사가 쏟아진다.
ZONE_STOPWORDS = {
    "개발제한구역", "보호구역", "통제보호구역", "제한보호구역", "군사시설보호구역",
    "상수원보호구역", "문화재보호구역", "어린이보호구역", "노인보호구역",
    "조정대상지역", "투기과열지구", "토지거래허가구역", "규제지역", "용도지역",
    "정비구역", "사업구역", "해제구역", "지정구역", "공사구역", "관리지역",
    "업무지구", "상업지구", "주거지구", "역세권지구", "계획지구", "개발지구",
}

# 개발호재 관련성 판정 — 요약에 넣을 기사를 거른다(소상공인 지원·선거구 획정 등 제외)
TOPIC_KEYWORDS = [
    "개발", "철도", "노선", "역세권", "신도시", "지구", "정비사업", "재개발", "재건축",
    "착공", "고시", "분양", "입주", "공급", "택지", "도시계획", "교통", "GTX", "광역",
    "보상", "지구단위", "산업단지", "업무지구", "역 신설", "연장", "예타", "타당성",
]

# 호재 확정성 3단계 (강의안 p17: 발표와 확정은 다르고, 확정과 개통은 또 다르다)
STAGE_RULES = [
    ("확정", ["고시", "착공", "승인", "인가", "실시계획", "예산 반영", "개통", "보상 착수",
              "보상 접수", "지정 완료", "의결", "확정"]),
    ("계획", ["계획", "발표", "추진", "예정", "목표", "제안", "용역", "검토 착수", "구상"]),
    ("검토중", ["검토", "건의", "요구", "촉구", "기대", "전망", "논의", "가능성", "관측"]),
]

# 동명이지 판별용 상위 행정구역 마커
OTHER_REGION_MARKERS = [
    "서울", "인천", "부산", "대구", "대전", "광주", "울산", "세종",
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
]


def sigungu_core(sigungu):
    """'시흥시' → '시흥'. 접미사를 떼어 오탐 판별의 기준으로 쓴다."""
    return re.sub(r"(특별자치시|광역시|특별시|자치시|자치구|시|군|구)$", "", sigungu)


def build_primary_queries(a):
    """주소에서 곧바로 만들 수 있는 확정 검색어. 행정단위 접미사를 반드시 붙인다.

    '시흥'으로 검색하면 서울 금천구 시흥동 기사가 대량으로 섞인다(2026-08-08 실증).
    """
    qs = []
    if a.dong:
        qs.append(f"{a.sigungu} {a.dong}")
    qs.append(f"{a.sigungu} 개발계획")
    qs.append(f"{a.sigungu} 입주물량")
    if a.complex_name:
        qs.append(a.complex_name)
    for d in a.district or []:
        qs.append(d)
    for e in a.extra or []:
        qs.append(e)
    # 순서 유지 중복제거
    return list(dict.fromkeys(qs))


def extract_candidates(articles, exclude, sigungu, core, dong):
    """1차 결과에서 지구명·사업명 후보를 빈도순으로 뽑는다.

    핵심 가드: 후보가 등장한 기사에 대상 지역명이 함께 있어야 채택한다(동시출현 조건).
    이게 없으면 '고덕국제화계획지구'(평택) 같은 타 지역 사업명이 2차 검색어로 올라가
    전혀 무관한 기사를 대량으로 끌어온다.
    """
    counter = collections.Counter()
    for art in articles:
        text = f"{art.get('title','')} {art.get('description','')}"
        near = bool(dong and dong in text)
        if not (near or sigungu in text or core in text):
            continue
        # 읍면동까지 함께 언급된 기사의 후보에 가중치를 준다. 시군구 전역 검색은
        # 같은 시의 다른 지구(배곧·검단 등)를 대량으로 물고 오는데, 대상 단지의
        # 생활권 호재와는 무관하다. 근접 가중치로 순위를 갈라낸다.
        weight = 3 if near else 1
        rail_ctx = any(k in text for k in ("철도", "전철", "노선", "역 신설", "복선", "개통", "지하철"))
        for pat in EXTRACT_PATTERNS:
            for m in pat.findall(text):
                cand = re.sub(r"\s+", " ", m).strip()
                if len(cand) < 3 or cand in GENERIC_STOPWORDS or cand in ZONE_STOPWORDS:
                    continue
                if cand.endswith("구역") and any(z in cand for z in ("보호", "제한", "허가")):
                    continue
                if cand.endswith("지구") and any(z in cand for z in ("우선해제", "해제", "미지정")):
                    continue
                if cand.endswith("선"):
                    if cand in LINE_STOPWORDS or len(cand) < 4:
                        continue  # '서해선'(3)은 통과, '우선'류는 제외
                    if any(cand.endswith(s) for s in ("개선", "선정", "우선", "노선")):
                        continue  # '규제개선'류 — 철도 노선명이 아니다
                    if not rail_ctx:
                        continue  # 철도 맥락이 없는 기사의 '○○선'은 신뢰하지 않는다
                if any(x and x in cand for x in exclude):
                    continue
                # 패턴이 앞 어절을 삼킨 경우('개소하며 신도시') — 어미로 판별해 버린다
                head = re.sub(r"(지구|구역|신도시|광역철도|선)$", "", cand).strip()
                if re.search(r"(하며|하고|되며|이며|에서|으로|한다|했다|되는|하는)$", head):
                    continue
                counter[cand] += weight
    return dedupe_truncations(counter)


def dedupe_truncations(counter):
    """정규식 길이 상한 때문에 생기는 절단 아티팩트를 제거한다.

    '평택고덕국제화계획지구'가 상한(8자+접미사)에 걸려 '택고덕국제화계획지구'로 잘린다.
    더 짧고 더 빈번한 후보를 포함하는 긴 후보는 잘린 조각으로 보고 버린다.
    """
    out = collections.Counter(counter)
    for long_c in list(out):
        for short_c in list(out):
            if long_c == short_c or len(short_c) >= len(long_c):
                continue
            if short_c in long_c and out[short_c] >= out[long_c]:
                del out[long_c]
                break
    return out


def is_on_topic(art):
    """개발호재와 무관한 생활행정 기사(소상공인 지원·선거구 획정 등)를 요약에서 뺀다."""
    text = f"{art.get('title','')} {art.get('description','')}"
    return any(k in text for k in TOPIC_KEYWORDS)


def classify_stage(text):
    for stage, kws in STAGE_RULES:
        if any(k in text for k in kws):
            return stage
    return "미분류"


def is_offtarget(art, sigungu, core, dong):
    """동명이지 오탐 판정. 조용히 버리지 않고 '제외후보'로 표시만 한다."""
    text = f"{art.get('title','')} {art.get('description','')}"
    if sigungu in text:
        return False, ""
    if dong and dong in text:
        return False, ""
    if core not in text:
        return False, ""
    hits = [m for m in OTHER_REGION_MARKERS if m in text and m != core]
    if hits:
        return True, f"'{core}'만 등장 + 타 지역 마커({', '.join(hits[:3])})"
    return False, ""


def collect(queries, category, display, sort):
    seen, out = set(), []
    for q in queries:
        for it in nns.search(q, display, sort):
            art = nns.normalize(it, category, q)
            if art["id"] in seen:
                continue
            seen.add(art["id"])
            out.append(art)
        time.sleep(0.12)
    return out


def warn_db_divergence():
    """data/news.db는 로컬 .gitignore 대상이지만 GitHub Actions는 강제 커밋한다.
    로컬 파일과 원격 커밋본이 조용히 갈라지므로 실행 전에 경고한다."""
    try:
        blob = subprocess.run(["git", "rev-parse", "origin/main:data/news.db"],
                              cwd=ROOT, capture_output=True, text=True, timeout=10)
        if blob.returncode != 0:
            return
        size = subprocess.run(["git", "cat-file", "-s", blob.stdout.strip()],
                              cwd=ROOT, capture_output=True, text=True, timeout=10)
        remote = int(size.stdout.strip())
        local_path = os.path.join(ROOT, "data", "news.db")
        local = os.path.getsize(local_path) if os.path.isfile(local_path) else 0
        if remote > local * 1.2:
            print(f"⚠️  원격 DB({remote:,}B)가 로컬({local:,}B)보다 큽니다. 정본은 원격입니다.")
            print("    git pull --rebase && git cat-file -p origin/main:data/news.db > data/news.db")
            print()
    except Exception:
        pass  # 경고는 부가기능 — 실패해도 수집은 계속한다


def main():
    ap = argparse.ArgumentParser(description="지역 온디맨드 뉴스 수집 (2단계 검색)")
    ap.add_argument("--sigungu", required=True, help="시군구 (예: 시흥시) — 접미사 포함 필수")
    ap.add_argument("--dong", help="읍면동 (예: 은행동)")
    ap.add_argument("--complex", dest="complex_name", help="단지명 (예: 은계브리즈힐)")
    ap.add_argument("--district", action="append", help="택지지구·정비구역명 (반복 가능)")
    ap.add_argument("--extra", action="append", help="추가 검색어 (반복 가능)")
    ap.add_argument("--top", type=int, default=8, help="2차 검색어로 채택할 후보 수 (기본 8)")
    ap.add_argument("--display", type=int, default=100)
    ap.add_argument("--sort", default="date", choices=["date", "sim"])
    ap.add_argument("--dry-run", action="store_true", help="검색어만 확인하고 수집·적재는 하지 않음")
    ap.add_argument("--no-ingest", action="store_true", help="수집만 하고 DB 적재는 건너뜀")
    args = ap.parse_args()

    nns.load_env()
    core = sigungu_core(args.sigungu)
    slug = f"{args.sigungu}-{args.dong}" if args.dong else args.sigungu
    today = datetime.now(KST).strftime("%Y%m%d")
    run_id = f"od-{slug}-{today}"

    warn_db_divergence()

    q1 = build_primary_queries(args)
    print(f"[1차 검색어] {len(q1)}개")
    for q in q1:
        print(f"  · {q}")

    if not (os.environ.get("NAVER_CLIENT_ID") and os.environ.get("NAVER_CLIENT_SECRET")):
        print("\n⚠️  NAVER 키 없음 → API 수집 건너뜀. WebSearch로 보완이 필요합니다.")
        return 0

    if args.dry_run:
        print("\n(--dry-run: 1차 수집을 실제로 돌려야 2차 검색어가 나옵니다.")
        print(" 후보 추출까지 보려면 --dry-run 없이 --no-ingest로 실행하세요.)")
        return 0

    # ── 1차 수집 ──────────────────────────────────────────────────────
    a1 = collect(q1, "local", args.display, args.sort)
    print(f"\n[1차 수집] {len(a1)}건")

    if not a1:
        # 0건은 "호재 없음"이 아니라 "DB에 근거 없음"이다. 절대 혼동하지 말 것.
        print("\n❌ 1차 0건 — 2차 검색을 건너뜁니다.")
        print("   → 이는 '개발호재 없음'이 아니라 'DB에 근거 없음'입니다. 감점 근거로 쓰지 마세요.")
        print("   → WebSearch로 반드시 교차검증하세요.")
        return 0

    # ── 후보 역추출 ───────────────────────────────────────────────────
    exclude = {args.sigungu, core, args.dong or "", args.complex_name or ""}
    cands = extract_candidates(a1, exclude, args.sigungu, core, args.dong)
    picked = [c for c, _ in cands.most_common(args.top)]
    print(f"\n[역추출 후보] 상위 {len(picked)}개 (전체 {len(cands)}종)")
    for c in picked:
        print(f"  · {c} ({cands[c]}회)")
    if len(cands) > len(picked):
        dropped = len(cands) - len(picked)
        print(f"  … 빈도 하위 {dropped}종은 --top {args.top} 기준으로 제외했습니다.")

    # ── 2차 수집 ──────────────────────────────────────────────────────
    q2 = [c for c in picked if c not in q1]
    a2 = collect(q2, "local", args.display, args.sort) if q2 else []
    print(f"\n[2차 수집] 검색어 {len(q2)}개 → {len(a2)}건")

    # ── 병합 · 오탐 판정 ──────────────────────────────────────────────
    merged, seen = [], set()
    for art in a1 + a2:
        if art["id"] in seen:
            continue
        seen.add(art["id"])
        merged.append(art)

    keep, offtarget = [], []
    for art in merged:
        bad, why = is_offtarget(art, args.sigungu, core, args.dong)
        (offtarget if bad else keep).append((art, why))

    print(f"\n[오탐 가드] 유지 {len(keep)}건 / 제외후보 {len(offtarget)}건")
    for art, why in offtarget[:5]:
        print(f"  ✗ {art['title'][:50]} — {why}")
    if len(offtarget) > 5:
        print(f"  … 외 {len(offtarget)-5}건")

    # ── 저장 · 적재 ───────────────────────────────────────────────────
    os.makedirs(os.path.join(ROOT, "_workspace"), exist_ok=True)
    raw_path = os.path.join(ROOT, "_workspace", f"region_raw_{slug}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump([a for a, _ in keep], f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {raw_path}")

    if not args.no_ingest:
        cmd = [sys.executable, INGEST, "--inputs", raw_path,
               "--sources", os.path.join(ROOT, "config", "sources.json"),
               "--run-id", run_id]
        r = subprocess.run(cmd, cwd=ROOT)
        if r.returncode != 0:
            print(f"\n⚠️  적재 실패. raw는 보존됩니다. 수동 재적재:\n   {' '.join(cmd)}")
        else:
            print(f"[적재] run_id={run_id}")

    # ── 확정성 3단계 요약 (개발호재 관련 기사만) ──────────────────────
    on_topic = [a for a, _ in keep if is_on_topic(a)]
    off_topic = len(keep) - len(on_topic)
    buckets = collections.defaultdict(list)
    for art in on_topic:
        buckets[classify_stage(f"{art['title']} {art['description']}")].append(art)

    print("\n" + "=" * 60)
    print(f"## {args.sigungu} {args.dong or ''} 개발호재 — 확정성 3단계")
    print(f"   (호재 관련 {len(on_topic)}건 / 무관 {off_topic}건 제외)")
    print("=" * 60)
    for stage in ["확정", "계획", "검토중", "미분류"]:
        arts = buckets.get(stage, [])
        print(f"\n### {stage} ({len(arts)}건)")
        for art in arts[:6]:
            print(f"  - [{art['pub_date'][:10]}] {art['title'][:60]}")
            print(f"    {art['url']}")
        if len(arts) > 6:
            print(f"  … 외 {len(arts)-6}건")

    print("\n※ '확정'만 높은 점수를 준다. 발표와 확정은 다르고, 확정과 개통은 또 다르다.")
    print("※ 이 결과는 auction-news 단독 근거다. 반드시 WebSearch로 교차검증하라.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

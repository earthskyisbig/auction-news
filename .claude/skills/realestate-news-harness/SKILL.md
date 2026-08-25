---
name: realestate-news-harness
description: 부동산 뉴스를 네이버 오픈 API·WebSearch/WebFetch·브라우저 크롤링으로 복합 수집해 중복제거·스코어링·DB 적재 후 HTML 브리핑을 만드는 오케스트레이터. "부동산 뉴스 수집", "뉴스 브리핑 만들어줘", "오늘/이번주 부동산 뉴스", "뉴스 하네스 실행", "뉴스 리포트", 그리고 후속으로 "다시 수집", "재실행", "업데이트", "리포트만 다시", "특정 카테고리만", "이전 결과 기반"을 언급하면 반드시 이 스킬을 사용할 것. 단순 단일 기사 질의는 직접 응답 가능.
---

# realestate-news-harness — 부동산 뉴스 수집 오케스트레이터

3채널 복합 수집(API·웹·크롤) → 통합 정제 → HTML 브리핑 파이프라인을 조율한다.

## 실행 모드: 하이브리드
- **Phase 2 (수집)**: 팬아웃 — 3 콜렉터를 병렬 서브 에이전트로 실행(상호 통신 불필요, 결과만 파일로)
- **Phase 3~4 (통합·리포트)**: 파이프라인 — curator → reporter 순차

> 팀 통신 오버헤드가 이득보다 큰 순수 병렬 수집이라 서브 에이전트가 적합하다. 모든 Agent 호출은 `model: "opus"`.

## Phase 0: 컨텍스트 확인
1. `_workspace/` 산출물과 `data/news.db` 존재 여부 확인.
2. 실행 모드 판별:
   - **지역이 지정됨**(경매 물건 주소, 입지분석 대상 단지 등) → **지역 온디맨드 모드** (아래 별도 절)
   - `data/news.db` 없음 → **초기 실행** (전체 Phase)
   - 사용자가 "리포트만 다시" → **리포트 재생성** (Phase 4만)
   - 사용자가 "특정 카테고리만 다시" → **부분 재수집** (해당 카테고리 콜렉터 → curator → reporter)
   - 그 외 정기 실행 → **증분 수집** (기존 `_workspace/*.json`을 `_workspace_prev/`로 이동 후 전체)
3. `NAVER_CLIENT_ID/SECRET` 존재 확인 → 없으면 API 채널 제외하고 사용자에 `.env` 안내.

## 지역 온디맨드 모드 (Phase 1~4 대신 실행)

경매 물건은 **뜬 뒤에야 지역이 정해진다.** 워치리스트는 "미리 등록한 지역"만 수집하므로 이 상황을 커버하지 못한다. 지역이 지정된 요청은 정기 파이프라인 대신 `scripts/region_news.py`를 쓴다.

```bash
python scripts/region_news.py --sigungu 시흥시 --dong 은행동 --complex 은계브리즈힐
# 옵션: --district 은계지구  --extra "제2경인선"  --top 8  --dry-run  --no-ingest
```

**동작**: 주소 기반 1차 검색 → 본문에서 지구명·사업명 **역추출**(○○지구/○○구역/○○선/○○신도시) → 상위 후보로 2차 검색 → `ingest.py` 적재(`run_id = od-{지역}-{날짜}`) → 확정/계획/검토중 3단계 분류 출력.

**왜 2단계인가**: 지구명·사업명은 주소에서 도출할 수 없다. 1차만으로는 `은계지구`를 절대 못 찾는다. 근접 가중치(읍면동 동시출현 기사 ×3)로 같은 시의 다른 지구가 상위를 차지하는 것을 막는다.

**워치리스트와의 역할 구분** — 둘은 대체 관계가 아니다:

| | `config/watchlist.json` | `region_news.py` |
|---|---|---|
| 용도 | **장기 모니터링** — 보유 물건·계속 지켜볼 지역 | **일회성 조사** — 이번에 분석할 지역 |
| 시점 | 매일 자동 수집 + 즉시 알림 | 필요할 때 수동 실행 |
| 전제 | 지역을 미리 안다 | 지역을 몰라도 된다 |

**주의**: `data/news.db`는 로컬 `.gitignore` 대상이지만 GitHub Actions는 강제 커밋한다 → 로컬 파일과 원격 커밋본이 조용히 갈라진다. `region_news.py`가 실행 시 크기를 비교해 경고한다. **정본은 원격이다.**

## Phase 1: 준비
- `config/keywords.json`, `config/sources.json` 로드(사용자가 관심사·기간을 지정하면 반영).
- `run_id = ISO 시각` 생성.
- `data/` DB 초기화: `python .claude/skills/news-curation/scripts/db.py`

## Phase 2: 병렬 수집 (서브 에이전트, run_in_background)
콜렉터를 동시에 스폰한다:
- `news-api-collector` → `_workspace/api_raw.json` (네이버 뉴스 API, config 키워드 일괄)
- 네이버 블로그 → `_workspace/blog_raw.json` (`naver_blog_search.py --config --sources`, 현장 매물·호가·구역 동향, method=blog)
  - **반드시 `--sources config/sources.json`을 넘긴다.** 없으면 `blog_channel` 제한이 풀려 전 카테고리를 긁는다(정책·시장 재탕글이 노이즈의 대부분). 수집 범위·정렬·게시일 상한은 `blog_channel`에서만 조정한다.
- 신뢰 블로거 RSS → `_workspace/rss_raw.json` (`naver_blog_rss.py --blogs config/blogs.json`, 구독 필자 새 글 통째로, method=rss)
  - **API 키가 필요 없다** → 네이버 키가 없는 상황에서도 이 채널은 실행한다.
- 기관 보도자료·전문지 → `_workspace/press_raw.json` (`press_feeds.py`, 국토부·서울시·금융위·하우징워치·하우징헤럴드, method=press)
  - 키·브라우저 없이 도는 원문 채널. 브라우저 크롤(아래)이 실패해도 이건 살아 있다.
- `news-web-researcher` → `_workspace/web_raw.json` (WebSearch/WebFetch 보완)
- `news-crawler` → `_workspace/crawl_raw.json` (브라우저 크롤, 실패 허용)

세 결과 수집을 기다린다. 일부 채널 실패해도 나머지로 진행(누락은 리포트에 명시).

## Phase 3: 통합·적재 (curator)
`news-curator` 스폰 (있는 입력만; 증분 채널도 그 시점까지의 모든 raw를 한 번에 재적재해야 교차병합 정상):
```
python .claude/skills/news-curation/scripts/ingest.py \
  --inputs _workspace/api_raw.json _workspace/blog_raw.json _workspace/web_raw.json _workspace/crawl_raw.json \
  --sources config/sources.json --run-id {run_id}
```
`{new, merged, total}` 통계 확보.

## Phase 4: 리포트 (reporter)
`news-reporter` 스폰:
```
python .claude/skills/news-report/scripts/build_report.py \
  --days {수집주기} --min-score {정기20~30|아카이브0} \
  --sources config/sources.json \
  --out reports/news_{YYYY-MM-DD}.html
```
경로와 카테고리별 톱 기사 하이라이트를 사용자에 보고.

**🏘 현장 목소리 섹션**: 블로그는 tier3 고정(16점)이라 뉴스 임계(45점)를 구조적으로 못 넘긴다. 그대로 두면 워치리스트 현장글이 리포트에 영영 안 나오므로, 블로그 단독 수집분만 별도 섹션에 낮은 임계(`blog_channel.report_min_score`, 기본 25)로 싣는다. `watch` 카테고리를 최상단에 세우고(점수가 낮아 표시 상한에 잘리는 것을 막음), 중개업소·분양대행 블로그는 `⚠광고` 배지를 단다(버리지 않음 — 정보는 있되 포지션이 걸린 글). 표시 상한은 `--blog-top`(기본 80)이며 잘린 건수는 리포트에 명시된다. 아카이브 리포트는 전수 보존이 목적이라 `--no-blog-section`.

## 데이터 전달 프로토콜
- **파일 기반**: `_workspace/{api,web,crawl}_raw.json` → curator → `data/news.db` → reporter
- **반환값 기반**: 각 서브 에이전트 결과 통계를 리더가 수집
- 중간 산출물(`_workspace/`)은 보존(감사·부분 재실행용), 최종 리포트만 `reports/`

## 에러 핸들링
- 채널 실패: 1회 재시도 → 재실패 시 해당 채널 없이 진행, 리포트에 "○○ 수집 실패" 명시.
- 상충 데이터: 삭제하지 않고 curator가 교차출처로 병합(출처 병기).
- API 키 없음: API 채널 제외, 사용자에 발급/`.env` 안내 후 웹+크롤로 진행.

## Phase 5: 텔레그램 발송 (선택)
`config/telegram.json`이 활성이고 텔레그램 키가 있으면, 리포트 후 `news-notifier`가 다이제스트를 발송한다.
- 즉시 발송: `python .claude/skills/news-telegram/scripts/send_digest.py`
- 아침 자동발송·명령어 설정: `telegram_bot.py` 상주(백그라운드). `/time`으로 시각, `/on /off`로 구독 카테고리 제어.

## 정기 자동화 (cron 연동)
정기 실행은 오케스트레이터 없이 스크립트 파이프라인만으로도 돌 수 있다(에이전트는 웹서치/크롤 품질 보강용). 최소 자동화:
```bash
python .claude/skills/naver-news-api/scripts/naver_news_search.py --config config/keywords.json --out _workspace/api_raw.json
python .claude/skills/news-curation/scripts/ingest.py --inputs _workspace/api_raw.json --sources config/sources.json --run-id $(date +%Y-%m-%dT%H)
python .claude/skills/news-report/scripts/build_report.py --days 1 --min-score 20 --out reports/news_$(date +%Y-%m-%d).html
```
전체 3채널 자동화는 `/schedule` 또는 `/loop`로 이 스킬을 정기 트리거한다.

## 테스트 시나리오
- **정상 흐름**: 초기 실행 → 3채널 수집 → 병합(교차출처 corroboration≥2 존재) → 리포트에 6카테고리 칩+카드 렌더 → 스코어순 정렬 확인.
- **에러 흐름(크롤 실패)**: 브라우저 미가용 → crawl_raw.json 없음 → curator가 api+web만 적재 → 리포트 생성 성공 + "크롤 미실행" 보고.
- **후속(리포트만)**: DB 존재 + "리포트만 다시" → 수집 건너뛰고 build_report.py만 → 재생성.

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
   - `data/news.db` 없음 → **초기 실행** (전체 Phase)
   - 사용자가 "리포트만 다시" → **리포트 재생성** (Phase 4만)
   - 사용자가 "특정 카테고리만 다시" → **부분 재수집** (해당 카테고리 콜렉터 → curator → reporter)
   - 그 외 정기 실행 → **증분 수집** (기존 `_workspace/*.json`을 `_workspace_prev/`로 이동 후 전체)
3. `NAVER_CLIENT_ID/SECRET` 존재 확인 → 없으면 API 채널 제외하고 사용자에 `.env` 안내.

## Phase 1: 준비
- `config/keywords.json`, `config/sources.json` 로드(사용자가 관심사·기간을 지정하면 반영).
- `run_id = ISO 시각` 생성.
- `data/` DB 초기화: `python .claude/skills/news-curation/scripts/db.py`

## Phase 2: 병렬 수집 (서브 에이전트, run_in_background)
콜렉터를 동시에 스폰한다:
- `news-api-collector` → `_workspace/api_raw.json` (네이버 뉴스 API, config 키워드 일괄)
- 네이버 블로그 → `_workspace/blog_raw.json` (`naver_blog_search.py --config`, 현장·후기·호재 보강, method=blog)
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
  --out reports/news_{YYYY-MM-DD}.html
```
경로와 카테고리별 톱 기사 하이라이트를 사용자에 보고.

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

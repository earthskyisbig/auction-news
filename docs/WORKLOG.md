# 부동산 뉴스 수집 하네스 — 구축 워크로그

> AI 에이전트 하네스로 "부동산 뉴스 자동 수집·정제·리포트·알림" 시스템을 처음부터 만든 과정 기록.
> 강의 자료용 — 특히 **중간에 부딪힌 문제와 해결 과정**이 핵심 교보재.
> 작성일: 2026-07-14 · 대상 저장소: github.com/earthskyisbig/auction-news

---

## 1. 무엇을 만들었나 (한 줄)

네이버 오픈 API(뉴스+블로그) · WebSearch/WebFetch · 브라우저 크롤링으로 부동산 뉴스를 **복합 수집** →
중복제거·교차출처 병합·관련도 필터·중요도 스코어링 → **SQLite 누적 DB** →
**HTML 브리핑 리포트** + **텔레그램 아침 발송** + **관심물건 뉴스 즉시 알림**.

## 2. 핵심 설계 철학 (하네스)

- **에이전트(누가)와 스킬(어떻게)을 분리**한다. 에이전트는 `.claude/agents/*.md`, 실행 절차는 `.claude/skills/*/SKILL.md`.
- **무의존(stdlib) 우선**: Python 표준 라이브러리만으로 API 호출·DB·텔레그램까지. 설치 마찰 0, Windows에서 안정.
- **설정은 파일로, 코드는 고정**: 관심사·소스·구독·워치리스트는 `config/*.json`만 고쳐 바꾼다.
- **채널 실패는 비치명적**: 한 수집 채널이 죽어도 나머지로 성립, 리포트에 누락 명시.
- **진화하는 시스템**: 매 피드백마다 에이전트·스킬·설정을 갱신하고 CLAUDE.md 변경이력에 기록.

## 3. 최종 아키텍처

```
config/           keywords.json  sources.json  telegram.json  watchlist.json
  │
  ▼  (수집 3.5채널)
├ naver-news-api   ─ naver_news_search.py   → _workspace/api_raw.json
├ naver-blog       ─ naver_blog_search.py   → _workspace/blog_raw.json
├ news-web-research─ WebSearch/WebFetch      → _workspace/web_raw.json
└ news-crawl       ─ 브라우저(claude-in-chrome)→ _workspace/crawl_raw.json
  │
  ▼  (통합·정제)
news-curation/ingest.py
  · 중복제거(canonical URL + 제목 유사도 0.86, 접두어 버킷팅)
  · 교차출처 병합(corroboration) · 신뢰도 티어 · 관련도(relevance) · 관심물건 매칭(watch_hits)
  · 스코어 = 티어(40) + 교차출처(25) + 최신성(20) + 키워드(15)
  → data/news.db (SQLite: articles / collection_runs / alerts)
  │
  ├─▶ news-report/build_report.py  → reports/*.html (브리핑·아카이브)
  └─▶ news-telegram/
        · send_digest.py     아침 다이제스트(카테고리별 톱N)
        · watch_alert.py     관심물건 매칭 즉시 알림(별도)
        · telegram_bot.py    명령봇(/time /on /off /now /watchlist …)
```

- **에이전트 6**: news-api-collector · news-web-researcher · news-crawler · news-curator · news-reporter · news-notifier
- **스킬 8**: realestate-news-harness(오케스트레이터) + 위 7개 실행 스킬
- **8 카테고리**: 관심(watch) · 정책·규제·세제 · 시장·시세 · 경매·공매 · 재개발·재건축 · 분양·청약 · 도시계획·공공주택 · 산업단지·신도시

## 4. 구축 타임라인 (기능별)

### 4-1. 초기 3채널 하네스 골격
- 도메인 분석 → 팬아웃(수집) + 파이프라인(통합·리포트) 하이브리드 설계.
- 에이전트 5 + 스킬 6 + 스크립트 4 생성, 테스트 데이터로 파이프라인 무의존 검증.

### 4-2. 실제 수집
- 네이버 뉴스 API로 6카테고리 일괄 수집 → **3,117건**.

### 4-3. 크롤 채널
- 브라우저 확장으로 국토부 보도자료(tier1) 등 게시판형 원문 확보.
- 크롤분과 API분이 제목 유사도로 **교차 병합**(예: LH 광명시흥) 확인.

### 4-4. 8카테고리 개편 + 리포트 UX
- 분양·청약을 재개발에서 분리, **지역단지·호재** 신설(경매 호재 판단용).
- 리포트: 대형 기준일 헤더 + **sticky 카테고리 네비(클릭 이동)** + **카테고리별 요약** 섹션.

### 4-5. 텔레그램 발송 + 명령봇
- send_digest(발송)·telegram_bot(명령)·watch_alert(알림) 3스크립트, 전부 stdlib.
- 명령어로 발송시각·구독 카테고리 제어(/time, /on, /off, /now …).

### 4-6. 블로그 채널 + 성능 최적화
- 네이버 블로그 검색 API 추가(현장·후기·호재 보강), method=blog로 구분.
- 대용량 병합 성능 개선(아래 5-3).

### 4-7. 워치리스트 (관심 키워드·관련도·관심물건 알림)
- `watchlist.json`: 관심 지역·정비구역·정책 키워드(watch 카테고리) + 담당 물건(properties).
- **관련도 필터**: 검색어 핵심 토큰이 제목/본문에 실제 있는지(relevance) → 네이버 fuzzy 노이즈 제거.
- **관심물건 매칭 알림**: properties.region이 뉴스에 걸리면 아침 다이제스트와 **별개로 즉시** 텔레그램 알림.

### 4-8. 스케줄링
- Windows 작업 스케줄러에 아침 07:00 발송 작업 등록(로컬 키·DB 사용).
- 클라우드 루틴은 로컬 .env·DB 접근 불가라 이 하네스엔 부적합으로 판단.

## 5. 부딪힌 문제와 해결 ★ (강의 하이라이트)

### 5-1. 네이버 API 401 (errorCode 024)
- **증상**: 키를 넣었는데 "인증 실패".
- **원인**: 키 값 오타 또는 해당 앱에 **"검색" API 미등록**. (공백·개행은 정상이었음 → repr로 확인)
- **교훈**: 401은 "키가 틀림"이 아니라 "이 키로 이 API를 쓸 권한 없음"일 수 있다. 응답 본문의 errorCode를 꼭 본다.

### 5-2. 텔레그램 409 Conflict — 진단의 정석 ★★
- **증상**: 봇이 계속 `HTTP 409 Conflict`. 재시작해도 반복.
- **가설 소거 과정**:
  1. 웹훅? → `getWebhookInfo` url='' (아님)
  2. 로컬 중복 프로세스? → 전체 프로세스 스캔, 1개뿐 (아님)
  3. 외부 폴러? → 단일 스크립트 3연속 getUpdates는 성공, **20초 롱폴만 409** 재현
  4. **결론**: 봇당 getUpdates는 1개만 허용 → 같은 토큰을 **다른 곳에서 폴링 중**이면 충돌. (사용자 확인: 토큰 공유 중이었음)
- **해결**: 뉴스 전용 봇 토큰 신규 발급 → 폴링 정상.
- **부수 교훈**: sendMessage(발송)는 공유해도 무해, getUpdates(수신)만 배타적. 발송 기능은 문제 없었던 이유.
- **또 하나**: 봇을 빠르게 죽였다 켜면 서버측 롱폴이 잔존(최대 30초)해 자기 자신과 충돌 → 재시작 간 텀을 둬야 함.

### 5-3. 대용량 중복제거 O(n²) → 접두어 버킷팅
- **증상**: 5,404건 병합에서 2분 타임아웃.
- **원인**: 제목 유사도(difflib)를 모든 기존 대표와 비교 → O(n²).
- **해결**: 정규화 제목 **접두어 4자로 버킷팅**, 같은 버킷 안에서만 비교. **120초+ → 0.75초**.
- **교훈**: 근사 중복제거는 블로킹(bucketing)으로 후보를 좁히면 정확도 손실 거의 없이 수십~수백 배 빨라진다.

### 5-4. 크롤 기사 URL 오병합 방지
- 개별 기사 URL이 없어 섹션 URL을 쓰면, canonical URL이 같아 **서로 다른 기사가 한 스토리로 오병합**.
- **해결**: URL 없는 항목은 url을 비우고 **제목 유사도 경로로만** 그룹핑.

### 5-5. 증분 적재의 교차병합 한계
- 크롤분을 나중에 따로 적재하면 기존 DB 행과 제목 병합이 안 됨(같은 배치 내에서만 병합).
- **해결/규칙**: 증분 채널도 **그 시점까지의 모든 raw를 한 번에 재적재**해야 교차출처가 정확.

### 5-6. watch_alert notified 플래그 버그
- 알림은 발송됐는데 `notified` 갱신 SQL이 잘못된 컬럼(article_id ↔ alerts PK) 참조 → 미표시 → **중복 발송 위험**.
- **해결**: alerts PK(id)로 UPDATE. dry-run 재실행 0건으로 dedup 검증.

### 5-7. 관심물건 과다매칭
- region에 "광명"(시명)만 넣으니 119건 매칭(광명시흥 등 무관 지역까지).
- **해결**: region은 **구체 고유명사**(단지명·정비구역명)로 좁힘 + 알림은 relevance=1 + 스코어 하한. 135건 → 정확한 13건.

### 5-8. 백신의 PowerShell 차단
- 봇 상주를 위해 PowerShell로 프로세스를 반복 생성/종료 → 백신이 의심 동작으로 차단(4646).
- **교훈**: 상주 프로세스 기동은 대화형 자동화보다 **스케줄러·시작프로그램**에 맡기는 게 백신 마찰이 적다.

## 6. 스코어링·필터링 설계 요약

- **스코어(0~100)** = 출처 신뢰도 티어(T1 40/T2 28/T3 16) + 교차출처(최대 25) + 최신성(최대 20) + 키워드 매칭수(최대 15).
- **관련도(relevance)**: 검색어 핵심 토큰이 제목/본문에 실제 존재하면 1. 브리핑·알림은 기본 relevance=1만.
- **교차출처(corroboration)**: 같은 사안을 다룬 소스 수. 삭제 대신 **신호로 보존**해 스코어·배지에 반영.

## 7. 최종 산출물 파일 구조

```
auction-news/
├ CLAUDE.md                      하네스 포인터 + 변경이력
├ .env(.example)                 NAVER_*, TELEGRAM_* 키
├ config/  keywords/sources/telegram/watchlist.json
├ data/    news.db (SQLite)
├ reports/ news_briefing_*.html, news_archive_*.html
├ scripts/ run_morning_send.cmd, run_bot.cmd, start_bot.vbs  (스케줄러/시작프로그램용)
├ docs/    WORKLOG.md (이 문서)
└ .claude/
   ├ agents/  news-{api-collector,web-researcher,crawler,curator,reporter,notifier}.md
   └ skills/  realestate-news-harness/ + naver-news-api/ news-web-research/ news-crawl/
              news-curation/ news-report/ news-telegram/ news-watchlist/
```

## 8. 하네스 설계에서 배운 것 (교훈 정리)

1. **채널을 분리하고 실패를 허용**하면 시스템이 견고해진다(한 채널 죽어도 산출물이 나온다).
2. **중복은 지우지 말고 신호로 바꾼다**(교차출처 → 중요도).
3. **근사 알고리즘은 블로킹으로 스케일**한다(버킷팅).
4. **외부 서비스의 제약을 먼저 이해**한다(텔레그램 폴링 배타성, 네이버 API 권한).
5. **비밀·상태의 위치가 실행 위치를 결정**한다(로컬 키·DB → 로컬/자기 서버 크론, 클라우드 루틴 부적합).
6. **자동화 마찰(백신 등)** 은 상주 실행을 스케줄러/시작프로그램에 위임해 줄인다.

## 9. 남은 작업 (TODO)

- [ ] 스케줄링 최종 확정: 로컬 작업 스케줄러(PC 상시 ON) vs GCP VM crontab(24/7).
- [ ] 백신 예외 등록(pythonw / .cmd) 또는 GCP VM로 이전.
- [ ] `config/watchlist.json`의 예시 물건을 실제 담당 물건으로 교체.
- [ ] GitHub(earthskyisbig/auction-news) 커밋·푸시.

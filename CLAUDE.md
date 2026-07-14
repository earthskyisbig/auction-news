# auction-news

## 하네스: 부동산 뉴스 수집

**목표:** 부동산 뉴스를 네이버 오픈 API·WebSearch/WebFetch·브라우저 크롤링으로 복합 수집 → 중복제거·교차출처 병합·스코어링 → SQLite 누적 DB → HTML 브리핑 리포트.

**트리거:** 부동산 뉴스 수집/브리핑/리포트 관련 요청 시 `realestate-news-harness` 스킬을 사용하라. 후속(재실행·리포트만·특정 카테고리·업데이트)도 동일 스킬. 단일 기사 단순 질의는 직접 응답 가능.

**환경:** 프로젝트 루트 `.env` — 네이버 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`, 텔레그램 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (`.env.example` 참고). 네이버 키 없으면 API 채널 제외하고 웹서치+크롤로 동작.

**카테고리(8):** policy 정책·규제·세제 · market 시장·시세 · auction 경매·공매 · redevelopment 재개발·재건축 · subscription 분양·청약 · urban_plan 도시계획·공공주택 · industrial 산업단지·신도시 · local 지역단지·호재(경매 호재용).

**관심사·소스 설정:** `config/keywords.json`(카테고리별 키워드), `config/sources.json`(신뢰도 티어·크롤 대상), `config/telegram.json`(발송시각·구독), `config/watchlist.json`(관심 키워드·담당 물건). 코드 수정 없이 이 파일들만 고쳐 관심사를 바꾼다.

**워치리스트:** `news-watchlist` 스킬 — 관심 지역·정비구역·정책을 `category=watch`로 추가 수집(⭐관심 섹션), 검색어가 본문에 실제 있는지 `relevance` 필터, 담당 물건(properties.region) 매칭 시 `watch_alert.py`로 즉시 텔레그램 알림(다이제스트와 별개, 중복 없음). properties.region은 구체 고유명사 권장.

**텔레그램:** `news-telegram` 스킬 — 봇 상주(`telegram_bot.py`)로 매일 지정 시각 자동 발송 + 명령어 설정(/time, /on, /off, /now). 발송만 수동: `send_digest.py [--collect]`.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-07-14 | 초기 구성 (에이전트 5, 스킬 6, 스크립트 4) | 전체 | - |
| 2026-07-14 | 8카테고리 개편(분양·청약, 지역단지·호재 신설), 리포트에 기준일 대형헤더·카테고리별 요약·sticky 네비 추가 | keywords.json, build_report.py | 분양/청약 별도분류 + 경매 호재용 지역단지 뉴스 요청 |
| 2026-07-14 | 텔레그램 아침발송 하네스 추가 (news-telegram 스킬, news-notifier 에이전트) | 신규 | 매일 07:00 텔레그램 다이제스트 + 명령어 구독설정 요청 |
| 2026-07-14 | 네이버 블로그 검색 채널 추가 (naver_blog_search.py, method=blog) + ingest 접두어 버킷팅 최적화(5천건 0.7초) | naver-news-api, ingest.py, send_digest.py | 블로그글 수집 요청 + 대용량 병합 성능 |
| 2026-07-14 | 공유 봇 토큰은 getUpdates 폴링 충돌(409) → 명령봇은 전용 토큰 필요. 발송(sendMessage)은 공유해도 무해 | news-telegram | 봇 토큰 공유 사용 확인 |
| 2026-07-14 | 워치리스트 하네스 추가: 관심 키워드 수집(watch 카테고리)·relevance 관련도 필터·관심물건 매칭 즉시 알림 | news-watchlist 스킬, watchlist.json, ingest.py, db.py(relevance/watch_hits/alerts), watch_alert.py, 리포트/다이제스트 watch 카테고리 | 관심 키워드 수집+관련도 필터+담당물건 뉴스 알림 요청 |
| 2026-07-14 | GitHub Actions 매일 07:00 KST 자동화(빌드→커밋→텔레그램). 키는 Secrets. scripts/build.py 단일 엔트리포인트 | .github/workflows/daily-news.yml, scripts/build.py, docs/GITHUB_ACTIONS.md | 클라우드 크론(로컬 PC 불필요) 요청 |

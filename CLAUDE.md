# auction-news

## 하네스: 부동산 뉴스 수집

**목표:** 부동산 뉴스를 네이버 오픈 API·WebSearch/WebFetch·브라우저 크롤링으로 복합 수집 → 중복제거·교차출처 병합·스코어링 → SQLite 누적 DB → HTML 브리핑 리포트.

**트리거:** 부동산 뉴스 수집/브리핑/리포트 관련 요청 시 `realestate-news-harness` 스킬을 사용하라. 후속(재실행·리포트만·특정 카테고리·업데이트)도 동일 스킬. 단일 기사 단순 질의는 직접 응답 가능.

**환경:** 프로젝트 루트 `.env` — 네이버 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`, 텔레그램 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (`.env.example` 참고). 네이버 키 없으면 API 채널 제외하고 웹서치+크롤로 동작.

**카테고리(8):** policy 정책·규제·세제 · market 시장·시세 · auction 경매·공매 · redevelopment 재개발·재건축 · subscription 분양·청약 · urban_plan 도시계획·공공주택 · industrial 산업단지·신도시 · local 지역단지·호재(경매 호재용).

**관심사·소스 설정:** `config/keywords.json`(카테고리별 키워드), `config/sources.json`(신뢰도 티어·크롤 대상·`blog_channel` 블로그 전용 규칙), `config/telegram.json`(발송시각·구독), `config/watchlist.json`(관심 키워드·담당 물건), `config/blogs.json`(신뢰 블로거 RSS 구독), `config/press.json`(기관 보도자료·전문지). 코드 수정 없이 이 파일들만 고쳐 관심사를 바꾼다.

**신뢰 블로거 RSS:** `config/blogs.json`에 등록한 블로거의 새 글을 `rss.blog.naver.com/{id}.xml`로 통째로 수집한다(API 키 불필요). 검색 채널과 반대 방향 — 검색어에 안 걸려도 들어온다. `tier`(기본 2)로 스코어 가중치, `relevance`는 1 고정(구독 콘텐츠라 검색 노이즈 필터가 무의미), 리포트에 `⭐신뢰` 배지. 등록만 하면 되고 코드는 안 건드린다.

**기관 보도자료·전문지:** `config/press.json` — 국토교통부·서울시·인천시·금융위원회 보도자료 원문과 정비사업 전문지(하우징워치·하우징헤럴드·디벨로퍼뉴스)를 순수 HTTP로 받는다(키·브라우저 불필요 → GH Actions 가능). 정부 보도자료는 전 분야라 `topic_filter`로 부동산 건만 남기고, 전문지는 전량 통과. tier1(정부)·tier2(전문지), 리포트에 `🏛공식` 배지. `press_feeds.py`의 파서는 rss/molit/fsc/incheon 4종. MTN은 목록이 JS 렌더라 HTTP 수집 불가 → `crawl_targets`(브라우저 크롤 전용)와 tier2 등재로 커버. 경기도는 사용자가 찾은 무인증 RSS 3종(주거정책 E004·교통 E007·보도자료) 등재 — 카테고리 피드는 날짜 태그가 없어 기사번호에서 추출하며 갱신이 느려 소스별 `max_age_days: 90` 적용.

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
| 2026-08-08 | **지역 온디맨드 수집 추가** — `scripts/region_news.py`. 지역 인자를 받아 2단계 검색(주소 기반 1차 → 본문에서 지구명·사업명 역추출 → 2차)으로 즉석 수집·적재(`run_id=od-{지역}-{날짜}`)하고 확정/계획/검토중 3단계로 분류. 근접 가중치(읍면동 동시출현 ×3)·동시출현 가드·규제구역 스톱워드·철도맥락 요구·동명이지 제외후보 표시 내장. 워치리스트는 장기 모니터링용으로 **병행 유지** | scripts/region_news.py(신규), realestate-news-harness SKILL.md(Phase 0 분기 + 온디맨드 모드 절) | 경매 물건은 뜬 뒤에야 지역이 정해져 워치리스트 사전등록 전제가 성립하지 않음. 검증: `은계` 0→65건, `서남부 광역철도` 0→7건, `신구로선` 0→28건, 총 8,301→8,786건. 2차 검색어에 `은계지구` 자동 도출(1위 18회) |
| 2026-08-08 | 워치리스트에 시흥 은계지구·수도권 서남부 광역철도(제2경인선·신구로선·신천신림선)·광명시흥 3기 신도시·거모지구 키워드 9종 추가 | config/watchlist.json | 입지분석 하네스에서 `은계` 0건 확인. 미등록 지역은 DB 신선도와 무관하게 영구 0건이므로 키워드 등록이 유일한 해법 |
| 2026-08-08 | ⚠️ **정본 DB는 원격(origin/main)이다.** `data/news.db`는 로컬 `.gitignore`(data/*.db) 대상이라 로컬에서 추적되지 않지만, GitHub Actions는 `-f`로 강제 커밋한다 → 로컬 파일과 원격 커밋본이 조용히 갈라진다. 2026-08-08 확인 시 원격 26,418건 vs 로컬 8,301건(7월하순 14,894 vs 885). 로컬에서 build.py를 돌리기 전에 반드시 원격본을 내려받을 것 | .gitignore, data/news.db, scripts/build.py | 로컬 DB가 7/14 이후 정체된 것으로 오진했으나, 실제로는 GH Actions가 매일 정상 실행 중이었고 로컬만 26커밋 뒤처져 있었음 |
| 2026-08-25 | **블로그 채널 정밀화** — 수집을 `local`·`redevelopment`+`watch`로 축소(정책·시장 등 6카테고리 제외), `sort=date`·게시일 400일 상한. 리포트에 **🏘 현장 목소리** 섹션 신설(블로그 단독분·임계 25점·watch 우선·`⚠광고` 배지·상한 80건). 설정은 `sources.json`의 `blog_channel` 한 곳 | config/sources.json, naver_blog_search.py, build_report.py, build.py, realestate-news-harness SKILL.md | 블로그 3,775건 중 **브리핑(45점)에 오른 유효 건수 0**이었음. tier3 고정(16점)이라 구조적으로 임계를 못 넘김. 무작위 샘플 12/12가 '부동산 대책 요약' 재탕글이었고, 값어치 있는 것은 워치리스트 현장글(광명뉴타운 주간 실거래·구역 동향)뿐. 검증: 수집 2,000여건→579건(watch 288·local 157·redevelopment 134), 2026년 글 99%, 광고 판정 56건 |
| 2026-08-25 | **신뢰 블로거 RSS 구독 채널 신설** — `naver_blog_rss.py` + `config/blogs.json`(16개 피드). 검색이 아니라 구독이라 검색어 불일치로 놓치던 글이 들어온다. tier2·relevance1 고정, `⭐신뢰` 배지(전화번호 상호여도 광고로 깎지 않음), ingest가 병합 시에도 신뢰·티어를 승격. 분류는 제목+태그+RSS분류만 보고 CAT_TOKENS 단일어 2점·keywords.json 구 1점 가중투표 | naver_blog_rss.py(신규), config/blogs.json(신규), ingest.py, build_report.py, build.py | 사용자가 직접 선별한 블로거 목록 제공. 검증: 16피드 중 14개 응답 206건 수집(휴면 1·세미나글만 1은 WARN으로 명시), 41건이 45점 이상으로 브리핑 본문 진입, 분류 오류 5건 재검 후 전건 정정 |
| 2026-08-25 | **기관 보도자료·정비사업 전문지 채널 신설** — `press_feeds.py` + `config/press.json`(국토부·서울시·금융위·하우징워치·하우징헤럴드). 분류 규칙을 `classify.py`로 분리해 RSS 채널과 공유. **`canon_url` 버그 수정**: 쿼리·프래그먼트를 버려서 `article.html?no=27196` 같은 CMS의 기사 전체가 한 URL로 붕괴 → 무관한 기사 40건이 한 스토리로 병합되고 있었다 | press_feeds.py(신규), classify.py(신규), config/press.json(신규), ingest.py, build_report.py, build.py | 국토부·서울시·금융위 원문과 정비사업 전문지 요청. 검증: 102건 수집(국토부 10·서울시 10·금융위 2·하우징워치 40·하우징헤럴드 40), 주제필터로 정부 보도자료 75건 제외, 그룹핑 6→101(붕괴 해소), 65건이 45점 이상 |
| 2026-08-25 | 보도자료 채널에 인천시(전용 파서)·디벨로퍼뉴스(RSS) 추가, mtn.co.kr·dpnews.co.kr tier2 등재, MTN 건설부동산은 crawl_targets 등록 | config/press.json, config/sources.json, press_feeds.py | 경기도·인천 추가 요청 + MTN·dpnews 추가 요청. 경기도 뉴스포털·MTN은 목록이 JS 렌더라 순수 HTTP 불가(경기도 RSS는 인증키 필요). 검증: 인천 5건(노후계획도시 선도지구 등)·dpnews 40건 수집, 총 147건 |
| 2026-08-25 | 경기도 뉴스포털 무인증 RSS 3종 추가(주거정책 E004·교통 E007·보도자료) + 소스별 `max_age_days`·`topic_extra` 지원, 필터 0건과 수신 0건의 WARN 구분 | config/press.json, press_feeds.py | 사용자가 무인증 RSS 경로 발견(내 탐색은 인증키 필요 결론이었음 — 정정). 카테고리 피드 특이점: 날짜 태그 없음(기사번호 YYYYMMDDHHMM에서 추출), 본문 태그가 `deion`으로 잘림, 갱신 느림(최신 7월말). 교통 피드는 철도·GTX가 입지 호재라 `topic_extra`로 통과어 확장 |

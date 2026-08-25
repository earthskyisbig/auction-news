---
name: news-crawl
description: 브라우저 자동화(claude-in-chrome)로 부동산 전문 매체·정부 보도자료 게시판을 직접 크롤링해 뉴스를 수집한다. 검색 API·WebSearch가 색인 못하는 게시판형 원문(국토부 보도자료, 매경/한경 부동산 섹션)을 잡는다. news-crawler 에이전트가 사용한다. "부동산 뉴스 크롤링", "국토부 보도자료 수집", "매체 사이트 크롤링", "뉴스 하네스 크롤 단계"를 언급하거나 하네스가 크롤링 단계를 실행할 때 반드시 이 스킬을 사용할 것.
---

# news-crawl — 브라우저 크롤링 수집

3차 수집원. 검색 API·웹서치가 실시간 색인하지 못하는 **게시판형 원문 소스**를 직접 크롤링한다. 특히 정책의 1차 출처인 정부 보도자료가 핵심 가치.

## 대상

`config/sources.json`의 `crawl_targets`:
- 국토교통부 보도자료 게시판 (정책 원문 — 최고 신뢰도 tier1)
- 한경 부동산 / 매경 부동산 섹션 (시장·분양 큐레이션)

새 대상은 `crawl_targets`에 `{name,url,note}`로 추가한다.

## 절차 (claude-in-chrome MCP)

1. **툴 로드** — 브라우저 툴이 deferred면 한 번의 ToolSearch로 일괄 로드:
   `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__tabs_create_mcp`
2. **세션 시작** — `tabs_context_mcp`로 현재 탭 확인 후 `tabs_create_mcp`로 새 탭 생성(기존 탭 재사용 금지).
3. **목록 페이지 방문** — 각 `crawl_targets` URL로 `navigate`, `get_page_text`로 목록의 제목·링크·날짜 추출.
4. **필터링** — `config/keywords.json` 키워드와 매칭되는 항목만 선별(전량 수집 금지 — 부동산 무관 기사 배제).
5. **원문 확인(선택)** — 중요 항목은 상세 페이지로 이동해 본문 앞부분으로 요약을 만든다.
6. **정규화 출력** — `_workspace/crawl_raw.json`에 JSON 배열 저장.

## 출력 스키마 (curator ingest.py 호환)

```json
[{
  "title":"…","description":"요약","url":"상세 원문 URL","naver_url":"",
  "source":"molit.go.kr","pub_date":"ISO 또는 빈문자열",
  "category":"policy|market|…","keywords_matched":["…"],
  "collection_method":"crawl","raw":{}
}]
```

## 안전 규칙 (중요)

- **다이얼로그 유발 금지**: alert/confirm/prompt를 띄우는 요소(삭제·로그인 버튼 등) 클릭 금지 — 확장이 응답 불능이 된다.
- **읽기 위주**: 로그인·폼 제출·결제 흐름에 진입하지 않는다. 공개 게시판 열람만.
- **막히면 중단**: 2~3회 시도 후 페이지가 안 뜨거나 요소가 없으면 그 대상은 건너뛰고 다음으로. 무한 재시도·무관 페이지 탐색 금지.
- **로봇 배려**: 대상당 목록 1~2페이지까지만. 과도한 페이지네이션 금지.

## 왜 이렇게 하나

- **정책 1차 출처**: 국토부 보도자료는 기사보다 먼저·정확하다. tier1으로 스코어가 높게 잡혀 리포트 상단에 온다.
- **크롤링은 선택 채널**: 브라우저 환경이 없거나 실패해도 파이프라인은 API+웹서치로 성립한다. 크롤 실패는 치명적이지 않으니 보고만 하고 진행한다.

## 협업

산출물을 `_workspace/crawl_raw.json`으로 남기고 curator에 완료 통보. 실패 시 "크롤 수집 실패(사유)"를 명시해 리포트에 누락이 드러나게 한다.

## 키 없는 보도자료 수집 (`scripts/press_feeds.py`)

브라우저 크롤은 GitHub Actions에서 못 돈다. 정기 자동화에 태울 원문 수집은 이 스크립트를 쓴다. 대상은 `config/press.json`.

```bash
python .claude/skills/news-crawl/scripts/press_feeds.py --press config/press.json --config config/keywords.json --watchlist config/watchlist.json --out _workspace/press_raw.json
```

| 소스 | type | 비고 |
|---|---|---|
| 국토교통부 보도자료 | `molit` | 첫 요청이 **307로 쿠키를 심는다** → `CookieJar` 없이는 무한 307. 목록 `<tr>`에 분야·등록일 |
| 서울시 보도자료 | `rss` | 링크가 `#view/464541` **프래그먼트**로 기사를 구분. 본문은 `description`이 아니라 `<cn>` |
| 금융위원회 보도자료 | `fsc` | 행에 날짜가 없다 → 첨부파일명 앞 `YYMMDD`로 추정 |
| 하우징워치 | `rss` | 날짜가 `dc:date`, 형식은 `YYYY-MM-DD HH:MM:SS`(RFC822 아님) |
| 하우징헤럴드 | `rss` | 조합 공고가 대량. 제목 패턴이 서로 비슷해 URL 정규화가 정확해야 한다 |
| 인천시 보도자료 | `incheon` | `<li>` 블록의 subject·요약·날짜. 링크는 `?repSeq=` 쿼리로 기사 구분 |
| 디벨로퍼뉴스 | `rss` | 정비사업 전문. 표준 RSS |

- `filter: true`인 소스는 `topic_filter` 용어가 제목·요약에 없으면 버린다. **정부·지자체 보도자료는 철도·보험·축제까지 전 분야**라 필수다(실측: 국토부 30건 중 17건, 서울시 50건 중 40건이 주제 밖).
- `pages`로 목록 페이지를 넘긴다(게시판 1페이지 10건 → 하루치를 놓친다).
- 수집 0건이면 WARN을 찍는다. 게시판 HTML은 언제든 구조가 바뀌므로 조용한 0건이 가장 위험하다.
- 출력에 `raw.official=true`가 붙고 `ingest.py`가 relevance 필터를 면제한다(원문은 검색 노이즈가 아니다). 리포트에 `🏛공식` 배지.

**HTTP로 못 잡는 곳**: 경기도 뉴스포털(gnews.gg.go.kr)·MTN 건설부동산은 목록이 JS 렌더다. MTN은 `sources.json`의 `crawl_targets`(브라우저 크롤)와 tier2 등재(네이버 검색 유입분 가중)로 커버한다. 경기도 RSS는 무료 인증키(gnews 오픈API) 신청 후 `type: rss`로 추가하면 된다.

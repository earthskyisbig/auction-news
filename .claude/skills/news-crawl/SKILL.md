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

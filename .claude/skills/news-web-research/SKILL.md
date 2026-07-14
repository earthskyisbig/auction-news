---
name: news-web-research
description: WebSearch와 WebFetch로 부동산 뉴스를 보완 수집한다. 네이버 API가 놓치는 심층·해설·원문 기사와 최신 속보를 찾아 정규화 JSON으로 출력한다. news-web-researcher 에이전트가 사용한다. "웹서치로 뉴스 보완", "부동산 뉴스 심층 조사", "원문 기사 찾기", "뉴스 하네스 웹 수집"을 언급하거나 하네스가 웹 리서치 단계를 실행할 때 반드시 이 스킬을 사용할 것.
---

# news-web-research — WebSearch/WebFetch 보완 수집

네이버 API의 사각지대를 메우는 2차 수집원. API가 색인하지 못한 정부 보도자료 원문, 해설·분석 기사, 특정 매체 전용 콘텐츠, API 지연분 속보를 잡는다.

## 역할 분담 (중복 최소화)

API 수집(`_workspace/api_raw.json`)이 이미 넓게 훑으므로, 웹 리서치는 **보완**에 집중한다:
- API 결과가 빈약한 카테고리를 우선 보강 (예: 정책 원문, 도시계획 고시)
- `config/sources.json`의 `preferred_domains`(정부·주요 경제지) 위주로 탐색
- 큰 이슈는 원문 기사 본문을 WebFetch로 확보해 요약 품질을 높인다

## 절차

1. **API 결과 확인** — `_workspace/api_raw.json`이 있으면 카테고리별 건수를 보고 빈약한 곳을 파악한다.
2. **WebSearch** — 카테고리별 대표 키워드 + 기간 한정(예: "최근", "2026")으로 검색한다. `config/keywords.json`을 참고하되, 시의성 있는 구체 이슈어(지역명·단지명·법안명)를 조합해 롱테일을 잡는다.
3. **WebFetch 심층화** — 검색 결과 중 티어1/2 도메인이거나 중요도가 높아 보이는 기사는 URL을 WebFetch로 가져와 제목·요약·발행일·매체를 정확히 추출한다.
4. **정규화 출력** — 아래 스키마로 `_workspace/web_raw.json`에 JSON 배열 저장.

## 출력 스키마 (curator ingest.py 호환)

```json
[{
  "title": "…", "description": "핵심 2~3문장 요약",
  "url": "원문 기사 URL", "naver_url": "",
  "source": "hankyung.com", "pub_date": "2026-07-14T...Z 또는 빈문자열",
  "category": "policy|market|auction|redevelopment|urban_plan|industrial",
  "keywords_matched": ["매칭 키워드"], "collection_method": "web", "raw": {}
}]
```

- `id`는 curator가 title+url 해시로 생성하므로 넣지 않아도 된다(넣어도 무방).
- `source`는 반드시 원문 도메인(www 제외). 티어링·중복판정의 핵심.
- `pub_date`는 확인되면 ISO, 불확실하면 빈 문자열(추정 금지).

## 왜 이렇게 하나

- **원문 도메인 정확성**: curator의 신뢰도 티어와 교차출처 병합이 `source`에 의존한다. 검색 스니펫의 재배포 링크가 아니라 실제 매체 도메인을 기록한다.
- **요약은 사실 기반**: description은 기사에 실제로 있는 내용만. 추측·과장 금지 — 리포트 신뢰도가 여기서 갈린다.
- **날짜 미상은 공란**: 잘못된 날짜는 최신성 스코어와 기간 필터를 오염시킨다. 모르면 비운다.

## 협업

산출물은 파일(`_workspace/web_raw.json`)로 남기고, curator에게 완료를 알린다. API·크롤러와 병렬 실행되며 중복은 curator가 병합하므로, 여기서 완벽한 중복제거를 시도하지 않는다.

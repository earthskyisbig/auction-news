---
name: news-curation
description: 여러 수집원(네이버 API·웹서치·크롤링)의 부동산 뉴스 JSON을 통합해 중복제거·교차출처 병합·카테고리 분류·중요도 스코어링 후 SQLite DB에 누적 적재한다. news-curator 에이전트가 사용한다. "뉴스 중복제거", "뉴스 DB 적재", "기사 통합·분류·스코어링", "뉴스 큐레이션"을 언급하거나 하네스가 수집분을 통합·저장하는 단계를 실행할 때 반드시 이 스킬을 사용할 것.
---

# news-curation — 통합·중복제거·스코어링·적재

수집 3채널의 산출물을 하나의 정제된 DB로 만드는 파이프라인 허브. 리포트 품질은 이 단계의 중복제거·스코어링 정확도에서 갈린다.

## 실행

```bash
python .claude/skills/news-curation/scripts/ingest.py \
  --inputs _workspace/api_raw.json _workspace/web_raw.json _workspace/crawl_raw.json \
  --sources config/sources.json \
  --run-id 2026-07-14T09
```

- 없는 입력 파일은 경고 후 건너뛴다(채널 일부 실패해도 진행).
- DB는 `data/news.db`(SQLite). 환경변수 `NEWS_DB`로 경로 변경 가능.
- 결과 요약을 stdout에 JSON(`{new, merged, total, run_id}`)으로 낸다.

## 중복제거 로직

두 단계로 같은 스토리를 묶는다:
1. **canonical URL 동일** — `netloc(www제거)+path` 정규화 후 일치 → 동일 기사.
2. **제목 유사도 ≥ 0.86** (difflib) — URL이 달라도(교차출처: 같은 사안, 다른 매체) 병합.

병합 시:
- `corroboration` = 묶인 고유 출처 수 (교차 검증 강도)
- `methods` = 수집 방법 합집합 (api/web/crawl)
- 대표 레코드는 **가장 높은 신뢰도 티어** 소스를 채택

재실행 시 이미 있던 `id`는 methods·keywords·corroboration만 갱신(upsert). 이력이 누적되되 중복 폭증하지 않는다.

## 카테고리

6종 고정: `policy`(정책·규제·세제) · `market`(시장·시세) · `auction`(경매·공매) · `redevelopment`(재개발·재건축·분양) · `urban_plan`(도시계획·공공주택) · `industrial`(산업단지·신도시·뉴타운). 수집원이 지정한 category를 신뢰하되, 명백히 어긋나면 curator가 보정한다.

## 스코어링 (0~100)

| 요소 | 배점 | 근거 |
|------|------|------|
| 출처 신뢰도 티어 | 40/28/16 (T1/T2/T3) | 정부·공식 원문 우선 |
| 교차출처 corroboration | 최대 25 (출처수×5) | 여러 매체가 다룬 사안 = 중요 |
| 최신성 | 최대 20 (1일내20/3일15/7일10/30일5) | 정기 브리핑은 신선도가 가치 |
| 키워드 매칭 수 | 최대 15 (개수×3) | 여러 관심축에 걸치면 중요 |

티어 매핑은 `config/sources.json`의 `source_tiers`. 정부/공식(tier1) > 주요 경제지(tier2) > 일반/전문(tier3).

## DB 스키마

`scripts/db.py`의 `SCHEMA` 참조. 두 테이블:
- `articles` — 스토리당 1행 (중복 병합 후). 조회·리포트의 원천.
- `collection_runs` — 실행 이력(신규/병합/누적 건수) → 추세 분석·감사 추적.

## 왜 이렇게 하나

- **교차출처를 삭제 아닌 신호로**: 같은 사안 중복을 지우기만 하면 "얼마나 크게 다뤄진 이슈인지" 정보를 잃는다. corroboration으로 남겨 스코어에 반영한다.
- **티어 상위 소스 채택**: 같은 스토리면 정부 원문·주요지 기사를 대표로 링크해 리포트 신뢰도를 높인다.
- **upsert 누적**: 정기 자동화라 매번 새 DB가 아니라 하나의 DB에 쌓아야 추세(카테고리별 이슈 증감)가 보인다.

## 협업

적재 완료 후 `{new, merged, total}`을 reporter/오케스트레이터에 전달. reporter는 이 DB를 읽어 HTML을 만든다.

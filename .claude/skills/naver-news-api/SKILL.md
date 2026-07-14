---
name: naver-news-api
description: 네이버 뉴스 검색 오픈 API로 부동산 뉴스를 수집한다. config/keywords.json의 카테고리별 키워드를 일괄 검색해 정규화된 JSON 배열로 출력하고 curator가 적재하도록 넘긴다. news-api-collector 에이전트가 사용한다. "네이버 API로 뉴스 수집", "부동산 뉴스 검색", "뉴스 수집 실행", "정기 뉴스 수집"을 언급하거나 뉴스 하네스가 API 수집 단계를 실행할 때 반드시 이 스킬을 사용할 것.
---

# naver-news-api — 네이버 뉴스 오픈 API 수집

부동산 뉴스 1차 수집원. 네이버 뉴스 검색 API는 넓은 커버리지·빠른 속도·안정적 구조라서 파이프라인의 기본 수집 채널로 둔다. WebSearch/크롤링은 이 결과를 **보완**한다.

## 인증

환경변수 두 개가 필요하다:
- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`

프로젝트 루트 `.env`에 넣으면 스크립트가 자동 로드한다(`.env.example` 참고). 발급: https://developers.naver.com → 애플리케이션 등록 → "검색" API 사용.

## 실행

키워드 설정 파일 기반 일괄 수집(권장):

```bash
python .claude/skills/naver-news-api/scripts/naver_news_search.py \
  --config config/keywords.json --out _workspace/api_raw.json
```

단일 키워드 테스트:

```bash
python .claude/skills/naver-news-api/scripts/naver_news_search.py \
  --query "3기 신도시" --category industrial --display 100
```

## 동작 원리

- `--config`를 주면 `keywords.json`의 모든 카테고리·키워드를 순회 검색한다(키워드당 최대 100건, `sort=date`).
- 각 기사를 정규화한다: HTML 태그 제거, pubDate → UTC ISO, `originallink` 우선(원문 도메인 확보), 제목+URL 해시로 `id` 생성.
- API 응답 내 중복은 `id`로 1차 제거한다. 교차출처 병합은 curator가 담당한다.
- rate-limit 여유를 위해 요청 간 0.12초 간격. 일일 호출 한도(기본 25,000)를 초과하지 않도록 키워드 수를 관리한다.

## 출력 스키마

curator의 `ingest.py`가 그대로 받는 dict 배열. 필드: `id, title, description, url, naver_url, source, pub_date, category, keywords_matched, collection_method("api"), raw`.

## 왜 이렇게 하나

- **원문 링크 우선**: `originallink`를 써야 실제 매체 도메인으로 신뢰도 티어를 매길 수 있다. `link`(네이버 재배포)만 쓰면 전부 naver.com이 되어 티어링이 무의미해진다.
- **sort=date**: 정기 수집은 "최신 흐름"이 목적이므로 관련도(sim)보다 최신순이 맞다. 특정 이슈 심층 조사는 `--sort sim`으로 바꾼다.
- **키워드 = 설정 파일**: 관심사가 바뀌면 코드가 아니라 `config/keywords.json`만 고친다.

## 에러 처리

- 키 미설정 → exit 2 + stderr 안내. 오케스트레이터는 이 경우 API 단계를 건너뛰고 WebSearch/크롤링으로 진행한다.
- 개별 쿼리 HTTP 에러 → 해당 쿼리만 건너뛰고 경고, 나머지 계속.

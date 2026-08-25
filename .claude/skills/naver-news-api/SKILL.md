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

## 블로그 채널 규칙 (`naver_blog_search.py`)

블로그는 뉴스와 성격이 다르다. **제도 요약 재탕글이 노이즈의 대부분**이고, 값어치는 워치리스트 지역의 현장 매물·호가·구역 동향에 몰려 있다. 그래서 수집 범위를 `config/sources.json`의 `blog_channel`로 좁힌다.

```bash
python naver_blog_search.py --config config/keywords.json --watchlist config/watchlist.json   --sources config/sources.json --out _workspace/blog_raw.json
```

| 키 | 뜻 |
|---|---|
| `categories` | 블로그를 수집할 카테고리 화이트리스트(기본 `local`,`redevelopment`). 나머지는 제외 |
| `always_watch` | true면 워치리스트 키워드는 화이트리스트와 무관하게 항상 수집 |
| `sort` | `date` 권장. `sim`이면 10년 전 글이 섞인다 |
| `max_age_days` | 게시일 상한(기본 400). 날짜 미상은 통과 |
| `report_min_score` / `ad_markers` | 리포트 쪽에서 사용(현장 목소리 섹션 임계·광고 판정) |

- `--sources`를 빼면 제한이 풀려 **전 카테고리를 긁는다.** 정기 파이프라인에서는 반드시 넘긴다.
- 일회성으로 전부 긁어야 하면 `--all-categories`.
- 카테고리를 늘리기 전에 그 카테고리 블로그가 뉴스에 없는 정보를 주는지 먼저 확인할 것 — `policy`/`market`은 확인 결과 전량 재탕이었다.

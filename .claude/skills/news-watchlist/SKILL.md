---
name: news-watchlist
description: 관심 워치리스트(지역명·정비구역·규제정책 키워드)로 뉴스를 추가 수집하고, 관심 물건(담당 경매물건·정비구역)과 뉴스가 겹치면 별도 텔레그램 알림을 보낸다. 관련도 필터링으로 검색 노이즈를 제거한다. "관심 지역 뉴스", "워치리스트", "관심 물건 알림", "담당 물건 지역 뉴스", "정비구역 뉴스 알림"을 언급하면 반드시 이 스킬을 사용할 것.
---

# news-watchlist — 관심 키워드 수집 · 관련도 필터 · 관심물건 알림

일반 카테고리 수집 위에, 사용자 고유의 관심사(지역·정비구역·정책)와 담당 물건을 겨냥한 3가지 기능을 얹는다.

## 설정: `config/watchlist.json`

```json
{
  "keywords": ["광명뉴타운", "토지거래허가구역", "재건축 초과이익환수"],
  "properties": [
    {"id":"p1","name":"광명 철산주공","region":["철산주공","철산동 재건축"],"note":"담당 경매물건"}
  ]
}
```

- **keywords**: 관심 지역·정비구역·정책. `category=watch`로 추가 수집돼 리포트/다이제스트의 **⭐관심 지역·물건** 섹션에 모인다.
- **properties**: 담당/관심 물건. `region` 용어가 뉴스 제목·본문에 걸리면 **즉시 알림**. `region`은 **구체 고유명사**(단지명·정비구역명)를 써야 정확하다 — "광명" 같은 시명만 넣으면 무관 뉴스까지 과다매칭된다.

## 3가지 기능

### 1. 워치리스트 기반 수집
수집기에 `--watchlist config/watchlist.json`을 주면 keywords를 `category=watch`로 함께 검색한다.
```bash
python .claude/skills/naver-news-api/scripts/naver_news_search.py --config config/keywords.json --watchlist config/watchlist.json --out _workspace/api_raw.json
python .claude/skills/naver-news-api/scripts/naver_blog_search.py  --config config/keywords.json --watchlist config/watchlist.json --out _workspace/blog_raw.json
```

### 2. 관련도 필터링
네이버 검색은 fuzzy라 검색어와 무관한 기사도 섞인다. ingest가 각 기사의 `relevance`(검색어 핵심 토큰이 제목/본문에 실제 존재하면 1)를 계산·저장한다.
- 리포트: `--relevant-only`
- 다이제스트: `config/telegram.json`의 `"relevant_only": true`(기본)
- 관심물건 알림은 `relevance=1`인 기사만 큐잉해 노이즈를 원천 차단.

### 3. 관심물건 ↔ 뉴스 매칭 알림 (별도 경로)
ingest에 `--watchlist`를 주면 properties의 region 용어를 뉴스에 대조해 `alerts` 큐에 적재한다. 아침 다이제스트와 **별개**로 즉시 발송:
```bash
python .claude/skills/news-telegram/scripts/watch_alert.py            # 미발송 알림 전송
python .claude/skills/news-telegram/scripts/watch_alert.py --dry-run  # 대상만 확인
python .claude/skills/news-telegram/scripts/watch_alert.py --min-score 45  # 하한 조정
```
- 물건별로 묶어 1메시지(🚨 관심물건 뉴스 알림 + 매칭 기사 목록).
- `alerts` 테이블 `UNIQUE(property_id, article_id)` + `notified` 플래그로 **중복 알림 없음**.
- 기본 `--min-score 40`으로 저품질 매칭 억제.

`send_digest.py --collect`가 수집→적재(관심물건 매칭)→`watch_alert.py`까지 자동 실행하므로, 정기 수집 때마다 새 매칭이 자동 알림된다.

## 봇 명령어
- `/watchlist` — 현재 관심 키워드·물건 목록 확인 (편집은 config 파일)
- `/on watch` · `/off watch` — 관심 카테고리 구독 토글

## 왜 이렇게 하나
- **관심사는 개인 고유**: 카테고리 taxonomy(공용)와 분리해 `watchlist.json`에 둔다. 코드 수정 없이 사용자가 관리.
- **알림은 다이제스트와 분리**: "담당 물건 지역에 재개발 뉴스" 같은 건 아침까지 기다릴 게 아니라 즉시 알아야 가치가 있다.
- **relevance 게이트**: 넓은 지역어의 과다매칭·검색 노이즈를 관련도로 걸러 알림 신뢰도를 지킨다.

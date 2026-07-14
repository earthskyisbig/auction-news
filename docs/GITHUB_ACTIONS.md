# GitHub Actions — 매일 아침 뉴스 자동화

`.github/workflows/daily-news.yml` 이 매일 **07:00 KST**(=22:00 UTC 전날)에:
1. 뉴스+블로그 수집 → 중복제거·스코어링·관련도·관심물건 매칭 (`scripts/build.py`)
2. 결과(`data/news.db`, `reports/*.html`)를 저장소에 **커밋**
3. **텔레그램 다이제스트** 발송 (`send_digest.py`)
4. **관심물건 알림** 발송 (`watch_alert.py`)

클라우드에서 돌기 때문에 **로컬 PC를 켤 필요가 없습니다.** 파이프라인이 전부 Python stdlib라 `pip install`도 없습니다.

## 1회만 설정 (필수 2가지)

### ① 저장소 Secrets 등록
GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret** 에서 4개 등록:

| 이름 | 값 |
|------|-----|
| `NAVER_CLIENT_ID` | 네이버 검색 API Client ID |
| `NAVER_CLIENT_SECRET` | 네이버 검색 API Client Secret |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 받을 chat id |

> 값은 로컬 `.env`에 있는 것과 동일. Secrets는 로그에 노출되지 않는다.

### ② 워크플로우 쓰기 권한 허용 (결과 커밋용)
**Settings → Actions → General → Workflow permissions → "Read and write permissions"** 선택 후 저장.
(워크플로우에도 `permissions: contents: write`를 넣어뒀지만, 저장소 기본이 read-only면 이 설정이 필요.)

## 테스트 (즉시 실행)
**Actions 탭 → "Daily Real Estate News" → Run workflow** 버튼(workflow_dispatch)으로 지금 바로 1회 실행해 볼 수 있다. 성공하면 텔레그램에 다이제스트가 오고, 새 커밋(chore: 데일리 뉴스 …)이 생긴다.

## ⚠️ 로컬 발송과 중복 주의
GitHub Actions가 아침 발송을 맡으면, **로컬 Windows 작업 스케줄러의 `AuctionNews-MorningDigest`는 꺼야** 이중 발송을 막는다:
```
schtasks /Change /TN "AuctionNews-MorningDigest" /DISABLE
```
- 텔레그램 **명령봇**(`telegram_bot.py`, 로컬)은 그대로 둬도 된다 — 발송(sendMessage)은 Actions가, 명령 수신(getUpdates)은 로컬 봇이 맡아 충돌 없음.

## 동작 메모
- **스케줄 지연**: GitHub Actions cron은 부하에 따라 몇 분~십수 분 지연될 수 있다(정시 보장 아님).
- **누적**: `data/news.db`를 커밋해 되돌리므로, 다음 실행이 이전 DB를 이어받아 추세가 쌓인다(검증됨: 재실행 시 신규 32 / 병합 3779 / 누적 4648).
- **키 없을 때**: NAVER 키 미설정이면 수집을 건너뛰고 기존 DB로 리포트만 만든다(실패 아님).
- **커밋 루프 없음**: `GITHUB_TOKEN` 푸시는 다른 워크플로우를 재트리거하지 않는다.

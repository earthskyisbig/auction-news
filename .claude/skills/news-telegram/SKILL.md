---
name: news-telegram
description: 부동산 뉴스 다이제스트를 텔레그램으로 아침 자동 발송하고, 텔레그램 명령어(/time, /on, /off, /now 등)로 발송시각·구독 카테고리를 설정한다. 봇 상주 실행·즉시 발송·구독 설정을 담당한다. news-notifier 에이전트가 사용한다. "텔레그램 발송", "아침 뉴스 알림", "텔레그램 봇 실행", "발송시간 설정", "카테고리 구독", "지금 뉴스 보내줘"를 언급하면 반드시 이 스킬을 사용할 것.
---

# news-telegram — 텔레그램 아침 브리핑 발송·설정

수집·정제된 뉴스 DB에서 카테고리별 톱 헤드라인 요약을 만들어 텔레그램으로 보내고, 사용자가 텔레그램 명령어로 구독을 제어하게 한다.

## 인증

`.env`에 두 값 필요:
- `TELEGRAM_BOT_TOKEN` — @BotFather 발급 토큰
- `TELEGRAM_CHAT_ID` — 받을 사람의 chat id (개인/그룹)

chat_id 확인: 봇에게 아무 메시지나 보낸 뒤
`https://api.telegram.org/bot<TOKEN>/getUpdates` 열면 `chat.id`가 보인다.

## 구성 요소 (stdlib 전용, 무의존)

| 스크립트 | 역할 |
|----------|------|
| `tg_common.py` | 공용 헬퍼: 토큰 로드, config, DB 조회, 다이제스트 텍스트(HTML) 생성 |
| `send_digest.py` | 1회 발송. `--collect`면 발송 전 API 수집·적재까지(헤드리스 자동화) |
| `telegram_bot.py` | 상주 봇: 명령어 수신 + 매일 지정 시각 자동 발송 |

설정 파일: `config/telegram.json` (enabled, send_time, days, min_score, top_n, categories 8종 on/off).

## 봇 실행 (명령어 설정을 쓰려면 상주 필요)

```bash
python .claude/skills/news-telegram/scripts/telegram_bot.py
```

봇이 롱폴로 명령어를 받고, 1분 간격으로 스케줄을 확인해 `send_time`에 자동 발송한다. 발송 시각에는 API 수집→적재→발송을 자동 수행한다(웹/크롤 보강은 대화형 실행에서).

**명령어:** `/status` `/time HH:MM` `/categories` `/on <키|all>` `/off <키>` `/minscore N` `/topn N` `/days N` `/now` `/collectnow` `/enable` `/disable`. 카테고리 키: policy market auction redevelopment subscription urban_plan industrial local.

## 수동/스케줄 발송

```bash
python .claude/skills/news-telegram/scripts/send_digest.py            # 지금 DB로 발송
python .claude/skills/news-telegram/scripts/send_digest.py --collect  # 수집 후 발송
```

**백업 스케줄(봇 없이):** 머신이 항상 켜져있지 않으면 Windows 작업 스케줄러/cron에 `send_digest.py --collect`를 아침 7시로 걸어 이중화한다. 봇 내부 스케줄러와 중복돼도 다이제스트가 두 번 갈 뿐 무해하나, 보통 둘 중 하나만 쓴다.

## 발송 내용 형식

카테고리별 톱 N 헤드라인: `스코어 · 제목(원문링크) · 🔗교차출처수 · 매체`. 구독 ON 카테고리만. 텔레그램 4096자 제한에 맞춰 트림.

## 왜 이렇게 하나

- **stdlib HTTP**: Telegram Bot API는 단순 HTTPS라 python-telegram-bot 같은 의존성 없이 urllib로 충분. 설치 마찰 제거.
- **봇=설정+스케줄 단일 프로세스**: 명령어 설정을 쓰려면 상주가 필요하므로, 같은 프로세스가 스케줄 발송까지 맡아 구성을 단순화.
- **지정 chat만 응답**: `TELEGRAM_CHAT_ID` 외 발신은 무시해 오남용 방지.
- **--collect 자동 수집**: 아침 발송이 "어제 밤 DB"가 아니라 그 시각 최신이 되도록 API 채널을 먼저 돌린다(무의존·빠름).

## 협업

curator가 적재한 `data/news.db`를 읽는다. 오케스트레이터가 수집 파이프라인 완료 후 발송을 트리거하거나, 봇이 독립적으로 아침 스케줄에 발송한다.

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""텔레그램 봇: 명령어로 구독 설정 + 매일 지정 시각 자동 다이제스트 발송.

실행(백그라운드 상주):
  python telegram_bot.py

명령어:
  /start /help        도움말
  /status             현재 설정 확인
  /time HH:MM         아침 발송 시각 설정 (예: /time 07:00)
  /categories         카테고리 on/off 목록
  /on <키|all>        카테고리 켜기 (키: policy market auction redevelopment subscription urban_plan industrial local)
  /off <키>           카테고리 끄기
  /minscore N         중요도 하한 (기본 45)
  /topn N             카테고리당 헤드라인 수 (기본 5)
  /days N             집계 기간 일수 (기본 1)
  /now                지금 즉시 발송(최신 DB 기준)
  /collectnow         지금 수집 후 발송
  /enable /disable    아침 자동발송 on/off

무의존(stdlib). getUpdates 롱폴 + 1분 간격 스케줄 체크. 머신이 켜져 있어야 발송된다.
백업으로 send_digest.py를 Windows 작업 스케줄러/cron에 걸어도 된다.
"""
import subprocess, sys, time, os
from datetime import datetime
import tg_common as T

VALID = [c for c, _, _ in T.CATS]
HELP = (
    "🤖 <b>부동산 뉴스 봇</b>\n"
    "/status 설정확인\n/time HH:MM 발송시각\n/categories 카테고리목록\n"
    "/watchlist 관심 워치리스트\n"
    "/on &lt;키|all&gt; · /off &lt;키&gt;\n/minscore N · /topn N · /days N\n"
    "/now 지금발송 · /collectnow 수집후발송\n/enable · /disable 자동발송\n"
    f"키: {' '.join(VALID)}"
)


def status_text(cfg):
    cats = cfg.get("categories", {})
    on = [T.CAT_LABEL[c] for c in VALID if cats.get(c, True)]
    off = [T.CAT_LABEL[c] for c in VALID if not cats.get(c, True)]
    return (
        f"⚙️ <b>현재 설정</b>\n"
        f"자동발송: {'✅ ON' if cfg.get('enabled') else '⛔ OFF'}\n"
        f"발송시각: <b>{cfg.get('send_time')}</b> (KST)\n"
        f"기간: 최근 {cfg.get('days',1)}일 · 스코어 {cfg.get('min_score',45)}+ · 카테고리당 {cfg.get('top_n',5)}건\n"
        f"구독 ON: {', '.join(on) or '없음'}\n"
        f"구독 OFF: {', '.join(off) or '없음'}"
    )


def watchlist_text():
    import os, json
    p = os.path.join(T.project_root(), "config", "watchlist.json")
    if not os.path.isfile(p):
        return "워치리스트 없음 (config/watchlist.json)"
    wl = json.load(open(p, encoding="utf-8"))
    lines = ["⭐ <b>관심 워치리스트</b>", "", "<b>수집 키워드</b>"]
    lines.append("  " + ", ".join(wl.get("keywords", [])) or "  (없음)")
    lines.append("")
    lines.append("<b>관심 물건</b> (매칭 시 즉시 알림)")
    for pr in wl.get("properties", []):
        lines.append(f"  📍 {pr.get('name')} — {', '.join(pr.get('region', []))}")
    lines.append("")
    lines.append("편집: config/watchlist.json 수정 후 다음 수집부터 반영")
    return "\n".join(lines)


def categories_text(cfg):
    cats = cfg.get("categories", {})
    lines = ["📂 <b>카테고리</b> (/on /off 로 변경)"]
    for c, label, emoji in T.CATS:
        lines.append(f"{emoji} {'✅' if cats.get(c, True) else '⬜'} <code>{c}</code> {label}")
    return "\n".join(lines)


def collect_and_send(token, chat, collect=False):
    root = T.project_root()
    if collect:
        T.send_message(token, chat, "🔄 수집 중…")
        cmd = [sys.executable, os.path.join(root, ".claude/skills/news-telegram/scripts/send_digest.py"), "--collect"]
    else:
        cmd = [sys.executable, os.path.join(root, ".claude/skills/news-telegram/scripts/send_digest.py")]
    subprocess.run(cmd)


def handle(token, chat, cmd, arg, cfg):
    c = cmd.lower()
    if c in ("/start", "/help"):
        return HELP, False
    if c == "/status":
        return status_text(cfg), False
    if c == "/categories":
        return categories_text(cfg), False
    if c == "/watchlist":
        return watchlist_text(), False
    if c == "/time":
        try:
            hh, mm = arg.split(":"); hh, mm = int(hh), int(mm)
            assert 0 <= hh < 24 and 0 <= mm < 60
            cfg["send_time"] = f"{hh:02d}:{mm:02d}"
            return f"✅ 발송시각 <b>{cfg['send_time']}</b> (KST) 설정", True
        except Exception:
            return "형식 오류. 예: <code>/time 07:00</code>", False
    if c == "/on":
        key = arg.strip().lower()
        if key == "all":
            cfg["categories"] = {k: True for k in VALID}
            return "✅ 전체 카테고리 ON", True
        if key in VALID:
            cfg.setdefault("categories", {})[key] = True
            return f"✅ {T.CAT_LABEL[key]} ON", True
        return f"알 수 없는 키. {' '.join(VALID)}", False
    if c == "/off":
        key = arg.strip().lower()
        if key in VALID:
            cfg.setdefault("categories", {})[key] = False
            return f"⬜ {T.CAT_LABEL[key]} OFF", True
        return f"알 수 없는 키. {' '.join(VALID)}", False
    if c in ("/minscore", "/topn", "/days"):
        try:
            n = int(arg)
            k = {"/minscore": "min_score", "/topn": "top_n", "/days": "days"}[c]
            cfg[k] = n
            return f"✅ {k} = {n}", True
        except Exception:
            return f"숫자를 입력하세요. 예: <code>{c} 3</code>", False
    if c == "/enable":
        cfg["enabled"] = True; return "✅ 아침 자동발송 ON", True
    if c == "/disable":
        cfg["enabled"] = False; return "⛔ 아침 자동발송 OFF", True
    if c == "/now":
        return "__SEND__", False
    if c == "/collectnow":
        return "__COLLECT__", False
    return None, False


def main():
    token, chat = T.creds()
    if not token or not chat:
        sys.stderr.write("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정 (.env)\n")
        sys.exit(2)
    # 시작 알림 + 명령어 등록
    try:
        T.api(token, "setMyCommands", {"commands": __import__("json").dumps([
            {"command": "status", "description": "설정 확인"},
            {"command": "time", "description": "발송시각 HH:MM"},
            {"command": "categories", "description": "카테고리 목록"},
            {"command": "on", "description": "카테고리 켜기"},
            {"command": "off", "description": "카테고리 끄기"},
            {"command": "now", "description": "지금 발송"},
            {"command": "collectnow", "description": "수집 후 발송"},
            {"command": "help", "description": "도움말"},
        ], ensure_ascii=False)})
    except Exception as e:
        sys.stderr.write(f"setMyCommands warn: {e}\n")
    T.send_message(token, chat, "🤖 뉴스 봇 시작됨. /help 로 명령어 확인.")

    # 시작 시 폴 슬롯 선점(직전 인스턴스의 잔여 롱폴을 밀어내고 대기분 flush)
    offset = None
    for _ in range(6):
        try:
            r = T.api(token, "getUpdates", {"timeout": 1, "offset": -1}, timeout=10)
            ups = r.get("result", [])
            if ups:
                offset = ups[-1]["update_id"] + 1
            break
        except Exception:
            time.sleep(3)  # 잔여 롱폴 만료 대기 후 재시도

    last_sent_date = None
    sys.stderr.write("bot polling…\n")
    while True:
        try:
            params = {"timeout": 20}
            if offset is not None:
                params["offset"] = offset
            res = T.api(token, "getUpdates", params, timeout=30)
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("channel_post")
                if not msg or "text" not in msg:
                    continue
                frm = str(msg["chat"]["id"])
                if frm != str(chat):
                    continue  # 지정 chat만 응답
                parts = msg["text"].strip().split(maxsplit=1)
                cmd = parts[0].split("@")[0]
                arg = parts[1] if len(parts) > 1 else ""
                cfg = T.load_config()
                reply, save = handle(token, chat, cmd, arg, cfg)
                if reply == "__SEND__":
                    collect_and_send(token, chat, collect=False)
                elif reply == "__COLLECT__":
                    collect_and_send(token, chat, collect=True)
                elif reply:
                    if save:
                        T.save_config(cfg)
                    T.send_message(token, chat, reply)
            # 스케줄 체크 (BOT_NO_SCHEDULE=1이면 발송은 작업 스케줄러가 담당 → 봇은 명령만)
            cfg = T.load_config()
            if cfg.get("enabled") and not os.environ.get("BOT_NO_SCHEDULE"):
                now = datetime.now(T.KST)
                today = now.strftime("%Y-%m-%d")
                if now.strftime("%H:%M") >= cfg.get("send_time", "07:00") and last_sent_date != today:
                    # 발송시각 이후 첫 루프에 1회 발송
                    if now.strftime("%H:%M") <= _plus_min(cfg.get("send_time", "07:00"), 5):
                        collect_and_send(token, chat, collect=True)
                        last_sent_date = today
                    elif last_sent_date is None:
                        # 봇이 발송시각 한참 뒤에 켜졌으면 오늘 건 스킵(중복 방지)
                        last_sent_date = today
        except Exception as e:
            sys.stderr.write(f"loop error: {e}\n")
            time.sleep(5)


def _plus_min(hhmm, m):
    h, mm = map(int, hhmm.split(":"))
    tot = h * 60 + mm + m
    return f"{(tot // 60) % 24:02d}:{tot % 60:02d}"


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사업 단계 이벤트 알림 (신통기획 확정 등). 다이제스트와 별개의 즉시 알림 경로.

관심물건 알림(watch_alert.py)이 "내 물건 지역에 뉴스가 떴다"를 알린다면, 이쪽은
"정비사업이 특정 단계에 도달했다"를 알린다. 규칙은 config/watchlist.json의
`event_alerts`에 둔다 — 코드를 안 고치고 단계·패턴을 바꿀 수 있다.

**사업 단위로 한 번만 울린다.** 확정 하나에 언론 6곳이 쓰고 서울시가 [기획완료]·
[서북권]·[기록영상]으로 3건을 더 올리므로, 기사 단위로 알리면 한 사건에 9번 울린다.
제목에서 사업 키(홍제동 9-81, 가락삼익맨숀 …)를 뽑아 묶고, 이미 알린 키는 건너뛴다.

발송 상태는 alerts 테이블에 property_id=`evt:{규칙id}`, article_id=`key:{사업키}`로
남긴다. watch_alert.py는 articles와 INNER JOIN하므로 이 합성 행을 보지 않는다.

사용:
  python event_alert.py --dry-run   # 발송 없이 대상만 출력
  python event_alert.py             # 새 이벤트만 발송
  python event_alert.py --replay    # 이미 알린 것도 다시 출력(점검용, 발송 안 함)
"""
import argparse, json, os, re, sqlite3, sys
from datetime import datetime, timedelta, timezone
import tg_common as T

# 제목에서 사업을 특정하는 토큰. 앞쪽(더 구체적인 것)부터 시도한다.
KEY_PATTERNS = [
    r"[가-힣]+동\s*\d+[\d\-·]*",                     # 홍제동 9-81, 망원동 416-53
    r"[가-힣A-Za-z0-9·]+\s*\d*\s*구역",               # 한남3구역, 천호10구역
    r"[가-힣A-Za-z0-9·]+(?:아파트|맨숀|맨션|빌라트|타운)",  # 가락삼익맨숀
    r"[가-힣]+\s*주공\s*\d*단지",                      # 상계주공6단지
    r"[가-힣A-Za-z0-9·]+\s*\d*단지",                   # 목동4단지
    r"[가-힣]+(?:마을|뉴타운|지구)",                     # 개미마을, 광명뉴타운
]


DONG = re.compile(r"[가-힣]{2,4}동(?=\s|\d|$|[·,])")


def project_key(title):
    """(묶음키, 표시명). 못 찾으면 (None, None).

    묶음은 **동(洞) 단위**로 한다. 같은 확정 건을 매체마다 '홍제동 9-81'·'개미마을'·
    '문화마을'로 달리 불러서, 구역명으로 묶으면 한 사건이 3개로 쪼개진다. 동이 없는
    제목(가락삼익맨숀 등)은 구역·단지명을 그대로 묶음키로 쓴다.
    """
    spec = None
    for pat in KEY_PATTERNS:
        m = re.search(pat, title)
        if m:
            spec = re.sub(r"\s+", "", m.group(0))
            break
    d = DONG.search(title)
    if d:
        return d.group(0), (spec or d.group(0))
    return (spec, spec) if spec else (None, None)


def load_rules():
    p = os.path.join(T.project_root(), "config", "watchlist.json")
    try:
        return json.load(open(p, encoding="utf-8")).get("event_alerts", [])
    except Exception as e:
        sys.stderr.write(f"WARN: watchlist.json 읽기 실패({e}) → 이벤트 알림 건너뜀\n")
        return []


def matches(rule, title, desc):
    hay = f"{title} {desc}"
    if not any(p in hay for p in rule.get("patterns", [])):
        return False
    return not any(x in hay for x in rule.get("exclude", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replay", action="store_true", help="이미 알린 건도 출력(발송 안 함)")
    args = ap.parse_args()

    rules = load_rules()
    if not rules:
        sys.stderr.write("INFO: event_alerts 규칙 없음\n")
        return

    con = sqlite3.connect(T.db_path())
    con.row_factory = sqlite3.Row
    token = chat = None
    if not (args.dry_run or args.replay):
        token, chat = T.creds()
        if not token or not chat:
            sys.stderr.write("ERROR: 텔레그램 키 미설정 (.env)\n"); sys.exit(2)

    now = datetime.now(timezone.utc)
    total_sent = 0
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        rid, name = rule["id"], rule.get("name", rule["id"])
        since = (now - timedelta(days=int(rule.get("days", 3)))).isoformat()
        rows = con.execute(
            "SELECT id,title,description,url,naver_url,source,score,substr(pub_date,1,10) d "
            "FROM articles WHERE (pub_date>=? OR pub_date='') AND score>=? "
            "ORDER BY score DESC, pub_date DESC",
            (since, float(rule.get("min_score", 45)))).fetchall()

        groups = {}
        for r in rows:
            if not matches(rule, r["title"], r["description"] or ""):
                continue
            key, label = project_key(r["title"])
            if not key:
                key = label = re.sub(r"\W+", "", r["title"])[:20]
            g = groups.setdefault(key, {"items": [], "labels": []})
            g["items"].append(r)
            g["labels"].append(label)

        new_keys = []
        for key, g in groups.items():
            items = g["items"]
            # 표시명은 그 묶음에서 가장 구체적인 이름(가장 긴 것)을 쓴다
            label = max(g["labels"], key=len)
            state = ("evt:" + rid, "key:" + key)
            seen = con.execute(
                "SELECT 1 FROM alerts WHERE property_id=? AND article_id=?", state).fetchone()
            if seen and not args.replay:
                continue
            new_keys.append((label, items, state))

        if not new_keys:
            sys.stderr.write(f"INFO: [{name}] 새 이벤트 없음 (후보 {len(groups)}개 사업)\n")
            continue

        for key, items, state in new_keys:
            head = items[0]
            lines = [f"{rule.get('emoji','📌')} <b>{T.esc(name)}</b>",
                     f"📍 <b>{T.esc(key)}</b> · {head['d']}", ""]
            for r in items[:4]:
                link = r["url"] or r["naver_url"] or ""
                t = T.esc(r["title"][:70])
                lines.append(f"  <b>{r['score']:.0f}</b> " +
                             (f'<a href="{T.esc(link)}">{t}</a>' if link else t))
                lines.append(f"     <i>{T.esc(r['source'])}</i>")
            if len(items) > 4:
                lines.append(f"  …외 {len(items)-4}건")
            text = "\n".join(lines)

            if args.dry_run or args.replay:
                print(f"[{'REPLAY' if args.replay else 'DRY'}] {name} · {key} ({len(items)}건) {head['title'][:44]}")
                continue
            res = T.send_message(token, chat, text)
            if res.get("ok"):
                con.execute(
                    "INSERT OR IGNORE INTO alerts (property_id,property_name,article_id,matched_term,created_at,notified) "
                    "VALUES (?,?,?,?,?,1)",
                    (state[0], name, state[1], key, now.isoformat()))
                total_sent += 1
            else:
                sys.stderr.write(f"발송 실패({name}/{key}): {res}\n")
        con.commit()

    mode = "DRY-RUN" if args.dry_run else ("REPLAY" if args.replay else "OK")
    sys.stderr.write(f"{mode}: 이벤트 알림 {total_sent}건 발송\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""관심물건↔뉴스 매칭 알림 발송. alerts 테이블에서 미발송(notified=0)을 텔레그램으로 보내고 표시.

아침 다이제스트와 별개의 '즉시 알림' 경로. ingest가 관심물건 매칭을 alerts에 적재해두면
이 스크립트가 새 매칭만 골라 발송한다(중복 없음).

사용:
  python watch_alert.py            # 미발송 알림 전송
  python watch_alert.py --dry-run  # 발송 없이 대상만 출력
"""
import argparse, json, sqlite3, sys
from datetime import datetime
import tg_common as T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-score", type=float, default=40, help="이 스코어 이상 매칭만 알림(노이즈 억제)")
    args = ap.parse_args()

    con = sqlite3.connect(T.db_path())
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT a.id aid, a.property_id, a.property_name, a.matched_term,
               ar.title, ar.url, ar.naver_url, ar.source, ar.score, ar.category
        FROM alerts a JOIN articles ar ON ar.id = a.article_id
        WHERE a.notified = 0 AND ar.score >= ?
        ORDER BY ar.score DESC
    """, (args.min_score,)).fetchall()

    if not rows:
        sys.stderr.write("미발송 관심물건 알림 없음\n")
        return

    token, chat = (None, None)
    if not args.dry_run:
        token, chat = T.creds()
        if not token or not chat:
            sys.stderr.write("ERROR: 텔레그램 키 미설정 (.env)\n"); sys.exit(2)

    # 물건별로 묶어 발송
    from collections import defaultdict
    by_prop = defaultdict(list)
    for r in rows:
        by_prop[(r["property_id"], r["property_name"])].append(r)

    sent = 0
    for (pid, pname), items in by_prop.items():
        lines = [f"🚨 <b>관심물건 뉴스 알림</b>", f"📍 <b>{T.esc(pname)}</b>", ""]
        for r in items:
            link = r["url"] or r["naver_url"] or ""
            t = T.esc(r["title"][:70])
            cat = T.CAT_LABEL.get(r["category"], r["category"])
            title_html = f'<a href="{T.esc(link)}">{t}</a>' if link else t
            lines.append(f"  <b>{r['score']:.0f}</b> {title_html}")
            lines.append(f"     <i>{T.esc(r['source'])}</i> · {T.esc(cat)} · 🔑{T.esc(r['matched_term'])}")
        text = "\n".join(lines)
        if len(text.encode()) > 4000:
            text = text[:1300] + "\n…(생략)"
        if args.dry_run:
            print(f"[DRY] {pname}: {len(items)}건")
        else:
            res = T.send_message(token, chat, text)
            if res.get("ok"):
                for r in items:
                    con.execute("UPDATE alerts SET notified=1 WHERE id=?", (r["aid"],))
                sent += len(items)
            else:
                sys.stderr.write(f"발송 실패({pname}): {res}\n")
    con.commit()
    sys.stderr.write(f"{'DRY-RUN' if args.dry_run else 'OK'}: 관심물건 알림 {sent}건 발송 ({len(by_prop)}개 물건)\n")


if __name__ == "__main__":
    main()

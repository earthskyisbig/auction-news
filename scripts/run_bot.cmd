@echo off
REM 텔레그램 명령봇 상주 기동 (로그온 트리거용). 발송은 작업 스케줄러가 담당하므로 봇 내부 스케줄러는 끔.
cd /d "C:\Users\m9938\auction-news"
set BOT_NO_SCHEDULE=1
"C:\Python313\pythonw.exe" ".claude\skills\news-telegram\scripts\telegram_bot.py"

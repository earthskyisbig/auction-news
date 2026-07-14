@echo off
REM 아침 뉴스 다이제스트 발송 (수집→적재→다이제스트+관심물건 알림). 작업 스케줄러 07:00 트리거용.
cd /d "C:\Users\m9938\auction-news"
"C:\Python313\pythonw.exe" ".claude\skills\news-telegram\scripts\send_digest.py" --collect

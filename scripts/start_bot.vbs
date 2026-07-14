' 텔레그램 명령봇을 콘솔 창 없이 숨김 실행 (로그온 시작프로그램용).
' 발송은 작업 스케줄러(AuctionNews-MorningDigest)가 담당 → 봇 내부 스케줄러는 끔.
Set sh = CreateObject("WScript.Shell")
sh.Environment("Process").Item("BOT_NO_SCHEDULE") = "1"
sh.CurrentDirectory = "C:\Users\m9938\auction-news\.claude\skills\news-telegram\scripts"
sh.Run """C:\Python313\pythonw.exe"" ""telegram_bot.py""", 0, False

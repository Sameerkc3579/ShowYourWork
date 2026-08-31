@echo off
set FASTMCP_QUIET=1
set PYTHONUTF8=1
cd /d "C:\Users\sameer choudhary\OneDrive\Desktop\ShowYourWork"
"C:\Users\sameer choudhary\AppData\Local\Programs\Python\Python310\Scripts\uv.exe" run --quiet python main.py gateway 2> claude_error.log

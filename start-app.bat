@echo off
REM Starts the HCCS chatbot app (uvicorn) for the live rollout.
REM Double-click this, or drop a shortcut to it in shell:startup so it
REM auto-starts after a reboot. Leave the window open — closing it stops the app.

cd /d "C:\College Life\3Y - 3S\SIA2\3.3-dashboard\hccs_rag_chatbot"
call "C:\College Life\3Y - 3S\SIA2\3.3-dashboard\venv\Scripts\activate.bat"
REM Bind to loopback only: the Cloudflare tunnel (cloudflared) reaches the app
REM locally, so nothing else needs LAN access. This also stops a LAN client from
REM hitting uvicorn directly and spoofing the CF-Connecting-IP header to dodge
REM the per-guest rate limits.
uvicorn main:app --host 127.0.0.1 --port 8000

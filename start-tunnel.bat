@echo off
REM Starts the Cloudflare tunnel that forwards https://hochichat.cc to the app.
REM Leave the window open — closing it takes the site offline.

cloudflared tunnel run hochi-chatbot

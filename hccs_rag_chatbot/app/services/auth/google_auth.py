from urllib.parse import urlencode

import httpx
from app.core.config import settings

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

def get_google_auth_url(state: str | None = None) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        # NOTE: we intentionally do NOT send `hd` (hosted-domain). `hd` restricts
        # Google's account chooser to one domain, which would hide the developer/
        # owner accounts allowlisted via BOOTSTRAP_ADMIN_EMAILS (usually personal
        # Gmail) — they'd never even appear to sign in. Who may actually sign in is
        # enforced server-side in the callback, so the chooser can list every
        # account safely.
        # Always present the account chooser instead of silently reusing an
        # existing Google session. On a shared computer this stops one student
        # being auto-logged-in as whoever used the browser before, and makes the
        # "Switch Account" button actually offer a choice.
        "prompt": "select_account",
    }
    # CSRF guard: Google echoes `state` back to the callback, which verifies it.
    if state:
        params["state"] = state
    # urlencode so values with ':' and '/' (e.g. the https redirect_uri behind
    # the tunnel) are percent-encoded — Google rejects a raw, unencoded URI.
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

async def exchange_code_for_token(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        return response.json()

async def get_google_user_info(access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        return response.json()
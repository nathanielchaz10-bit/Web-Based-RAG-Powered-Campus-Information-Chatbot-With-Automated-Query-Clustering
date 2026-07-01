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
        # Show only the school domain in Google's account chooser. This is a UX
        # nudge, NOT a security control — `hd` can be omitted/altered by the
        # client, so the callback still verifies the email domain server-side.
        "hd": settings.HCCS_DOMAIN,
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
# Deploying the HCCS Chatbot for the student rollout

This guide takes the app from "works on my machine in dev mode" to "students can
use it safely over a shared link for a week." Read it top to bottom the first
time.

The model: the app runs **on your machine**, and a **Cloudflare Tunnel** gives
students a public **HTTPS** link that forwards to it. No server to rent. Your
machine must stay on and running the app for the whole week — it *is* the server.

> **What this does and doesn't secure.** Hardening below locks down the *running
> app* (who can log in, who reaches admin pages, how much the API is used). It
> does **not** expose your source code — a tunnel only forwards the one app port
> (8000), not your files. Keep `.env` out of git (it already is) and only tunnel
> port 8000.

---

## Step 1 — Generate a strong JWT secret

With the default signing key, anyone can forge an admin token. Generate a real one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the output; you'll paste it into `.env` next.

---

## Step 2 — Configure `.env` for deployment

Your `.env` lives at the **repo root**. Set these for the live run (see
`.env.example` for the full annotated list):

```ini
# Turn OFF dev mode — THIS is the most important line. While on, anyone with no
# token is treated as Head Admin and the domain restriction is relaxed.
DEV_MODE=False

# The secret from Step 1 (the app refuses to start with the default when DEV_MODE=False).
JWT_SECRET_KEY=<paste the generated secret>

# Your real Gemini + Google credentials.
GEMINI_API_KEY=<your key>
GOOGLE_CLIENT_ID=<your client id>
GOOGLE_CLIENT_SECRET=<your client secret>

# School domain stays enforced (students use @hccs.edu.ph Workspace accounts).
HCCS_DOMAIN=hccs.edu.ph

# YOUR admin access: comma-separated emails that become Head Admin on Google
# sign-in and may log in even off the school domain. On a fresh deployment this is
# the ONLY way a Head Admin exists — set at least your own email here.
BOOTSTRAP_ADMIN_EMAILS=you@gmail.com,teammate@gmail.com

# Set AFTER Step 4, when you know your tunnel URL. Must match Google exactly.
GOOGLE_REDIRECT_URI=https://<your-tunnel-host>/api/auth/callback
CORS_ALLOW_ORIGINS=https://<your-tunnel-host>

# Budget protection for the ~$10 key (tune to taste).
RATE_LIMIT_USER_DAILY_MAX=20      # questions per student per day
RATE_LIMIT_GLOBAL_DAILY_MAX=300   # questions per day across everyone
CHAT_ENABLED=True                 # master on/off (also in Portal Settings)
```

### Sizing the daily cap to your budget

Gemini 2.5 Flash is ~$0.003–0.005 per chat turn, so **~$10 ≈ 2,000–3,300 turns
total**. Over 7 days that's **~300–450/day**. `RATE_LIMIT_GLOBAL_DAILY_MAX=300`
keeps a week under budget with headroom. If you have hundreds of students, expect
to hit the daily cap (the bot will say "try again tomorrow") — that is the cap
doing its job. To stretch further, lower `RATE_LIMIT_USER_DAILY_MAX`. Google's
billing is the hard backstop; the app handles a depleted key gracefully.

---

## Step 3 — Google Cloud Console (one-time)

This project uses an **External** OAuth app (created under a personal Google
account — Internal isn't available unless the project is owned by the school's
Workspace org). External is fine: Google lets any account *reach* the sign-in
screen, but the app **only admits verified `@hccs.edu.ph` emails** — it rejects
everything else server-side in the login callback (when `DEV_MODE=False`). So the
school-only rule is enforced by the app, not by Google.

Sign in to <https://console.cloud.google.com/> with the account that owns the
OAuth client, then:

1. **OAuth consent screen** (newer UI: **Google Auth Platform → Audience**)
   - It will be **External**. Set **Publishing status → Publish app** so it's
     **In production** — this removes the ~100 test-user cap and the "unverified
     app" warning. **No Google verification is required**, because the app only
     uses the non-sensitive `openid / email / profile` scopes.
   - (Staying in *Testing* instead caps you at ~100 manually-added test users —
     only OK for a small pilot, not a whole-school week.)
2. **Credentials → your OAuth 2.0 Client ID** (newer UI: **Google Auth Platform → Clients**)
   - **Authorized redirect URIs** → add: `https://<your-tunnel-host>/api/auth/callback`
   - **Authorized JavaScript origins** → add: `https://<your-tunnel-host>`
   - (Keep the `http://localhost:8000/...` entries too, so local dev still works.)
   - Save. Changes can take a few minutes to propagate.

You'll get `<your-tunnel-host>` from Step 4.

> **Why `DEV_MODE=False` is critical here:** with an External app, that domain
> check is the *only* thing keeping outside accounts out. If `DEV_MODE` were left
> on, the check is skipped and **any** Google account could log in (as Head
> Admin). The app's startup guardrail refuses to boot insecurely, but double-check
> the banner doesn't appear. The Google account chooser lists all of a user's
> accounts (we don't send the `hd` domain hint, so allowlisted developer Gmail
> accounts can sign in) — the server-side check enforces school-only access for
> everyone else.

---

## Step 4 — Cloudflare Tunnel

Install:

```bash
winget install --id Cloudflare.cloudflared
```

### Which kind of tunnel?

- **Permanent URL (recommended if you have a domain on Cloudflare):** a *named
  tunnel* gives a fixed custom hostname you configure in Google once. Follow
  Cloudflare's "Create a tunnel" docs (needs a free Cloudflare account + a domain
  added to it).
- **No domain? Use a quick tunnel.** Zero setup, but the URL is random **per
  run**:

  ```bash
  cloudflared tunnel --url http://localhost:8000
  ```

  It prints a `https://<random>.trycloudflare.com` URL. **That URL stays fixed as
  long as you don't stop `cloudflared`.** So for a week-long run: start it once,
  put that URL into `.env` (Step 2) and Google (Step 3), and **leave it running
  the whole week.** If it ever restarts you'll get a new URL and must update both
  places again.

> Only ever tunnel `http://localhost:8000`. Don't expose other ports.

---

## Step 5 — Start the app

From inside `hccs_rag_chatbot/`, with a **single worker** (the per-minute limiter
is per-process; the daily caps are DB-backed so they're fine regardless):

```bash
cd hccs_rag_chatbot
uvicorn main:app --host 0.0.0.0 --port 8000
```

On startup you should **not** see the `DEV_MODE IS ON` warning banner. If you do,
`DEV_MODE` is still `True` in `.env`. If it refuses to start complaining about the
JWT secret, finish Step 1/2.

Students use the **tunnel URL** (e.g. `https://<host>/` → redirects to the login
page). Do not give them `localhost`.

---

## Step 6 — Smoke test before sharing

Open the tunnel URL in a fresh/incognito window and verify:

- [ ] Login page loads; "Sign in with Google" works with an `@hccs.edu.ph` account.
- [ ] A non-`hccs.edu.ph` Google account is **rejected** ("Access denied").
- [ ] After login you land on the student chat and can ask a question.
- [ ] **Log out, then press the browser Back button** → you're bounced to login,
      not back into the chat.
- [ ] Visiting an admin URL (e.g. `/frontend/admin/dashboard.html`) while logged
      out (or as a student) redirects to login — it does **not** show admin data.
- [ ] Signing in with an email listed in `BOOTSTRAP_ADMIN_EMAILS` lands you in the
      admin portal as **Head Admin** (this is how you administer the live app).
- [ ] In Portal Settings, flip **Chatbot Availability** off → students immediately
      get "temporarily unavailable"; flip it back on.

---

## Operating during the week

- **Monitor:** the admin **Dashboard → System Health** shows *Daily Budget*
  (questions used today vs. the cap) and a *Chatbot Availability* badge.
- **Emergency stop:** **Portal Settings → Chatbot Availability → Disabled** (or
  set `CHAT_ENABLED=False`) pauses everything instantly, no restart.
- **Tune limits live:** Portal Settings changes apply on the next question.
- **Back to dev:** set `DEV_MODE=True` in `.env` and restart (re-enables the
  dev-login bypass for local testing). Never do this while the tunnel is public.

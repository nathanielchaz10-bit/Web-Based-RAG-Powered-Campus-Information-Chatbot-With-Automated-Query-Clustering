# Merge Summary — `test/merge/1244am`

**Goal:** Bring the new work from the fork (`groupmate-main2.1`) into the current
`semi-final` line — but only the parts that add value without breaking what
`semi-final` already does.

**Key context:** `groupmate-main2.1` branched off *before* `semi-final`'s big
update (the FastAPI app, the real RAG chat pipeline, and the LLM-based query
clustering). So the two branches had diverged a lot. A plain `git merge` would
have **overwritten newer, working code with older versions**. Instead we did a
*selective* integration: take the genuinely-new features, adapt them to
`semi-final`'s architecture, and skip anything that would regress it.

---

## ✅ What got integrated

### 1. NLP enrichment — sentiment & intent (the headline feature)
- Added two lightweight, local (no API cost) classifiers from the fork:
  - `sentiment.py` — VADER-based: tags each query **Positive / Inquisitive**,
    **Neutral / Transactional**, or **Urgent / Frustrated**.
  - `intent.py` — keyword rules: tags each query **Scholarship Info /
    Enrollment / Campus Directory / Payments / Academic Policy**.
- Wired both into the **real** chat pipeline so every student question is now
  classified and stored on its `query_logs` row (the `sentiment` /
  `detected_intent` columns existed but were never being filled).
- Made it safe: classification can never break a chat reply, and sentiment
  falls back gracefully if the dependency isn't installed.
- Added the dependency (`vaderSentiment`) to both requirements files.

### 2. Admin Settings page
- Added `settings.html` + `settings.js`. Every admin page already had a
  "Settings" link in the sidebar, but it **404'd** because the page didn't
  exist — this fixes that dead link.
- Enabled the admin login guard on it (the fork had it commented out).
- *Note:* it's currently a UI scaffold — the Save button isn't backed by an
  endpoint yet.

### 3. Dashboard sentiment/intent visualization
- The "Recent Inquiries" table now shows **color-coded intent pills** and
  **sentiment** (added the missing CSS colors and mapped the labels), so the
  data from feature #1 is actually visible.

### 4. Backend robustness
- SQLite now waits up to 15s for a write lock instead of immediately erroring
  with "database is locked."

### 5. Bug fix (found during testing)
- The admin dashboard was rendering **completely blank** due to a pre-existing
  crash (`renderSidebar` referenced a `#sidebar` element that doesn't exist,
  which aborted all data loading). Fixed — the dashboard now loads its cards,
  chart, and inquiries.

---

## ⏭️ What we intentionally did *not* merge (and why)

These weren't dropped because they were bad — `semi-final` had simply moved past
them:

- **`main.py`, `core/__init__.py`** — fork versions were older and would have
  re-introduced a database-engine bug `semi-final` already fixed.
- **`chat.py` (fork version)** — it was a placeholder that returned fake
  answers; `semi-final`'s is the real RAG pipeline. We kept the real one and
  added the NLP on top.
- **`auth.py` (fork version)** — `semi-final` already has the HCCS-domain
  restriction *plus* a dev-login for local testing.
- **Student chat page rewrite** — tightly coupled to the fork's placeholder chat
  backend; would have broken the working RAG chat.
- **IDE config (`.idea/`) and the binary `.db` overwrite** — not source code /
  risky.

---

## Files changed

**New**
- `hccs_rag_chatbot/app/services/nlp/intent.py`
- `hccs_rag_chatbot/app/services/nlp/sentiment.py`
- `hccs_rag_chatbot/app/services/nlp/__init__.py`
- `hccs_rag_chatbot/frontend/admin/settings.html`
- `hccs_rag_chatbot/frontend/js/admin/settings.js`

**Modified**
- `hccs_rag_chatbot/app/api/chat.py`
- `hccs_rag_chatbot/app/core/database.py`
- `hccs_rag_chatbot/frontend/js/admin/dashboard.js`
- `hccs_rag_chatbot/frontend/css/admin.css`
- `requirements.txt`
- `requirements-min.txt`

---

## How to verify

1. `git checkout test/merge/1244am`, install deps
   (`pip install -r requirements-min.txt`), set `GEMINI_API_KEY` and
   `DEV_MODE=True` in `.env`.
2. Run `uvicorn main:app --reload` from inside `hccs_rag_chatbot/`.
3. Open http://localhost:8000/ → dev-login as **Student** → ask a few questions
   → dev-login as **Head Admin** → **Dashboard** → see classified, color-coded
   inquiries. Open **Settings** → it loads.

Quick offline check of just the classifiers (no API key needed), from
`hccs_rag_chatbot/` with the venv active:

```bash
python -c "from app.services.nlp.sentiment import classify_sentiment; from app.services.nlp.intent import classify_intent; print(classify_sentiment('urgent deadline today!'), '|', classify_intent('how do I pay tuition'))"
# -> Urgent / Frustrated | Payments
```

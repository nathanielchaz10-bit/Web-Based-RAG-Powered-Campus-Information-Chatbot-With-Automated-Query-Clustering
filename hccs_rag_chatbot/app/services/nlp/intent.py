# app/services/nlp/intent.py
"""
Rule-based intent classification for student queries.

Assigns each query a high-level topic label by matching it against a curated,
per-category keyword/phrase lexicon. This is deliberately a lightweight,
zero-API-cost classifier (no ML model, no network call) so it can run inline on
the chat hot path without adding latency or cost — the same design rationale as
the VADER-based sentiment classifier in this package.

How a label is chosen (see classify_intent):
  1. The query is normalized (lowercased, punctuation stripped — see _normalize).
  2. Each category is *scored* by how many of its keyword phrases appear in the
     query as whole words/phrases (word-boundary matching, not raw substring —
     so "fee" no longer matches inside "coffee", and "transfer" no longer fires
     on unrelated tokens).
  3. The highest-scoring category wins. Scoring — rather than first-keyword-wins —
     means a query that touches two topics is routed to the one it mentions
     *most*, and the more specific category naturally wins because it accrues
     more keyword hits (e.g. "is there free tuition for scholars?" scores
     Scholarship on both "free tuition" and "scholars" but Payments only on
     "tuition").
  4. Ties are broken by _CATEGORY_ORDER (earlier = higher priority).
  5. A query that matches *nothing* falls back to General Inquiry — an honest
     "uncategorized" bucket — instead of being force-labeled into a real topic.

Labels must match dashboard.js intentClass(); General Inquiry has no explicit
color there and renders with the neutral "intent-grey" default.
"""

import re

# The fixed intent categories — labels must match dashboard.js intentClass().
INTENT_SCHOLARSHIP = "Scholarship Info"
INTENT_ENROLLMENT = "Enrollment"
INTENT_DIRECTORY = "Campus Directory"
INTENT_PAYMENTS = "Payments"
INTENT_PORTAL = "Portal & Accounts"
INTENT_DOCUMENTS = "Documents & Records"
INTENT_WELFARE = "Student Welfare"
INTENT_SCHEDULE = "Schedule & Events"
INTENT_FACILITIES = "Facilities & Services"
INTENT_ACADEMIC_POLICY = "Academic Policy"

# Catch-all for queries that match no category's keywords. This is intentionally
# NOT one of the real topics: previously the default was Academic Policy, which
# quietly mislabeled every off-topic / unrecognized query ("is there a varsity
# team?", "can I bring my laptop?") as a policy question and inflated that
# bucket. General Inquiry keeps the unmatched tail honest.
INTENT_GENERAL = "General Inquiry"

DEFAULT_INTENT = INTENT_GENERAL

# Keyword/phrase lists per category. Lowercase, no punctuation assumed —
# matching is done against a normalized version of the query text, with each
# phrase matched on word boundaries (see _compile_category).
#
# Because matching is word-boundary based, a short keyword no longer catches its
# own longer inflections (e.g. "enroll" will NOT match "enrollment"), so each
# surface form a student is likely to type is listed explicitly below.

_KEYWORDS = {
    INTENT_SCHOLARSHIP: [
        "scholarship", "scholarships", "scholar", "scholars", "gwa",
        "general weighted average", "grade requirement",
        "academic scholar", "grant", "financial assistance", "discount",
        "iskolar", "iskolarship", "merit", "deans lister", "dean lister",
        "latin honor", "academic excellence award", "free tuition",
        "maintain scholarship", "renew scholarship", "scholarship slot",
        "scholarship requirements", "qualify for scholarship",
        # Academic recognition / honors (there is no separate Honors bucket)
        "honor", "honors", "honor roll", "honor student", "with honors",
        "with high honors", "highest honors", "honor ranking",
    ],
    INTENT_ENROLLMENT: [
        "enroll", "enrolls", "enrolled", "enrolling", "enrollment",
        "enrolment", "mag-enroll", "mag enroll", "magpapaenroll",
        "registration", "register", "registering", "late enrollment",
        "schedule of enrollment", "enrollment period", "enrollment dates",
        "section", "sectioning", "class schedule", "load my subjects",
        "subject load", "units", "shift", "shifting", "shift course",
        "shift program", "lipat course", "transfer", "transferee",
        "transferring", "lipat school", "new student", "freshman",
        "freshmen", "old student", "returning student", "re-enroll",
        "re-enrollment", "irregular student", "cross enroll",
        "cross-enrollment", "requirements for enrollment",
        "entrance exam", "admission test", "reservation",
    ],
    INTENT_DIRECTORY: [
        "where is", "where can i find", "located", "location",
        "saan ang", "saan po ang", "office hours", "office", "clinic",
        "infirmary", "guidance office",
        "registrars office", "registrar office", "directory",
        "room number", "what room", "which room", "room assignment",
        "room assignments", "building", "faculty", "professors office",
        "professor office", "teachers office", "teacher office",
        "principals office", "principal office", "admissions office",
        "contact number", "phone number", "telephone number",
        "email address of", "school address", "campus map", "how to get to",
    ],
    INTENT_PAYMENTS: [
        "payment", "payments", "pay", "paying", "paid", "tuition",
        "tuition fee", "balance", "account balance", "cashier",
        "cashiers office", "billing", "billing statement", "invoice",
        "fee", "fees", "miscellaneous fee", "installment", "installment plan",
        "down payment", "downpayment", "reservation fee", "official receipt",
        "or number", "refund",
        "refund policy", "bayad", "magbayad", "babayaran", "utang",
        "promissory note", "assessment of fees", "statement of account",
        "soa", "payment deadline", "payment plan", "online payment",
        "gcash", "bank transfer",
    ],
    INTENT_PORTAL: [
        "portal", "student portal", "lms", "learning management system",
        "log in", "login", "log-in", "logging in", "sign in", "sign-in",
        "password", "reset password", "forgot password", "forgot my password",
        "change password", "my account", "account", "locked account",
        "locked out", "username", "online module", "online modules", "modules",
        "submit my activities", "submit activities", "e-learning", "e learning",
    ],
    INTENT_DOCUMENTS: [
        "transcript", "transcript of records", "tor", "form 137", "form 138",
        "good moral", "certificate", "certification",
        "certificate of enrollment", "certified true copy", "ctc", "diploma",
        "report card", "school records", "request a document",
        "request my documents", "documents", "credentials",
        "copy of my grades", "copy of grades",
    ],
    INTENT_WELFARE: [
        "guidance counselor", "counselor", "counseling", "counsel",
        "bully", "bullied", "bullying", "anti-bullying", "anti bullying",
        "mental health", "stressed", "stress", "anxiety", "depressed",
        "personal problem", "personal problems", "complaint",
        "file a complaint", "harassment", "harassed", "welfare",
        "emotional support", "talk to someone", "guidance appointment",
    ],
    INTENT_SCHEDULE: [
        "flag ceremony", "morning mass", "mass schedule", "holiday", "holidays",
        "no classes", "class suspension", "classes suspended", "suspended",
        "suspension", "typhoon", "storm", "bad weather", "walang pasok",
        "foundation day", "intramurals", "intrams", "field trip",
        "christmas break", "semestral break", "sem break", "summer break",
        "recognition day", "graduation ceremony", "school calendar",
        "academic calendar", "parent teacher conference", "pta meeting",
        "when do classes resume", "classes resume", "school event",
        "classes cancelled", "classes canceled", "class cancelled",
        "dismissal", "dismissal time", "classes start", "start of classes",
    ],
    INTENT_FACILITIES: [
        "library", "wifi", "wi-fi", "internet", "internet connection",
        "canteen", "cafeteria", "study area", "study areas", "study room",
        "lost and found", "borrow a book", "borrow books", "books", "book",
        "overdue", "library fine", "computer lab", "computers", "facility",
        "facilities", "comfort room", "parking", "locker",
    ],
    INTENT_ACADEMIC_POLICY: [
        "uniform", "uniforms", "dress code", "id lace", "pe uniform",
        "haircut", "colored hair", "hair color", "accessories",
        "drop a subject", "add or drop", "adding a subject",
        "wash day", "attendance", "absence", "absences", "absent",
        "excuse letter", "tardiness", "grading", "grading system",
        # NOTE: only the plural "grades" — bare "grade" would misfire on grade
        # LEVELS ("grade 7", "grade 12 students"), which are not policy questions.
        "grades", "passing grade", "failing grade",
        "incomplete grade", "retake",
        "policy", "policies", "handbook", "student handbook",
        "code of conduct", "discipline", "disciplinary action",
        "retention policy", "academic probation", "dropping a subject",
        "leave of absence", "graduation requirements",
    ],
}

# Tie-break order — only consulted when two categories score equally (same
# number of matched keywords). Narrower/less-ambiguous categories come first.
#
# Most of the classic collisions are now resolved by *scoring* rather than this
# order, because the more specific category accrues more keyword hits and wins
# outright. The order below is the safety net for genuine ties:
#   - "free tuition" (Scholarship) vs "tuition" (Payments): "is there free
#     tuition for scholars" scores Scholarship 2 (free tuition + scholars) vs
#     Payments 1 (tuition) — Scholarship wins on score, no tie.
#   - "account balance" (Payments) vs "account" (Portal): "what is my account
#     balance" scores Payments 2 (balance + account balance) vs Portal 1 —
#     Payments wins on score.
#   - "certificate of enrollment" (Documents) vs "enrollment" (Enrollment):
#     scores Documents 2 (certificate + certificate of enrollment) vs
#     Enrollment 1 — Documents wins on score.
#   - "refund policy" (Payments) vs "policy" (Academic Policy): scores Payments
#     2 vs Academic Policy 1 — Payments wins on score.
#   - "guidance counselor" (Welfare) vs "guidance office" (Directory): the two
#     don't share keywords ("guidance counselor" is Welfare, "guidance office"
#     is Directory), so each routes by its own match — no collision.
#   - "bank transfer" (Payments) vs "transfer" (Enrollment): word-boundary
#     matching means "transfer" still fires inside "bank transfer", but a
#     payment query also matches "paid"/"pay", so Payments outscores Enrollment.
# When two categories DO tie (e.g. a query mentioning exactly one keyword from
# each), this order decides the winner.
_CATEGORY_ORDER = [
    INTENT_SCHOLARSHIP,
    INTENT_PAYMENTS,
    INTENT_PORTAL,
    INTENT_DOCUMENTS,
    INTENT_WELFARE,
    INTENT_SCHEDULE,
    INTENT_ENROLLMENT,
    INTENT_DIRECTORY,
    INTENT_FACILITIES,
    INTENT_ACADEMIC_POLICY,
]


def _compile_category(phrases: list[str]) -> list["re.Pattern[str]"]:
    r"""Precompile each keyword phrase as a word-boundary regex.

    Matching on \b...\b (instead of plain substring containment) is what stops
    false positives like "fee" matching inside "coffee" or "or" matching inside
    "for". The phrases only ever contain [a-z0-9] and single spaces after
    normalization, so re.escape + \b is safe and unambiguous.
    """
    return [re.compile(r"\b" + re.escape(p) + r"\b") for p in phrases]


# category -> list of compiled phrase patterns. Built once at import time.
_COMPILED = {category: _compile_category(phrases) for category, phrases in _KEYWORDS.items()}


def classify_intent(query_text: str) -> str:
    """
    Classifies a student query into one of the fixed intent categories.

    Scores every category by how many of its keyword phrases the query contains
    (whole-word/phrase matches), then returns the highest-scoring category. Ties
    are broken by _CATEGORY_ORDER. A query that matches no keywords at all falls
    back to General Inquiry (DEFAULT_INTENT) rather than being forced into a real
    topic.

    Args:
        query_text: The raw text of the student's question.

    Returns:
        One of the INTENT_* category labels (Scholarship Info, Payments,
        Portal & Accounts, Documents & Records, Student Welfare,
        Schedule & Events, Enrollment, Campus Directory, Facilities & Services,
        Academic Policy), or INTENT_GENERAL ("General Inquiry") when nothing
        matches.
    """
    if not query_text or not query_text.strip():
        return DEFAULT_INTENT

    normalized = _normalize(query_text)

    best_category = None
    best_score = 0
    # Iterate in tie-break order so that, on equal scores, the first (highest
    # priority) category is the one retained by the strict-greater comparison.
    for category in _CATEGORY_ORDER:
        score = sum(1 for pattern in _COMPILED[category] if pattern.search(normalized))
        if score > best_score:
            best_score = score
            best_category = category

    return best_category if best_category is not None else DEFAULT_INTENT


def _normalize(text: str) -> str:
    """
    Lowercases and strips punctuation so phrase matching isn't broken by
    things like "GWA?" not matching "gwa", or "tuition," not matching
    "tuition" due to trailing punctuation.

    The possessive "'s" is collapsed (e.g. "library's" -> "library",
    "principal's" -> "principal") so a bare single-word keyword still matches
    under word-boundary matching — removing the apostrophe first would leave a
    dangling "s" ("librarys") and \blibrary\b would no longer match. The
    plural-possessive forms students type without an apostrophe ("deans lister",
    "cashiers office") are kept matchable by their own keyword entries.

    Any remaining apostrophes (contractions like "don't" -> "dont") are removed
    outright. Hyphens are replaced with a space via the punctuation pass below,
    so "mag-enroll" normalizes to "mag enroll" and "re-enroll" to "re enroll".
    """
    text = text.lower()
    text = text.replace("'", "'")  # curly -> straight apostrophe
    text = re.sub(r"'s\b", "", text)  # collapse possessive "'s" before removal
    text = text.replace("'", "")  # drop any remaining apostrophes
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# app/services/nlp/intent.py
"""
Lightweight, zero-API-cost intent classification for student queries.

Uses keyword/phrase matching against five fixed categories. These exact
strings must match what's already hardcoded in:
    - frontend/js/admin/dashboard.js  (intentClass() mapping, for CSS pill colors)
    - frontend/js/admin/clusters.js   (cluster card titles like "Scholarship
                                        Guidelines", "Enrollment Schedules")

No ML model is used here intentionally — keyword rules are fully
deterministic, require no training data, and are easy for a non-technical
admin to audit/extend (just add a phrase to a list) compared to a trained
classifier they can't inspect.

Limitation to be aware of: ambiguous queries that don't match any keyword
list fall back to "Academic Policy" as a catch-all. As real query volume
comes in, the keyword lists below should be revisited and expanded based
on what's actually showing up misclassified in the Query Clusters page —
that's exactly the feedback loop the clustering pipeline (Step 3) is for.

When adding new keywords, watch for substring collisions across category
lists (e.g. "tuition" living in two categories where one is a more
specific phrase like "free tuition") — see the comment above
_CATEGORY_ORDER for the known collisions this module currently relies on
staying in a specific check order.
"""

import re

# The five fixed intent categories — must match dashboard.js intentClass().
INTENT_SCHOLARSHIP = "Scholarship Info"
INTENT_ENROLLMENT = "Enrollment"
INTENT_DIRECTORY = "Campus Directory"
INTENT_PAYMENTS = "Payments"
INTENT_ACADEMIC_POLICY = "Academic Policy"

DEFAULT_INTENT = INTENT_ACADEMIC_POLICY

# Keyword/phrase lists per category. Lowercase, no punctuation assumed —
# matching is done against a normalized version of the query text.
# Order matters: categories are checked top-to-bottom and the first match
# wins, so put more specific/distinctive phrases in categories checked
# earlier if overlap is a concern (see _CATEGORY_ORDER below).

_KEYWORDS = {
    INTENT_SCHOLARSHIP: [
        "scholarship", "scholarships", "scholar", "scholars", "gwa",
        "general weighted average", "grade requirement", "form 138",
        "academic scholar", "grant", "financial assistance", "discount",
        "iskolar", "iskolarship", "merit", "dean's lister", "deans lister",
        "latin honor", "academic excellence award", "free tuition",
        "maintain scholarship", "renew scholarship", "scholarship slot",
        "scholarship requirements", "qualify for scholarship",
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
    ],
    INTENT_DIRECTORY: [
        "where is", "where can i find", "located", "location",
        "saan ang", "saan po ang", "office hours", "office", "clinic",
        "infirmary", "guidance office", "guidance counselor",
        "registrar's office", "registrar office", "directory",
        "room number", "what room", "building", "faculty", "professor's office",
        "teacher's office", "contact number", "phone number", "telephone number",
        "email address of", "school address", "campus map", "how to get to",
    ],
    INTENT_PAYMENTS: [
        "payment", "payments", "pay", "paying", "paid", "tuition",
        "tuition fee", "balance", "account balance", "cashier",
        "cashier's office", "billing", "billing statement", "invoice",
        "fee", "fees", "miscellaneous fee", "installment", "installment plan",
        "down payment", "official receipt", "or number", "refund",
        "refund policy", "bayad", "magbayad", "babayaran", "utang",
        "promissory note", "assessment of fees", "statement of account",
        "soa", "payment deadline", "payment plan", "online payment",
        "gcash", "bank transfer",
    ],
    INTENT_ACADEMIC_POLICY: [
        "uniform", "uniforms", "dress code", "id lace", "pe uniform",
        "haircut", "wash day", "attendance", "absence", "absences",
        "excuse letter", "tardiness", "grading", "grading system",
        "passing grade", "failing grade", "incomplete grade", "retake",
        "policy", "policies", "handbook", "student handbook",
        "code of conduct", "discipline", "disciplinary action",
        "retention policy", "academic probation", "dropping a subject",
        "leave of absence", "graduation requirements",
    ],
}

# Explicit check order — keeps narrower/less-ambiguous categories first.
# (e.g. "fee" could theoretically appear in an enrollment context too,
# so Payments and Scholarship are checked before the catch-all Academic
# Policy bucket.)
#
# IMPORTANT — this order is load-bearing, not arbitrary. A few keyword
# pairs deliberately rely on it to avoid misrouting:
#   - "bank transfer" (Payments) vs "transfer" (Enrollment):
#     Payments must be checked before Enrollment, or "I paid via bank
#     transfer" would still resolve correctly either way since "bank
#     transfer" only lives in Payments — but don't move "transfer" itself
#     into Payments without removing it from Enrollment first.
#   - "free tuition" (Scholarship) vs "tuition" (Payments):
#     Scholarship must stay before Payments, or "is there free tuition
#     for scholars" would match Payments' bare "tuition" first and lose
#     the scholarship context.
#   - "refund policy" (Payments) vs "policy" (Academic Policy):
#     Payments must stay before Academic Policy for the same reason.
# If you add new keywords, re-run the collision check in this module's
# test suite before changing _CATEGORY_ORDER.
_CATEGORY_ORDER = [
    INTENT_SCHOLARSHIP,
    INTENT_PAYMENTS,
    INTENT_ENROLLMENT,
    INTENT_DIRECTORY,
    INTENT_ACADEMIC_POLICY,
]


def classify_intent(query_text: str) -> str:
    """
    Classifies a student query into one of five fixed intent categories.

    Args:
        query_text: The raw text of the student's question.

    Returns:
        One of INTENT_SCHOLARSHIP, INTENT_ENROLLMENT, INTENT_DIRECTORY,
        INTENT_PAYMENTS, INTENT_ACADEMIC_POLICY. Falls back to
        INTENT_ACADEMIC_POLICY (DEFAULT_INTENT) if nothing matches.
    """
    if not query_text or not query_text.strip():
        return DEFAULT_INTENT

    normalized = _normalize(query_text)

    for category in _CATEGORY_ORDER:
        for phrase in _KEYWORDS[category]:
            if phrase in normalized:
                return category

    return DEFAULT_INTENT


def _normalize(text: str) -> str:
    """
    Lowercases and strips punctuation (keeping spaces) so phrase matching
    isn't broken by things like "GWA?" or "tuition," not matching "gwa"/
    "tuition" due to trailing punctuation.
    """
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
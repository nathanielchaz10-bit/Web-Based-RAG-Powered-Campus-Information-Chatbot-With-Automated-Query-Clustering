# app/services/nlp/sentiment.py
"""
Lightweight, zero-API-cost sentiment classification for student queries.

Uses VADER (Valence Aware Dictionary and sEntiment Reasoner) — a rule-based
sentiment model tuned for short, informal text, which fits chat-style
student queries well (it understands punctuation emphasis, negation,
intensifiers like "very"/"really", and capitalization as signals).

VADER itself returns a compound score from -1.0 (most negative) to +1.0
(most positive). We map that score into the THREE labels the rest of the
system already expects — these exact strings are used by:
    - app/models/query_log.py            (QueryLog.sentiment, free string)
    - frontend/js/admin/clusters.js       (sentiment distribution bars)
    - frontend/admin/clusters.html        ("Urgent / Frustrated Drivers" modal)

Install:
    pip install vaderSentiment

No NLTK corpus download required — vaderSentiment ships its own lexicon.

Graceful degradation: if vaderSentiment is not installed, this module still
imports cleanly and classify_sentiment() falls back to neutral. That keeps the
chat router (which imports this module) working even on an environment where
the optional NLP dependency hasn't been installed yet — sentiment enrichment
is a nice-to-have, not a hard requirement for answering a student's question.
"""

import re

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    # Singleton analyzer — VADER's lexicon loads once per process, not per call.
    _analyzer = SentimentIntensityAnalyzer()
except Exception:  # pragma: no cover - exercised only when the dep is absent
    # Missing/broken vaderSentiment install. Degrade instead of crashing the
    # import of every module that depends on this one (e.g. the chat router).
    _analyzer = None

# The three sentiment buckets used across the admin dashboard/clusters UI.
SENTIMENT_POSITIVE = "Positive / Inquisitive"
SENTIMENT_NEUTRAL = "Neutral / Transactional"
SENTIMENT_URGENT = "Urgent / Frustrated"

# Thresholds on VADER's compound score.
# VADER's own docs suggest +/-0.05 as the boundary between neutral and
# polarized, but that band is too narrow for short transactional queries
# ("when is enrollment" scores ~0.0 and should stay neutral, not flip on
# noise). Widened the neutral band to +/-0.2 to reduce false positives
# on routine administrative questions.
_POSITIVE_THRESHOLD = 0.2
_NEGATIVE_THRESHOLD = -0.2

# Emphasis / shouting heuristic (see _has_emphasis_markers). A message that is
# at least _SHOUT_CAPS_RATIO uppercase counts as "shouting" only once it has at
# least _SHOUT_MIN_LETTERS letters, so short acronyms ("GWA?", "TOR po?") and
# normal-case queries don't get flagged.
_SHOUT_MIN_LETTERS = 12
_SHOUT_CAPS_RATIO = 0.8

# Words/phrases that signal urgency or distress regardless of VADER's
# polarity score — VADER often scores these near-neutral because they
# aren't classically "negative" words, but in a school-admin context
# they indicate a student who needs faster attention.
_URGENCY_OVERRIDE_TERMS = [
    "asap", "urgent", "emergency", "deadline today", "deadline is today",
    "please help", "i need help now", "running out of time",
    "about to expire", "last day", "final notice",
]


def classify_sentiment(query_text: str) -> str:
    """
    Classifies a student query into one of three sentiment buckets.

    Args:
        query_text: The raw text of the student's question.

    Returns:
        One of SENTIMENT_POSITIVE, SENTIMENT_NEUTRAL, SENTIMENT_URGENT.
    """
    if not query_text or not query_text.strip():
        return SENTIMENT_NEUTRAL

    text_lower = query_text.lower()

    # 1. Explicit urgency vocabulary takes priority over everything — a student
    # typing "URGENT, deadline today!!" should never be bucketed as neutral
    # just because VADER doesn't recognize "deadline" as negative.
    if any(term in text_lower for term in _URGENCY_OVERRIDE_TERMS):
        return SENTIMENT_URGENT

    # 2. VADER lexical polarity. A clearly positive or negative compound score
    # is decisive, and it is checked BEFORE the emphasis heuristic below so that
    # genuine positivity ("thanks, this is great!!!") is not mis-flagged as
    # Frustrated just because it shouts. (compound defaults to 0.0/neutral when
    # the optional vaderSentiment dependency is unavailable.)
    compound = _analyzer.polarity_scores(query_text)["compound"] if _analyzer else 0.0
    if compound >= _POSITIVE_THRESHOLD:
        return SENTIMENT_POSITIVE
    if compound <= _NEGATIVE_THRESHOLD:
        return SENTIMENT_URGENT

    # 3. VADER reads this as neutral. But it only treats ALL-CAPS and "!" as
    # *intensifiers of an existing sentiment word*, so a shouted,
    # punctuation-heavy but lexically-neutral query — e.g.
    # "WHEN IS THE CHRISTMAS BREAK PO!?!?!?" (VADER compound 0.0) — slips through
    # as Neutral. Treat sustained emphasis/impatience markers as a Frustrated
    # signal so these surface to admins instead of hiding in the neutral pile.
    if _has_emphasis_markers(query_text):
        return SENTIMENT_URGENT

    return SENTIMENT_NEUTRAL


def _has_emphasis_markers(text: str) -> bool:
    """Detect shouting / impatient phrasing that VADER misses on neutral text.

    Two deliberately low-false-positive signals:
      * A run of 2+ emphasis marks ("!!", "??", "!?", "?!", "!?!?!?", ...). A
        lone "!" or the single "?" that ends an ordinary question does NOT
        qualify, so calm questions stay Neutral.
      * Sustained shouting: a message that is at least _SHOUT_CAPS_RATIO
        uppercase, guarded by _SHOUT_MIN_LETTERS so short acronyms and
        normal-case queries don't trip it.
    """
    if re.search(r"[!?]{2,}", text):
        return True

    letters = [c for c in text if c.isalpha()]
    if len(letters) >= _SHOUT_MIN_LETTERS:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio >= _SHOUT_CAPS_RATIO:
            return True

    return False


def get_sentiment_score(query_text: str) -> float:
    """
    Returns the raw VADER compound score (-1.0 to 1.0) without bucketing.
    Useful if SystemMetrics or analytics ever need the continuous value
    rather than the discrete label.
    """
    if not query_text or not query_text.strip() or _analyzer is None:
        return 0.0
    return _analyzer.polarity_scores(query_text)["compound"]

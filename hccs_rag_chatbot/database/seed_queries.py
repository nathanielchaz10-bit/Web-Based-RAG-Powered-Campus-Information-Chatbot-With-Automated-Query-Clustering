"""Seed the database with sample student queries for testing query clustering.

Inserts a batch of realistic, topic-grouped questions directly into QueryLog so
the clustering pipeline has enough dense, semantically-similar groups to work
with.

Clustering needs at least CLUSTERING_MIN_QUERIES valid queries to run at all,
and each topic needs at least MIN_CLUSTER_SIZE (3) tightly-related questions to
survive as a cluster (smaller groups are dropped as noise), so each group below
ships ~5 close paraphrases that should land in the same cluster.

Run from inside hccs_rag_chatbot/:
    python database/seed_queries.py
or:
    python -m database.seed_queries

Then trigger clustering as an admin (dashboard "Query Clusters" page, or
POST /clusters/run). Embedding + labeling call Gemini, so GEMINI_API_KEY must
be set in your .env.

Idempotent: a query whose exact text is already in the DB is skipped, so it's
safe to run more than once.
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Base, SessionLocal, engine
import app.models  # noqa: F401  registers all ORM models on Base.metadata
from app.models.query_log import QueryLog

# Optional NLP enrichment so the dashboard's Detected Intent / Sentiment columns
# are populated for the seeded rows too. Falls back to None if unavailable.
try:
    from app.services.nlp.intent import classify_intent
    from app.services.nlp.sentiment import classify_sentiment
except Exception:  # pragma: no cover - defensive
    classify_intent = classify_sentiment = None


# Topic-grouped sample questions. Each group is intentionally a set of close
# paraphrases so it forms one dense cluster.
SAMPLE_QUERIES = {
    "Scholarship": [
        "What are the requirements to qualify for an academic scholarship?",
        "How do I apply for a scholarship at HCCS?",
        "What GWA do I need to maintain my scholarship?",
        "Is there a scholarship for students with high grades?",
        "How can I renew my academic scholarship next school year?",
    ],
    "Enrollment": [
        "How do I enroll for the next semester?",
        "What are the requirements for enrollment?",
        "When does the enrollment period start?",
        "Can I still enroll if I am a late enrollee?",
        "What is the process for re-enrollment as an old student?",
    ],
    "Payments": [
        "How much is the tuition fee this year?",
        "Can I pay my tuition in installments?",
        "What payment methods are accepted for tuition?",
        "Where do I pay my school fees?",
        "Is there a deadline for the tuition payment?",
    ],
    "Uniform Policy": [
        "What is the school's uniform policy?",
        "What is the dress code on PE days?",
        "What color of ID lace should grade 11 students wear?",
        "Are we allowed to wear our PE uniform on regular days?",
        "What kind of shoes are allowed under the uniform policy?",
    ],
    "Campus Directory": [
        "Where is the registrar's office located?",
        "What are the office hours of the guidance office?",
        "Where can I find the school clinic?",
        "How do I get to the cashier's office?",
        "Which building is the faculty room in?",
    ],
}


def seed():
    # Ensure tables exist so this works even against a brand-new database.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    inserted = skipped = 0
    try:
        existing = {t for (t,) in db.query(QueryLog.query_text).all()}

        flat = [(topic, q) for topic, qs in SAMPLE_QUERIES.items() for q in qs]
        total = len(flat)
        now = datetime.utcnow()

        for i, (topic, text) in enumerate(flat):
            if text in existing:
                skipped += 1
                continue

            intent = classify_intent(text) if classify_intent else None
            sentiment = classify_sentiment(text) if classify_sentiment else None
            # Spread timestamps over the last ~6 days so the query-volume chart
            # and week-over-week growth metric have something to show.
            ts = now - timedelta(days=(total - i) % 6, minutes=i)

            db.add(QueryLog(
                query_text=text,
                timestamp=ts,
                is_valid=True,
                detected_intent=intent,
                sentiment=sentiment,
            ))
            inserted += 1

        db.commit()

        valid_total = db.query(QueryLog).filter(QueryLog.is_valid.is_(True)).count()
        print(f"Seed complete: inserted {inserted}, skipped {skipped} (already present).")
        print(f"Valid queries now in DB: {valid_total}")
        print("Next: trigger clustering as an admin — the Query Clusters page, "
              "or POST /clusters/run. (GEMINI_API_KEY must be set.)")
    except Exception as exc:
        db.rollback()
        print(f"Seeding failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()

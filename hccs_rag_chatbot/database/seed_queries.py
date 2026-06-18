"""Seed the database with sample student queries for testing query clustering.

Inserts a batch of realistic, topic-grouped questions directly into QueryLog so
the clustering pipeline has enough dense, semantically-similar groups to work
with.

Seeds ~60 questions across 8 topics (5-8 close paraphrases each) plus a short
tail of unrelated one-off questions, to mimic a realistic clustering run.

Clustering needs at least CLUSTERING_MIN_QUERIES valid queries to run at all,
and each topic needs at least MIN_CLUSTER_SIZE (3) tightly-related questions to
survive as a cluster (smaller/looser groups are dropped as noise), which is why
each topic ships several close paraphrases and the one-off tail is expected to
stay unclustered.

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
# paraphrases so it forms one dense cluster. The final "_noise" group is a set
# of unrelated one-off questions that should NOT cluster — they mimic the long
# tail of a real run (some queries always end up unclustered).
SAMPLE_QUERIES = {
    "Scholarship": [
        "What are the requirements to qualify for an academic scholarship?",
        "How do I apply for a scholarship at HCCS?",
        "What GWA do I need to maintain my scholarship?",
        "Is there a scholarship for students with high grades?",
        "How can I renew my academic scholarship next school year?",
        "Do I lose my scholarship if my grades drop?",
        "Are there scholarships available for incoming freshmen?",
        "What documents do I submit for a scholarship application?",
    ],
    "Enrollment": [
        "How do I enroll for the next semester?",
        "What are the requirements for enrollment?",
        "When does the enrollment period start?",
        "Can I still enroll if I am a late enrollee?",
        "What is the process for re-enrollment as an old student?",
        "How do I enroll as a transferee from another school?",
        "Is online enrollment available this year?",
        "What is the deadline for enrollment this semester?",
    ],
    "Payments": [
        "How much is the tuition fee this year?",
        "Can I pay my tuition in installments?",
        "What payment methods are accepted for tuition?",
        "Where do I pay my school fees?",
        "Is there a deadline for the tuition payment?",
        "Can I pay tuition through GCash or bank transfer?",
        "How do I get an official receipt for my payment?",
        "What happens if I miss the tuition payment deadline?",
    ],
    "Uniform Policy": [
        "What is the school's uniform policy?",
        "What is the dress code on PE days?",
        "What color of ID lace should grade 11 students wear?",
        "Are we allowed to wear our PE uniform on regular days?",
        "What kind of shoes are allowed under the uniform policy?",
        "Is there a haircut rule for male students?",
        "What is the proper uniform for wash days?",
    ],
    "Campus Directory": [
        "Where is the registrar's office located?",
        "What are the office hours of the guidance office?",
        "Where can I find the school clinic?",
        "How do I get to the cashier's office?",
        "Which building is the faculty room in?",
        "Where is the library located?",
        "What is the contact number of the registrar's office?",
    ],
    "Grades / Records": [
        "How do I request a copy of my grades?",
        "What is the passing grade at HCCS?",
        "How is the grading system computed?",
        "How can I get my Form 138?",
        "What should I do if I have an incomplete grade?",
        "How do I request my transcript of records?",
        "When will the grades for this semester be released?",
    ],
    "Attendance": [
        "What is the school's attendance policy?",
        "How many absences are allowed before being dropped?",
        "Do I need an excuse letter after being absent?",
        "What is the policy on tardiness?",
        "What happens if I miss an exam due to an absence?",
        "How do I file an excuse for an absence?",
    ],
    "Class Schedule": [
        "How do I check my class schedule?",
        "Can I change my class schedule after enrollment?",
        "Where do I see my room assignments?",
        "What time do classes start in the morning?",
        "How do I add or drop a subject from my schedule?",
    ],
    "_noise": [
        "Is there a basketball varsity team I can try out for?",
        "Does the school have a lost and found section?",
        "Can I bring my own laptop to class?",
        "What time does the canteen close?",
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

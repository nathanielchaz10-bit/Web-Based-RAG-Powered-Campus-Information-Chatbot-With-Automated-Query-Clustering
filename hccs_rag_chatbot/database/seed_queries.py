"""Seed the database with sample student queries for testing query clustering.

Inserts a batch of realistic, topic-grouped questions directly into QueryLog so
the clustering pipeline has enough dense, semantically-similar groups to work
with.

Seeds 150 questions across 14 topics (8-12 close paraphrases each) plus a short
tail of unrelated one-off questions, to mimic a realistic clustering run.

Clustering needs at least CLUSTERING_MIN_QUERIES valid queries to run at all,
and each topic needs at least MIN_CLUSTER_SIZE (3) tightly-related questions to
survive as a cluster (smaller/looser groups are dropped as noise), which is why
each topic ships several close paraphrases and the one-off tail is expected to
stay unclustered.

Run from inside hccs_rag_chatbot/:
    python database/seed_queries.py            # append (skips existing)
    python database/seed_queries.py --reset    # wipe queries + clusters first

Then trigger clustering as an admin (dashboard "Query Clusters" page, or
POST /clusters/run). Embedding + labeling call Gemini, so GEMINI_API_KEY must
be set in your .env.

Idempotent: a query whose exact text is already in the DB is skipped, so a
plain run is safe to repeat. Use --reset when you've changed the intent/
sentiment logic and want existing rows re-classified — it clears query_logs
(and the clusters/keywords/runs that reference them) before re-seeding.
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
        "Is there a discount or scholarship for siblings studying here?",
        "When is the deadline to apply for a scholarship?",
        "Who do I contact to follow up on my scholarship application?",
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
        "How much is the reservation fee during enrollment?",
        "Do incoming students need to take an entrance exam?",
        "Where do I submit my enrollment requirements?",
        "Can my parent enroll me if I can't come to school?",
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
        "How much is the downpayment for this school year?",
        "Is there a penalty for paying tuition late?",
        "Can I take the exams if I still have a balance?",
        "What are the available payment schemes for tuition?",
    ],
    "Uniform Policy": [
        "What is the school's uniform policy?",
        "What is the dress code on PE days?",
        "What color of ID lace should grade 11 students wear?",
        "Are we allowed to wear our PE uniform on regular days?",
        "What kind of shoes are allowed under the uniform policy?",
        "Is there a haircut rule for male students?",
        "What is the proper uniform for wash days?",
        "Where can I buy the official school uniform?",
        "Are accessories or colored hair allowed in school?",
        "Do we need to wear the complete uniform during exams?",
    ],
    "Campus Directory": [
        "Where is the registrar's office located?",
        "What are the office hours of the guidance office?",
        "Where can I find the school clinic?",
        "How do I get to the cashier's office?",
        "Which building is the faculty room in?",
        "Where is the library located?",
        "What is the contact number of the registrar's office?",
        "What time does the registrar's office open?",
        "Where is the admissions office located?",
        "How do I contact the principal's office?",
    ],
    "Grades / Records": [
        "What is the passing grade at HCCS?",
        "How is the grading system computed?",
        "What should I do if I have an incomplete grade?",
        "When will the grades for this semester be released?",
        "How do I have my grade rechecked if it looks wrong?",
        "How is the general weighted average calculated?",
        "Where can I view my grades for this quarter?",
        "What grade do I need to pass a subject?",
        "Who do I approach about a failing grade?",
        "Are grades released per quarter or per semester?",
        "How do I compute my average from my grades?",
    ],
    "Attendance": [
        "What is the school's attendance policy?",
        "How many absences are allowed before being dropped?",
        "Do I need an excuse letter after being absent?",
        "What is the policy on tardiness?",
        "What happens if I miss an exam due to an absence?",
        "How do I file an excuse for an absence?",
        "Will I be marked absent if I come in late?",
        "How many times can I be late before it counts as an absence?",
        "Do I need a medical certificate after being sick for several days?",
    ],
    "Class Schedule": [
        "How do I check my class schedule?",
        "Can I change my class schedule after enrollment?",
        "Where do I see my room assignments?",
        "What time do classes start in the morning?",
        "How do I add or drop a subject from my schedule?",
        "Where can I find my section's class schedule?",
        "What time is dismissal for senior high students?",
        "Can I request a different section after enrollment?",
        "How do I know which room my class is in?",
    ],
    "Portal / LMS": [
        "How do I log in to the student portal?",
        "I forgot my LMS password, how do I reset it?",
        "The student portal is not loading, what should I do?",
        "Where do I access my online modules?",
        "How do I get my student portal account?",
        "Why can't I log in to my school account?",
        "How do I change my password on the LMS?",
        "Who do I contact for student portal problems?",
        "Is there an app for the school's learning management system?",
        "My account is locked, how do I get back in?",
        "Where do I submit my activities on the LMS?",
    ],
    "Honors / Awards": [
        "What is the GWA required to graduate with honors?",
        "How do I qualify for the honor roll?",
        "What is the average needed for With High Honors?",
        "Is PE included in computing honors?",
        "Does a grade below 90 disqualify me from honors?",
        "What awards are given during recognition day?",
        "Are honors given per quarter or for the whole year?",
        "What are the requirements for the academic excellence award?",
        "Is there a leadership award for student officers?",
        "How is the honor ranking decided among students?",
        "What is the cutoff average to be an honor student?",
    ],
    "Events / Suspensions": [
        "What time does the flag ceremony start?",
        "Is there a morning mass tomorrow?",
        "Are classes suspended because of the typhoon?",
        "When is the foundation day celebration?",
        "When do classes resume after the semestral break?",
        "Is there class on the holiday next week?",
        "When is the intramurals this school year?",
        "Will classes be cancelled due to the bad weather?",
        "Is today's class suspended due to the storm?",
        "When is the Christmas break this year?",
        "When is the parent-teacher conference scheduled?",
    ],
    "Library / Facilities": [
        "What are the library's opening hours?",
        "Can I borrow books from the library overnight?",
        "Is there free WiFi for students on campus?",
        "How do I connect to the school WiFi?",
        "Are there study areas students can use?",
        "How many books can I borrow at once?",
        "What is the fine for returning a book late?",
        "Does the library have computers students can use?",
        "Until what time is the library open on weekdays?",
        "Can alumni still use the school library?",
    ],
    "Documents / Certificates": [
        "How do I request my transcript of records?",
        "How long does it take to get a good moral certificate?",
        "How do I get a copy of my Form 137?",
        "How much does a certificate of enrollment cost?",
        "Can I request my school documents online?",
        "How do I get a certified true copy of my grades?",
        "What do I need to claim my Form 138 report card?",
        "How many days before I can claim my transcript?",
        "Can someone else claim my documents on my behalf?",
    ],
    "Guidance / Student Welfare": [
        "How do I set an appointment with the guidance counselor?",
        "Who do I talk to if I am being bullied?",
        "Is there counseling available for stressed students?",
        "What is the school's anti-bullying policy?",
        "How do I report a bullying incident?",
        "Can I talk to a counselor about personal problems?",
        "Where do I get a guidance clearance signed?",
        "How do I file a complaint against a classmate?",
    ],
    "_noise": [
        "Is there a basketball varsity team I can try out for?",
        "Does the school have a lost and found section?",
        "Can I bring my own laptop to class?",
        "What time does the canteen close?",
        "Is there a school choir I can join?",
        "Are cellphones allowed during class hours?",
    ],
}


def _reset(db):
    """Wipe all query + clustering data so a fresh seed recomputes everything.

    Deleted in FK-safe order (children first): cluster_keywords -> clusters ->
    clustering_runs -> query_logs. Run this when you've changed the intent or
    sentiment logic and want existing rows re-classified (a plain re-seed skips
    queries whose text is already present, so it won't recompute them).
    """
    from app.models.cluster_keyword import ClusterKeyword
    from app.models.cluster import Cluster
    from app.models.clustering_run import ClusteringRun

    kw = db.query(ClusterKeyword).delete()
    cl = db.query(Cluster).delete()
    runs = db.query(ClusteringRun).delete()
    qs = db.query(QueryLog).delete()
    db.commit()
    print(f"Reset: removed {qs} queries, {cl} clusters, {kw} keywords, {runs} runs.")


def seed(reset: bool = False):
    # Ensure tables exist so this works even against a brand-new database.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    inserted = skipped = 0
    try:
        if reset:
            _reset(db)

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
            # Spread timestamps over the last ~14 days so the query-volume chart
            # and week-over-week growth metric have something to show.
            ts = now - timedelta(days=(total - i) % 14, minutes=i)

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
    seed(reset="--reset" in sys.argv)

import sqlite3
import os

def seed_database():
    mock_questions = [
        ("when is the deadline to pay tuition?", "Tuition deadlines vary per payment scheme. Please check with the cashier's office for your specific schedule."),
        ("how much is the downpayment for enrollment?", "The downpayment amount is set by the finance office and is announced during the enrollment period."),
        ("can i pay my fees through gcash?", "Yes, GCash payments are accepted. Please send your receipt to the cashier's office for confirmation."),
        ("what are the rules for the academic excellence award?", "The Academic Excellence Award is given to students who achieve a GWA of 90 or above with no failing grades in any subject."),
        ("how do i get with high honors?", "With High Honors is awarded to students with a GWA of 95 and above, with no grade below 90 in any subject."),
        ("is pe required for the honors list?", "Yes, PE is included in the computation of the GWA for honors. No subject is excluded."),
        ("where do i log in to check my grades?", "You can check your grades through the school's Learning Management System (LMS). Your login credentials were provided during enrollment."),
        ("i forgot my lms password, who do i contact?", "Please contact the IT office or your class adviser to request a password reset for your LMS account."),
        ("is the school official website down?", "If the school website is inaccessible, please try again later or contact the IT office to report the issue."),
        ("what time does the flag ceremony start?", "The flag ceremony starts at 7:00 AM. Students are expected to be present and in proper uniform."),
        ("do we have morning mass tomorrow?", "Morning mass schedules are announced by the school. Please check official school communications or ask your adviser for the schedule."),
    ]

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, 'analytics.db')
    conn = sqlite3.connect(db_path)
    
    cursor = conn.cursor()
    
    for q, a in mock_questions:
        cursor.execute(
            "INSERT INTO user_queries (query_text, answer_text) VALUES (?, ?)", (q, a)
        )
        
    conn.commit()
    conn.close()
    print(f"Successfully injected {len(mock_questions)} mock queries into the database!")

if __name__ == "__main__":
    seed_database()
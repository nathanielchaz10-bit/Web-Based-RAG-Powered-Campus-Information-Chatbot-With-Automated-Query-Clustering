import sqlite3
import os

def stress_test_seed():
    massive_mock_data = [
        # Finance
        ("can i pay via installment?", "Yes, tuition can be paid in installments. Please coordinate with the cashier's office for the available payment schemes."),
        ("where is the cashier?", "The cashier's office is located at the main building, ground floor, beside the registrar's office."),
        ("is there a discount for cash payment?", "Yes, a discount is available for full cash payment at the start of the school year. Please inquire at the cashier for the exact percentage."),
        ("my gcash payment didn't reflect", "Please send your GCash receipt to the cashier's office email or present it in person so they can verify and update your account."),
        ("how much is the late fee?", "A late payment fee is charged for payments made after the deadline. Please refer to the fee schedule provided during enrollment."),
        # Uniforms
        ("can we wear rubber shoes?", "Rubber shoes are only allowed during PE classes. The prescribed leather shoes must be worn with the regular uniform on regular school days."),
        ("is the pe uniform allowed on wednesdays?", "Yes, students are allowed to wear their PE uniform on Wednesdays, which is the designated PE day."),
        ("where do i buy the patch?", "School patches are available at the school bookstore located near the main entrance."),
        ("what color are the socks supposed to be?", "White socks are the prescribed color for all students as part of the standard uniform."),
        ("are hairpins allowed?", "Plain hairpins in dark colors (black or dark brown) are allowed. Flashy or oversized accessories are not permitted."),
        # Grades & Academics
        ("when is the release of report cards?", "Report cards are typically released at the end of each grading period. Specific dates are announced through official school communications."),
        ("how to compute my gwa?", "Your GWA is the average of your final grades across all subjects for the grading period, weighted equally unless otherwise specified."),
        ("what is the passing grade for math?", "The passing grade for all subjects, including Math, is 75 based on the DepEd grading system."),
        ("can i contest my grade?", "Yes, you may file a grade appeal by submitting a formal request to your subject teacher and the registrar within one week of report card release."),
        ("who is the valedictorian?", "The valedictorian is the graduating student with the highest General Weighted Average for the entire academic year."),
        # Discipline & Absences
        ("what happens if i'm late 3 times?", "Three tardiness incidents are equivalent to one absence. Accumulating a certain number of absences may affect your grade or require a parent conference."),
        ("how many absences until i fail?", "A student who exceeds 20% of the total school days (approximately 20 days per semester) may be dropped from the subject."),
        ("do i need a medical certificate for being sick?", "Yes, a medical certificate is required for absences of three or more consecutive days due to illness."),
        ("where is the guidance office?", "The guidance office is located on the second floor of the main building, across from the principal's office."),
        ("what is the penalty for cheating?", "Cheating is a major offense. Penalties range from a failing grade on the test to suspension, depending on the severity and frequency of the offense."),
        # Events & Scheduling
        ("when is intramurals?", "Intramurals is typically held during the third quarter of the school year. The exact date will be announced by the school."),
        ("is there no classes tomorrow?", "Please check the official school announcements or the school website for class suspension updates."),
        ("what time is dismissal on friday?", "Dismissal on Fridays is at 4:00 PM for regular school days, unless otherwise announced."),
        ("when is the christmas party?", "The Christmas party is usually scheduled on the last school day before the Christmas break. The specific date will be announced by the homeroom adviser."),
        ("when do we start the 2nd semester?", "The second semester typically begins in January. Refer to the official school calendar for the exact start date."),
        # Messy / Realistic Student Input
        ("hello bot where id", "Hi! If you're asking about your school ID, you can get it from the registrar's office. Please bring your enrollment form."),
        ("late ako kanina", "If you were late, please make sure to secure an admission slip from the guard on duty before going to class."),
        ("grades when???", "Report cards are released at the end of each grading period. Watch out for official announcements from your adviser."),
        ("uniform rules", "The school requires students to wear the prescribed uniform daily. This includes the standard polo, slacks or skirt, leather shoes, and white socks. PE uniform is allowed on PE days."),
        ("tuition deadline plsss", "Tuition deadlines are set at the beginning of the school year. Please check with the cashier's office for your specific payment schedule and deadlines."),
    ]

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, 'analytics.db')
    conn = sqlite3.connect(db_path)
    
    cursor = conn.cursor()
    for q, a in massive_mock_data:
        cursor.execute(
            "INSERT INTO user_queries (query_text, answer_text) VALUES (?, ?)", (q, a)
        )
    conn.commit()
    conn.close()
    print("Injected 30 stress-test questions into the database!")

if __name__ == "__main__":
    stress_test_seed()
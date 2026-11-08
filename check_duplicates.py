# check_duplicates.py
from sqlalchemy import text
from app.core.database import engine

dupes = text("""
    SELECT course_id, user_id, COUNT(*) AS paid_rows, SUM(amount) AS total
    FROM payments
    WHERE status = 'paid'
    GROUP BY course_id, user_id
    HAVING COUNT(*) > 1
""")

hindi = text("""
    SELECT *
    FROM payments
    WHERE status = 'paid'
      AND course_id = (SELECT id FROM courses WHERE title = 'Hindi' LIMIT 1)
""")

with engine.connect() as c:
    print("--- Duplicate (course, user) paid rows ---")
    for row in c.execute(dupes).mappings():
        print(dict(row))

    print("--- All paid rows for course 'Hindi' ---")
    for row in c.execute(hindi).mappings():
        print(dict(row))
import sqlite3

conn = sqlite3.connect('geoclean.db')
c = conn.cursor()

# Add ai_description column if it doesn't exist
try:
    c.execute("ALTER TABLE posts ADD COLUMN ai_description TEXT")
    print("Column added successfully.")
except sqlite3.OperationalError as e:
    print("Column probably already exists:", e)

conn.commit()
conn.close()

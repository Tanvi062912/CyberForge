import sqlite3
import os

DATABASE = "database/cyberforge.db"
print("DB Absolute Path:", os.path.abspath(DATABASE))
print("DB Exists:", os.path.exists(DATABASE))

if os.path.exists(DATABASE):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print("Tables:", tables)
    
    # Let's inspect users table
    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        print("Users count:", cursor.fetchone()[0])
    except Exception as e:
        print("Users error:", e)
        
    try:
        cursor.execute("SELECT COUNT(*) FROM leaderboard")
        print("Leaderboard count:", cursor.fetchone()[0])
    except Exception as e:
        print("Leaderboard error:", e)
    conn.close()
else:
    print("Database file not found.")

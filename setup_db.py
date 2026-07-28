import sqlite3
import os

os.makedirs("database", exist_ok=True)

conn = sqlite3.connect("database/cyberforge.db")

cursor = conn.cursor()

# ---------------- USERS ----------------

cursor.execute("""

CREATE TABLE IF NOT EXISTS users(

id INTEGER PRIMARY KEY AUTOINCREMENT,

username TEXT NOT NULL,

email TEXT UNIQUE NOT NULL,

password TEXT NOT NULL

)

""")

# ---------------- ACTIVITY LOGS ----------------

cursor.execute("""

CREATE TABLE IF NOT EXISTS activity_logs(

id INTEGER PRIMARY KEY AUTOINCREMENT,

username TEXT,

activity TEXT,

timestamp DATETIME DEFAULT CURRENT_TIMESTAMP

)

""")

# ---------------- LABS ----------------

cursor.execute("""

CREATE TABLE IF NOT EXISTS labs(

id INTEGER PRIMARY KEY AUTOINCREMENT,

title TEXT,

difficulty TEXT,

xp INTEGER

)

""")

# ---------------- LAB PROGRESS ----------------

cursor.execute("""

CREATE TABLE IF NOT EXISTS lab_progress(

id INTEGER PRIMARY KEY AUTOINCREMENT,

username TEXT,

lab_id INTEGER,

completed INTEGER DEFAULT 0,

flag TEXT

)

""")

# ---------------- ACADEMY LESSONS ----------------

cursor.execute("""
CREATE TABLE IF NOT EXISTS academy_lessons(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_key TEXT UNIQUE,
    title TEXT,
    correct_flag TEXT,
    xp_value INTEGER
)
""")

# Seed values for all 9 lessons
lessons_seed = [
    ('social_engineering', 'Social Engineering', 'ACADEMY{PHISH_DETECTED_2026}', 50),
    ('password_attacks', 'Password Attacks', 'ACADEMY{BRUTE_FORCE_SUCCESS_2026}', 50),
    ('packet_sniffing', 'Packet Sniffing', 'ACADEMY{PACKETS_CAPTURED_CLEARTEXT}', 75),
    ('sql_injection', 'SQL Injection', 'ACADEMY{SQL_UNION_INJECTION_COMPLETED}', 100),
    ('xss', 'XSS', 'ACADEMY{CROSS_SITE_SCRIPTING_REFLECTED_PASSED}', 100),
    ('lfi', 'Local File Inclusion (LFI)', 'ACADEMY{LOCAL_FILE_INCLUSION_SUCCESS}', 150),
    ('privilege_escalation', 'Privilege Escalation', 'ACADEMY{SUID_BINARY_ESCAPE_COMPLETED}', 150),
    ('windows_enumeration', 'Windows Enumeration', 'ACADEMY{WINDOWS_ENV_LANDING_PASSED}', 100),
    ('linux_enumeration', 'Linux Enumeration', 'ACADEMY{LINUX_HOST_ENUM_COMPLETED}', 100)
]

for lesson_key, title, correct_flag, xp in lessons_seed:
    cursor.execute("""
    INSERT OR REPLACE INTO academy_lessons (lesson_key, title, correct_flag, xp_value)
    VALUES (?, ?, ?, ?)
    """, (lesson_key, title, correct_flag, xp))

conn.commit()
conn.close()

print("CyberForge Database Created & Seeded Successfully")
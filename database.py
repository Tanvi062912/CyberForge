import sqlite3
import os
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ORIGINAL_DB = os.path.join(BASE_DIR, "database", "cyberforge.db")
TMP_DB = "/tmp/cyberforge.db"


def get_db_path():
    if os.environ.get("VERCEL"):
        if not os.path.exists(TMP_DB):
            try:
                os.makedirs("/tmp", exist_ok=True)
                if os.path.exists(ORIGINAL_DB):
                    shutil.copyfile(ORIGINAL_DB, TMP_DB)
            except Exception as e:
                print(f"Error copying DB to /tmp: {e}")
        if os.path.exists(TMP_DB):
            return TMP_DB
    return ORIGINAL_DB


def get_db():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
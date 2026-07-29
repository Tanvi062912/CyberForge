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
                else:
                    alt_path = os.path.join(os.getcwd(), "database", "cyberforge.db")
                    if os.path.exists(alt_path):
                        shutil.copyfile(alt_path, TMP_DB)
                    else:
                        conn = sqlite3.connect(TMP_DB)
                        conn.close()
            except Exception as e:
                print(f"Error initializing DB in /tmp: {e}")
                try:
                    conn = sqlite3.connect(TMP_DB)
                    conn.close()
                except Exception:
                    pass
        return TMP_DB
    return ORIGINAL_DB



def get_db():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
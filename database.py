import sqlite3

DATABASE = "database/cyberforge.db"


def get_db():

    conn = sqlite3.connect(DATABASE)

    conn.row_factory = sqlite3.Row

    return conn
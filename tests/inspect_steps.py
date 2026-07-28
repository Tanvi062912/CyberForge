import sqlite3

conn = sqlite3.connect("database/cyberforge.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute("SELECT * FROM scenario_steps")
rows = cursor.fetchall()
print("Total rows:", len(rows))
for row in rows:
    print(dict(row))

conn.close()

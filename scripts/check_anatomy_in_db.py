import sqlite3
import json
from pathlib import Path

db_path = Path(r"D:\Sentinari\data\sentinari.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

row = cur.execute("SELECT count(id) FROM documents WHERE source_collection = 'PrintAnatomy.eu'").fetchone()
print(f"Current PrintAnatomy documents in sentinari.db: {row[0]}")

row_apert = cur.execute("SELECT count(id) FROM documents WHERE title LIKE '%Apert%'").fetchone()
print(f"Current Apert syndrome documents: {row_apert[0]}")
conn.close()

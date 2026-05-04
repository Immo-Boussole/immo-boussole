import sqlite3
import json

conn = sqlite3.connect('immo_boussole.db')
cursor = conn.cursor()
cursor.execute("SELECT id, title, url FROM listings")
rows = cursor.fetchall()
print([r[0] for r in rows])

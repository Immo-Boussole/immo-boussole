#!/usr/bin/env python3
"""
Script to update a test user in the database.
"""
import sqlite3
import sys

def update_test_user(username, work_address):
    # Use static coordinates for Paris
    work_lat, work_lon = 48.8566, 2.3522

    conn = sqlite3.connect('immo_boussole.db')
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users
        SET work_address = ?, work_lat = ?, work_lon = ?
        WHERE username = ?
    """, (work_address, work_lat, work_lon, username))
    conn.commit()
    print(f"User {username} updated with work address: {work_address}")
    print(f"Coordinates: Latitude {work_lat}, Longitude {work_lon}")
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 2:
        username = sys.argv[1]
        work_address = sys.argv[2]
        update_test_user(username, work_address)
    else:
        print("Usage: python update_test_user.py <username> <work_address>")

#!/usr/bin/env python3
"""
Script to check user data in the database using SQLite directly.
"""
import sqlite3
import sys

def check_user_data(username=None):
    conn = sqlite3.connect('immo_boussole.db')
    cursor = conn.cursor()
    if username:
        cursor.execute("SELECT username, work_address, work_lat, work_lon, poi_json FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        if user:
            print(f"User found: {user[0]}")
            print(f"Work Address: {user[1]}")
            print(f"Work Latitude: {user[2]}")
            print(f"Work Longitude: {user[3]}")
            print(f"POI JSON: {user[4]}")
        else:
            print(f"User {username} not found.")
    else:
        cursor.execute("SELECT username FROM users")
        users = cursor.fetchall()
        if users:
            print("Users in database:")
            for user in users:
                print(f"- {user[0]}")
        else:
            print("No users found in database.")
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        username = sys.argv[1]
        check_user_data(username)
    else:
        check_user_data()

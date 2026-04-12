#!/usr/bin/env python3
"""
Script to check user data in the database.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import User

def check_user_data(username):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user:
            print(f"User found: {user.username}")
            print(f"Work Address: {user.work_address}")
            print(f"Work Latitude: {user.work_lat}")
            print(f"Work Longitude: {user.work_lon}")
            print(f"POI JSON: {user.poi_json}")
        else:
            print(f"User {username} not found.")
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        username = sys.argv[1]
        check_user_data(username)
    else:
        print("Usage: python check_user_data.py <username>")

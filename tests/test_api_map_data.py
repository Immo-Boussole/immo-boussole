#!/usr/bin/env python3
"""
Script to test the /api/map-data endpoint.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_map_data():
    # Simulate a logged-in user session
    response = client.get("/api/map-data")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Listings: {len(data.get('listings', []))}")
        print(f"User Work: {data.get('user', {}).get('work')}")
        print(f"User POIs: {data.get('user', {}).get('pois')}")
        print(f"Pins: {len(data.get('pins', []))}")
    else:
        print(f"Error: {response.text}")

if __name__ == "__main__":
    test_map_data()

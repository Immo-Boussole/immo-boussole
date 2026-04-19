import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.geo import get_insee_code, fetch_georisques_data
from app.database import run_migrations, SessionLocal
from app.models import Listing

def test_api():
    print("--- Testing INSEE Lookup ---")
    cities = [("Lyon", "69001"), ("Paris", "75001"), ("Marseille", None)]
    for city, zip in cities:
        insee = get_insee_code(city, zip)
        print(f"{city} ({zip}) -> INSEE: {insee}")

    print("\n--- Testing Géorisques Lookup (INSEE) ---")
    lyon_insee = "69381" # Lyon
    res = fetch_georisques_data(insee_code=lyon_insee)
    if res:
        print(f"Success for INSEE {lyon_insee}! Data keys: {list(res.keys())}")
        # print(json.dumps(res, indent=2))
    else:
        print(f"Failed for INSEE {lyon_insee}")

    print("\n--- Testing Géorisques Lookup (Address) ---")
    addr = "20 rue de la République, 69002 Lyon"
    res = fetch_georisques_data(address=addr)
    if res:
        print(f"Success for Address! Data keys: {list(res.keys())}")
    else:
        print("Failed for Address")

def test_db():
    print("\n--- Running Migrations ---")
    run_migrations()
    
    print("\n--- Verifying Database Column ---")
    db = SessionLocal()
    try:
        from sqlalchemy import text
        result = db.execute(text("PRAGMA table_info(listings)"))
        cols = [row[1] for row in result]
        if "georisques_json" in cols:
            print("Column 'georisques_json' exists in 'listings' table!")
        else:
            print("Column 'georisques_json' MISSING from 'listings' table!")
    finally:
        db.close()

if __name__ == "__main__":
    test_db()
    test_api()

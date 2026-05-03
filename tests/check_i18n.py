import os
import json
import sys
from typing import Dict, Set, List

def get_keys(data: Dict, prefix: str = "") -> Set[str]:
    """Recursively get all keys from a nested dictionary."""
    keys = set()
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys.update(get_keys(value, full_key))
        else:
            keys.add(full_key)
    return keys

def main():
    locales_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")
    if not os.path.exists(locales_dir):
        print(f"Error: locales directory not found at {locales_dir}")
        sys.exit(1)

    locale_files = [f for f in os.listdir(locales_dir) if f.endswith(".json")]
    if not locale_files:
        print("Error: No locale files found.")
        sys.exit(1)

    print(f"Checking {len(locale_files)} locale files: {', '.join(locale_files)}")

    all_keys_map: Dict[str, Set[str]] = {}
    master_keys: Set[str] = set()

    for filename in locale_files:
        filepath = os.path.join(locales_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                keys = get_keys(data)
                all_keys_map[filename] = keys
                master_keys.update(keys)
        except Exception as e:
            print(f"Error reading {filename}: {e}")
            sys.exit(1)

    errors = []
    for filename, keys in all_keys_map.items():
        missing = master_keys - keys
        if missing:
            errors.append((filename, sorted(list(missing))))

    if errors:
        print("\n[!] I18n Mismatch Found!")
        for filename, missing in errors:
            print(f"\n[{filename}] is missing {len(missing)} keys:")
            for key in missing:
                print(f"  - {key}")
        sys.exit(1)
    else:
        print("\n[OK] All locale files are synchronized!")
        sys.exit(0)

if __name__ == "__main__":
    main()

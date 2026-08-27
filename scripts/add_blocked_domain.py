#!/usr/bin/env python3
"""
Script to safely add a domain and description to app/data/blocked_domains.csv.
Can accept domain and description as arguments or parse a GitHub issue body.
"""
import sys
import csv
import re
from pathlib import Path

CSV_PATH = Path(__file__).parent.parent / "app" / "data" / "blocked_domains.csv"


def clean_domain(domain: str) -> str:
    domain = domain.strip().lower()
    # Remove scheme if present
    domain = re.sub(r"^https?://", "", domain)
    # Remove path/port/query
    domain = domain.split("/")[0].split(":")[0].strip()
    return domain


def parse_issue_body(issue_body: str) -> tuple[str, str]:
    """
    Parses GitHub Issue Form body to extract Domain and Description.
    """
    domain = ""
    description = ""

    # Match domain field from Issue Form
    domain_match = re.search(r"###\s*Domain name.*?\n+([^\n#]+)", issue_body, re.IGNORECASE | re.DOTALL)
    if domain_match:
        domain = domain_match.group(1).strip()

    # Match description field from Issue Form
    desc_match = re.search(r"###\s*Description.*?\n+([^\n#]+)", issue_body, re.IGNORECASE | re.DOTALL)
    if desc_match:
        description = desc_match.group(1).strip()

    return clean_domain(domain), description.strip()


def add_blocked_domain(domain: str, description: str) -> bool:
    domain = clean_domain(domain)
    if not domain:
        print("[Error] Invalid domain provided.")
        return False

    existing_rows = []
    if CSV_PATH.is_file():
        with open(CSV_PATH, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_rows.append(row)

    # Check if domain already exists
    for r in existing_rows:
        if (r.get("domain") or "").strip().lower() == domain:
            print(f"[Info] Domain '{domain}' already present in CSV.")
            return False

    # Append new row
    existing_rows.append({"domain": domain, "description": description})

    with open(CSV_PATH, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["domain", "description"])
        writer.writeheader()
        writer.writerows(existing_rows)

    print(f"[Success] Added domain '{domain}' ({description}) to {CSV_PATH}")
    return True


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        d = sys.argv[1]
        desc = " ".join(sys.argv[2:])
        add_blocked_domain(d, desc)
    elif len(sys.argv) == 2:
        # Assume single argument is issue body or domain
        arg = sys.argv[1]
        if "###" in arg:
            d, desc = parse_issue_body(arg)
            add_blocked_domain(d, desc)
        else:
            add_blocked_domain(arg, "Prohibited domain")
    else:
        print("Usage: python add_blocked_domain.py <domain> <description>")
        sys.exit(1)

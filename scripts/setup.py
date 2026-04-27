#!/usr/bin/env python3
"""
Dashboard Password Setup
------------------------
Run this ONCE to set the password for your foreclosure dashboard.
It hashes your chosen password and injects it into index.html.

Usage:
  cd /path/to/your/Foreclosures/folder
  python3 scripts/setup.py
"""

import hashlib
import getpass
import re
import os
import sys


def main():
    print()
    print("  Fredericksburg Foreclosure Tracker")
    print("  ─── Password Setup ──────────────────")
    print()

    html_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    if not os.path.exists(html_path):
        print(f"  ERROR: index.html not found at {html_path}")
        sys.exit(1)

    pwd = getpass.getpass("  Enter the password you want to use: ")
    if not pwd:
        print("  Password cannot be empty.")
        sys.exit(1)

    confirm = getpass.getpass("  Confirm password: ")
    if pwd != confirm:
        print("  Passwords do not match. Run setup.py again.")
        sys.exit(1)

    hash_val = hashlib.sha256(pwd.encode()).hexdigest()

    with open(html_path, "r") as f:
        html = f.read()

    # Replace placeholder OR any previously-set hash
    updated = re.sub(
        r"const PASSWORD_HASH = '[^']*'",
        f"const PASSWORD_HASH = '{hash_val}'",
        html,
    )

    if updated == html:
        print()
        print("  WARNING: Could not find PASSWORD_HASH placeholder in index.html.")
        print("  The file may have been modified. Check index.html manually.")
        sys.exit(1)

    with open(html_path, "w") as f:
        f.write(updated)

    print()
    print("  ✓ Password set successfully!")
    print(f"  ✓ index.html updated.")
    print()
    print("  Share this password with anyone who should have access.")
    print("  They will also need the dashboard URL (set up after GitHub Pages is live).")
    print()
    print("  Next step: run  python3 scripts/scraper.py  to populate data,")
    print("  then follow the GitHub Pages setup instructions.")
    print()


if __name__ == "__main__":
    main()

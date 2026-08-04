"""Prints DB connection status for reviewpilot-db.

Usage: python scripts/check_db.py
"""

import sys

from sqlalchemy import text

from app.db import engine


def main() -> int:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        print(f"db: error ({exc})")
        return 1
    print("db: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

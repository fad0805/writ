#!/usr/bin/env python3
"""Database migration script — supports SQLite and PostgreSQL.

Usage:
  python3 migrate.py              # auto-detect (SQLite default)
  python3 migrate.py sqlite       # force SQLite
  python3 migrate.py postgresql   # force PostgreSQL
"""

import sys
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///sns_blog.db")

# Determine database type
db_type = "sqlite"
if len(sys.argv) > 1:
    db_type = sys.argv[1].lower()
elif "postgres" in os.environ.get("DATABASE_URL", ""):
    db_type = "postgresql"

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL)


def run_sqlite():
    print("[migrate] Running SQLite migrations...")
    with Session(engine) as s:
        # Existing tables are created by init_db, but we add missing columns here
        columns = {
            "posts": ["bumped_at", "is_pinned"],
            "users": ["profile_image"],
            "novels": ["visibility", "cover_image"],
        }
        for table, cols in columns.items():
            for col in cols:
                try:
                    s.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} TEXT"))
                    print(f"  + Added {table}.{col}")
                except Exception:
                    print(f"  ~ {table}.{col} already exists")
        s.commit()
    print("[migrate] SQLite migrations complete.")


def run_postgresql():
    print("[migrate] Running PostgreSQL migrations...")
    with Session(engine) as s:
        columns = {
            "posts": [
                ("bumped_at", "TIMESTAMP"),
                ("is_pinned", "BOOLEAN DEFAULT FALSE"),
            ],
            "users": [
                ("profile_image", "VARCHAR(512) DEFAULT ''"),
            ],
            "novels": [
                ("visibility", "VARCHAR(16) DEFAULT 'public'"),
                ("cover_image", "VARCHAR(512) DEFAULT ''"),
            ],
        }
        for table, cols in columns.items():
            for col_name, col_type in cols:
                try:
                    s.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
                    print(f"  + Added {table}.{col_name}")
                except Exception as e:
                    print(f"  ~ {table}.{col_name}: {e}")
        s.commit()
    print("[migrate] PostgreSQL migrations complete.")


if __name__ == "__main__":
    if db_type == "postgresql":
        run_postgresql()
    else:
        run_sqlite()
    print("[migrate] Done.")

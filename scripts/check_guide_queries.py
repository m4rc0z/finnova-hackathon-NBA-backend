"""
Execute every ```sql block of a guide against the SQLite database and report rows and timing.
Keeps DATABASE_AGENT_GUIDE_REAL_DATA.md honest: a query that no longer runs fails the check.

Usage:  python scripts/check_guide_queries.py [--guide DATABASE_AGENT_GUIDE_REAL_DATA.md] [--db data/nba_marketplace_real.db]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path


def blocks(md: str) -> list[tuple[str, str]]:
    """(nearest heading, sql) for every fenced sql block."""
    out, heading = [], ""
    for part in re.split(r"(```sql\n.*?```)", md, flags=re.S):
        if part.startswith("```sql"):
            out.append((heading, part[len("```sql\n"):-3].strip()))
        else:
            heads = re.findall(r"^#{2,4} (.+)$", part, flags=re.M)
            if heads:
                heading = heads[-1]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--guide", default="DATABASE_AGENT_GUIDE_REAL_DATA.md")
    ap.add_argument("--db", default="data/nba_marketplace_real.db")
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    failures = 0
    for heading, sql in blocks(Path(args.guide).read_text(encoding="utf-8")):
        t0 = time.perf_counter()
        try:
            rows = con.execute(sql).fetchall()
            ms = (time.perf_counter() - t0) * 1000
            print(f"OK   {len(rows):6d} rows {ms:8.1f} ms | {heading}")
            if rows:
                print(f"     first row: {rows[0]}"[:220])
        except sqlite3.Error as e:
            failures += 1
            print(f"FAIL {heading}: {e}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

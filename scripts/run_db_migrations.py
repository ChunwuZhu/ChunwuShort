#!/usr/bin/env python3
"""Run idempotent database migrations for the project."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.db_migrations import run_migrations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-init-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_migrations(initialize_tables=not args.skip_init_db)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return
    print(f"migration_count={result['migration_count']}")
    for item in result["migrations"]:
        print(f"  {item['id']}: {item['description']}")


if __name__ == "__main__":
    main()

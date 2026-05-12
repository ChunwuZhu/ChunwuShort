"""Idempotent database migrations for earnings-options modules."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from utils.db import init_db, engine


MIGRATIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "202605_entry_order_status_columns",
        "description": "Track Moomoo paper entry order fill/status details.",
        "statements": (
            "ALTER TABLE paper_option_order_batch_legs ADD COLUMN IF NOT EXISTS dealt_qty NUMERIC(20,6)",
            "ALTER TABLE paper_option_order_batch_legs ADD COLUMN IF NOT EXISTS dealt_avg_price NUMERIC(20,6)",
            "ALTER TABLE paper_option_order_batch_legs ADD COLUMN IF NOT EXISTS last_err_msg TEXT",
            "ALTER TABLE paper_option_order_batch_legs ADD COLUMN IF NOT EXISTS last_status_at TIMESTAMPTZ",
        ),
    },
    {
        "id": "202605_exit_order_status_columns",
        "description": "Track Moomoo paper exit order fill/status details.",
        "statements": (
            "ALTER TABLE paper_option_exit_order_batch_legs ADD COLUMN IF NOT EXISTS dealt_qty NUMERIC(20,6)",
            "ALTER TABLE paper_option_exit_order_batch_legs ADD COLUMN IF NOT EXISTS dealt_avg_price NUMERIC(20,6)",
            "ALTER TABLE paper_option_exit_order_batch_legs ADD COLUMN IF NOT EXISTS last_err_msg TEXT",
            "ALTER TABLE paper_option_exit_order_batch_legs ADD COLUMN IF NOT EXISTS last_status_at TIMESTAMPTZ",
        ),
    },
    {
        "id": "202605_readiness_news_summary_column",
        "description": "Link data readiness rows to compact news summaries.",
        "statements": (
            "ALTER TABLE earnings_data_readiness ADD COLUMN IF NOT EXISTS news_summary_id INTEGER",
        ),
    },
)


def run_migrations(*, initialize_tables: bool = True) -> dict[str, Any]:
    """Run all known idempotent migrations.

    `init_db()` creates new tables from SQLAlchemy metadata. The ALTER statements
    cover columns added after tables already existed locally.
    """
    if initialize_tables:
        init_db()
    applied = []
    with engine.begin() as conn:
        for migration in MIGRATIONS:
            for statement in migration["statements"]:
                conn.execute(text(statement))
            applied.append({"id": migration["id"], "description": migration["description"]})
    return {"migration_count": len(applied), "migrations": applied}

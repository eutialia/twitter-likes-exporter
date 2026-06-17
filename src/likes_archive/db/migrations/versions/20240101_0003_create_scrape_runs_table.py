"""create scrape_runs table

Revision ID: 0003
Revises: 0002
Create Date: 2024-01-01 00:00:02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("new_tweets", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("pages_fetched", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("scrape_runs_run_at_idx", "scrape_runs", [sa.text("run_at DESC")])


def downgrade() -> None:
    op.drop_index("scrape_runs_run_at_idx", table_name="scrape_runs")
    op.drop_table("scrape_runs")

"""create updated_at trigger for tweets

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-01 00:00:01
"""
from __future__ import annotations

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN NEW.updated_at = now(); RETURN NEW; END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER tweets_set_updated_at
        BEFORE UPDATE ON tweets
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tweets_set_updated_at ON tweets")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at")

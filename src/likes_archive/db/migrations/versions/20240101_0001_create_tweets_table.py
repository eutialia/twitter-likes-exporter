"""create tweets table

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "tweets",
        sa.Column("tweet_id", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("user_handle", sa.Text, nullable=False),
        sa.Column("user_name", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "content_tsv",
            TSVECTOR,
            sa.Computed(
                "to_tsvector('english', coalesce(payload->>'tweet_content', ''))",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "tweets_content_tsv_idx", "tweets", ["content_tsv"], postgresql_using="gin"
    )
    op.execute(
        "CREATE INDEX tweets_content_trgm_idx ON tweets "
        "USING GIN ((payload->>'tweet_content') gin_trgm_ops)"
    )
    op.create_index(
        "tweets_payload_gin_idx", "tweets", ["payload"], postgresql_using="gin"
    )
    op.create_index("tweets_user_id_idx", "tweets", ["user_id"])
    op.create_index("tweets_user_handle_idx", "tweets", ["user_handle"])
    op.execute(
        "CREATE INDEX tweets_user_handle_trgm ON tweets "
        "USING GIN (user_handle gin_trgm_ops)"
    )
    op.create_index("tweets_created_at_idx", "tweets", [sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("tweets_created_at_idx", table_name="tweets")
    op.drop_index("tweets_user_handle_trgm", table_name="tweets")
    op.drop_index("tweets_user_handle_idx", table_name="tweets")
    op.drop_index("tweets_user_id_idx", table_name="tweets")
    op.drop_index("tweets_payload_gin_idx", table_name="tweets")
    op.drop_index("tweets_content_trgm_idx", table_name="tweets")
    op.drop_index("tweets_content_tsv_idx", table_name="tweets")
    op.drop_table("tweets")

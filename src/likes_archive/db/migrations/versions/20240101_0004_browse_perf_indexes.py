"""browse perf indexes — composite keyset + drop unused payload GIN

Revision ID: 0004
Revises: 0003
Create Date: 2024-01-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Keyset pagination orders by (created_at DESC, tweet_id DESC). The old
    # single-column created_at index is replaced by a composite that covers it.
    op.drop_index("tweets_created_at_idx", table_name="tweets")
    op.create_index(
        "tweets_created_at_id_idx",
        "tweets",
        [sa.text("created_at DESC"), sa.text("tweet_id DESC")],
    )
    # Full-payload GIN was never used by browse or search (those use content_tsv
    # + content trigram). It only slowed scrapes that rewrite payload.
    op.drop_index("tweets_payload_gin_idx", table_name="tweets")


def downgrade() -> None:
    op.create_index("tweets_payload_gin_idx", "tweets", ["payload"], postgresql_using="gin")
    op.drop_index("tweets_created_at_id_idx", table_name="tweets")
    op.create_index("tweets_created_at_idx", "tweets", [sa.text("created_at DESC")])

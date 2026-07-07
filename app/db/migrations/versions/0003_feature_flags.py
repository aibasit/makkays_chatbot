"""create feature flags table

Revision ID: 0003_feature_flags
Revises: 0002_conversation_turns
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op

revision = "0003_feature_flags"
down_revision = "0002_conversation_turns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS feature_flags (
          tenant_id UUID NOT NULL,
          flag_name TEXT NOT NULL,
          enabled BOOLEAN NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, flag_name)
        )
        """,
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feature_flags")

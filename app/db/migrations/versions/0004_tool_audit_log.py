"""create tool audit log table

Revision ID: 0004_tool_audit_log
Revises: 0003_feature_flags
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op

revision = "0004_tool_audit_log"
down_revision = "0003_feature_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pgcrypto
        """,
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_audit_log (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          session_id TEXT NOT NULL,
          tool_name TEXT NOT NULL,
          intent TEXT,
          allowed BOOLEAN NOT NULL,
          denial_reason TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tool_audit_log")

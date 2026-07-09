"""add conversation language preference fields

Revision ID: 0011_language_support
Revises: 0010_handoff_requests
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op

revision = "0011_language_support"
down_revision = "0010_handoff_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversation_state ADD COLUMN IF NOT EXISTS language_code TEXT NOT NULL DEFAULT 'en'")
    op.execute(
        "ALTER TABLE conversation_state ADD COLUMN IF NOT EXISTS language_override BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversation_state DROP COLUMN IF EXISTS language_override")
    op.execute("ALTER TABLE conversation_state DROP COLUMN IF EXISTS language_code")

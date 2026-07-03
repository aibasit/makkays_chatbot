"""create conversation turns table

Revision ID: 0002_conversation_turns
Revises: 0001_session_state
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op

revision = "0002_conversation_turns"
down_revision = "0001_session_state"
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
        CREATE TABLE IF NOT EXISTS conversation_turns (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          session_id TEXT NOT NULL,
          turn_number INTEGER NOT NULL,
          user_message TEXT NOT NULL,
          assistant_message TEXT,
          intent TEXT,
          intent_confidence REAL,
          intent_source TEXT,
          candidate_intents TEXT[] DEFAULT '{}',
          prompt_version JSONB,
          tool_calls JSONB,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_turns_session
        ON conversation_turns (tenant_id, session_id, turn_number)
        """,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uidx_turns_session_number
        ON conversation_turns (tenant_id, session_id, turn_number)
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uidx_turns_session_number")
    op.execute("DROP INDEX IF EXISTS idx_conversation_turns_session")
    op.execute("DROP TABLE IF EXISTS conversation_turns")

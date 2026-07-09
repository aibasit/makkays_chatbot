"""create handoff requests and extended qualification columns

Revision ID: 0010_handoff_requests
Revises: 0009_solution_builder
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op

revision = "0010_handoff_requests"
down_revision = "0009_solution_builder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("ALTER TABLE session_facts ADD COLUMN IF NOT EXISTS location TEXT")
    op.execute("ALTER TABLE session_facts ADD COLUMN IF NOT EXISTS timeline TEXT")
    op.execute("ALTER TABLE session_facts ADD COLUMN IF NOT EXISTS is_decision_maker BOOLEAN")
    op.execute("ALTER TABLE conversation_state ADD COLUMN IF NOT EXISTS handoff_target TEXT")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS handoff_requests (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          session_id TEXT NOT NULL,
          reference_id TEXT NOT NULL UNIQUE,
          target_team TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          conversation_export JSONB NOT NULL,
          contact_name TEXT,
          contact_email TEXT,
          contact_phone TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_handoff_session
        ON handoff_requests (tenant_id, session_id, status)
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_handoff_reference
        ON handoff_requests (tenant_id, reference_id)
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_handoff_reference")
    op.execute("DROP INDEX IF EXISTS idx_handoff_session")
    op.execute("DROP TABLE IF EXISTS handoff_requests")
    op.execute("ALTER TABLE conversation_state DROP COLUMN IF EXISTS handoff_target")
    op.execute("ALTER TABLE session_facts DROP COLUMN IF EXISTS is_decision_maker")
    op.execute("ALTER TABLE session_facts DROP COLUMN IF EXISTS timeline")
    op.execute("ALTER TABLE session_facts DROP COLUMN IF EXISTS location")

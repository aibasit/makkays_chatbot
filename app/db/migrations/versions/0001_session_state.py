"""create session facts and conversation state tables

Revision ID: 0001_session_state
Revises:
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op

revision = "0001_session_state"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS session_facts (
          tenant_id UUID NOT NULL,
          session_id TEXT NOT NULL,
          budget NUMERIC,
          company TEXT,
          industry TEXT,
          product_interest TEXT,
          project_size TEXT,
          quantity INTEGER,
          contact_name TEXT,
          contact_email TEXT,
          contact_phone TEXT,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, session_id)
        )
        """,
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_state (
          tenant_id UUID NOT NULL,
          session_id TEXT NOT NULL,
          current_intent TEXT,
          intent_confidence REAL,
          awaiting_clarification BOOLEAN NOT NULL DEFAULT false,
          clarification_candidates TEXT[] NOT NULL DEFAULT '{}',
          clarification_rounds INTEGER NOT NULL DEFAULT 0,
          current_plan JSONB,
          current_plan_step INTEGER,
          last_question TEXT,
          spec_question_detected BOOLEAN NOT NULL DEFAULT false,
          contact_info_captured BOOLEAN NOT NULL DEFAULT false,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, session_id)
        )
        """,
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_state")
    op.execute("DROP TABLE IF EXISTS session_facts")

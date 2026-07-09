"""create wizard sessions, use case profiles, and solutions tables

Revision ID: 0009_solution_builder
Revises: 0008_product_intelligence
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op

revision = "0009_solution_builder"
down_revision = "0008_product_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wizard_sessions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          session_id TEXT NOT NULL,
          current_step INTEGER NOT NULL DEFAULT 0,
          collected_requirements JSONB NOT NULL DEFAULT '{}',
          completed BOOLEAN NOT NULL DEFAULT false,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wizard_session
        ON wizard_sessions (tenant_id, session_id) WHERE completed = false
        """,
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS use_case_profiles (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          use_case TEXT NOT NULL,
          requirements JSONB NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_use_case_profile
        ON use_case_profiles (tenant_id, use_case)
        """,
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS solutions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          session_id TEXT NOT NULL,
          use_case TEXT,
          requirements JSONB NOT NULL,
          line_items JSONB NOT NULL,
          total_estimate NUMERIC(12,2),
          currency TEXT NOT NULL DEFAULT 'USD',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS solutions")
    op.execute("DROP INDEX IF EXISTS idx_use_case_profile")
    op.execute("DROP TABLE IF EXISTS use_case_profiles")
    op.execute("DROP INDEX IF EXISTS idx_wizard_session")
    op.execute("DROP TABLE IF EXISTS wizard_sessions")

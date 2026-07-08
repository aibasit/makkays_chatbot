"""create quote pricing and quote tables

Revision ID: 0006_quotes
Revises: 0005_rag_catalog
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op

revision = "0006_quotes"
down_revision = "0005_rag_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS product_pricing (
          product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          tenant_id UUID NOT NULL,
          unit_price NUMERIC NOT NULL,
          currency TEXT NOT NULL DEFAULT 'USD',
          PRIMARY KEY (product_id, tenant_id)
        )
        """,
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS quotes (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          session_id TEXT NOT NULL,
          company TEXT NOT NULL,
          line_items JSONB NOT NULL,
          total NUMERIC NOT NULL,
          currency TEXT NOT NULL DEFAULT 'USD',
          pdf_bytes BYTEA,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_quotes_tenant ON quotes (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_quotes_session ON quotes (tenant_id, session_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_quotes_session")
    op.execute("DROP INDEX IF EXISTS idx_quotes_tenant")
    op.execute("DROP TABLE IF EXISTS quotes")
    op.execute("DROP TABLE IF EXISTS product_pricing")

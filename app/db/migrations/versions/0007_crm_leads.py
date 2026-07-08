"""create crm lead and retry queue tables

Revision ID: 0007_crm_leads
Revises: 0006_quotes
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op

revision = "0007_crm_leads"
down_revision = "0006_quotes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          session_id TEXT NOT NULL,
          contact_name TEXT,
          contact_email TEXT,
          contact_phone TEXT,
          company TEXT,
          product_interest TEXT,
          message TEXT,
          status TEXT NOT NULL DEFAULT 'new',
          assigned_to TEXT,
          qualification JSONB NOT NULL DEFAULT '{}'::jsonb,
          facts_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant ON leads (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_session ON leads (tenant_id, session_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retry_queue (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
          payload JSONB NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          next_retry_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          last_error TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_retry_queue_tenant ON retry_queue (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_retry_queue_lead ON retry_queue (lead_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_retry_queue_due ON retry_queue (status, next_retry_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_retry_queue_due")
    op.execute("DROP INDEX IF EXISTS idx_retry_queue_lead")
    op.execute("DROP INDEX IF EXISTS idx_retry_queue_tenant")
    op.execute("DROP TABLE IF EXISTS retry_queue")
    op.execute("DROP INDEX IF EXISTS idx_leads_session")
    op.execute("DROP INDEX IF EXISTS idx_leads_tenant")
    op.execute("DROP TABLE IF EXISTS leads")

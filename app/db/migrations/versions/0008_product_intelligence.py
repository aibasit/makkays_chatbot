"""create compatibility rules and accessory relations tables

Revision ID: 0008_product_intelligence
Revises: 0007_crm_leads
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op

revision = "0008_product_intelligence"
down_revision = "0007_crm_leads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compatibility_rules (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          primary_product_id UUID NOT NULL REFERENCES products(id),
          secondary_product_id UUID NOT NULL REFERENCES products(id),
          compatibility_type TEXT NOT NULL,
          is_compatible BOOLEAN NOT NULL,
          notes TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_compat_rules_lookup
        ON compatibility_rules (tenant_id, primary_product_id, compatibility_type)
        """,
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS accessory_relations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          primary_product_id UUID NOT NULL REFERENCES products(id),
          accessory_product_id UUID NOT NULL REFERENCES products(id),
          relation_type TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_accessory_lookup
        ON accessory_relations (tenant_id, primary_product_id, relation_type)
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_accessory_lookup")
    op.execute("DROP TABLE IF EXISTS accessory_relations")
    op.execute("DROP INDEX IF EXISTS idx_compat_rules_lookup")
    op.execute("DROP TABLE IF EXISTS compatibility_rules")

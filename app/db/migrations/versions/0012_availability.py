"""create product availability table

Revision ID: 0012_availability
Revises: 0011_language_support
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op

revision = "0012_availability"
down_revision = "0011_language_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS product_availability (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          quantity INTEGER NOT NULL DEFAULT 0,
          in_stock BOOLEAN GENERATED ALWAYS AS (quantity > 0) STORED,
          estimated_delivery_days INTEGER,
          last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
          source TEXT NOT NULL DEFAULT 'manual',
          CONSTRAINT uidx_product_availability_tenant_product UNIQUE (tenant_id, product_id),
          CONSTRAINT chk_product_availability_quantity_nonnegative CHECK (quantity >= 0),
          CONSTRAINT chk_product_availability_delivery_nonnegative
            CHECK (estimated_delivery_days IS NULL OR estimated_delivery_days >= 0)
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_product_availability_tenant
        ON product_availability (tenant_id)
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_product_availability_tenant")
    op.execute("DROP TABLE IF EXISTS product_availability")

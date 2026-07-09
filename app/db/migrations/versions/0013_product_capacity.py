"""add structured capacity columns to products

Revision ID: 0013_product_capacity
Revises: 0012_availability
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op

revision = "0013_product_capacity"
down_revision = "0012_availability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS capacity_min NUMERIC")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS capacity_max NUMERIC")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS capacity_unit TEXT")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_products_capacity
        ON products (tenant_id, capacity_unit, capacity_min, capacity_max)
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_products_capacity")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS capacity_unit")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS capacity_max")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS capacity_min")

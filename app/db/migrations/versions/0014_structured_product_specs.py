"""add unit-specific structured spec columns to products

Revision ID: 0014_structured_product_specs
Revises: 0013_product_capacity
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op

revision = "0014_structured_product_specs"
down_revision = "0013_product_capacity"
branch_labels = None
depends_on = None

_NUMERIC_COLUMNS = (
    "capacity_kva",
    "rated_power_kw",
    "power_factor",
    "current_a",
    "voltage_class_v",
    "nominal_voltage_vdc",
    "capacity_ah",
    "energy_kwh",
    "max_discharge_power_kw",
    "service_life_years",
)
_INT_COLUMNS = ("phase_input_count", "phase_output_count", "max_parallel_units")


def upgrade() -> None:
    for column in _NUMERIC_COLUMNS:
        op.execute(f"ALTER TABLE products ADD COLUMN IF NOT EXISTS {column} NUMERIC")
    for column in _INT_COLUMNS:
        op.execute(f"ALTER TABLE products ADD COLUMN IF NOT EXISTS {column} INTEGER")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_products_capacity_kva
        ON products (tenant_id, capacity_kva)
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_products_phase
        ON products (tenant_id, phase_input_count, phase_output_count)
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_products_phase")
    op.execute("DROP INDEX IF EXISTS idx_products_capacity_kva")
    for column in _INT_COLUMNS:
        op.execute(f"ALTER TABLE products DROP COLUMN IF EXISTS {column}")
    for column in reversed(_NUMERIC_COLUMNS):
        op.execute(f"ALTER TABLE products DROP COLUMN IF EXISTS {column}")

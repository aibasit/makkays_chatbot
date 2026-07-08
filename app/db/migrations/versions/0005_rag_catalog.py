"""create RAG product and document metadata tables

Revision ID: 0005_rag_catalog
Revises: 0004_tool_audit_log
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op

revision = "0005_rag_catalog"
down_revision = "0004_tool_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          name TEXT NOT NULL,
          brand TEXT,
          category TEXT,
          description TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS product_specs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          tenant_id UUID NOT NULL,
          spec_key TEXT NOT NULL,
          spec_value TEXT NOT NULL
        )
        """,
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL,
          product_id UUID REFERENCES products(id) ON DELETE SET NULL,
          title TEXT NOT NULL,
          source_path TEXT NOT NULL,
          document_type TEXT NOT NULL DEFAULT 'technical_doc',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_products_tenant_category_brand
        ON products (tenant_id, category, brand)
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_product_specs_lookup
        ON product_specs (tenant_id, spec_key, spec_value)
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_documents_tenant_type
        ON documents (tenant_id, document_type)
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_documents_tenant_type")
    op.execute("DROP INDEX IF EXISTS idx_product_specs_lookup")
    op.execute("DROP INDEX IF EXISTS idx_products_tenant_category_brand")
    op.execute("DROP TABLE IF EXISTS documents")
    op.execute("DROP TABLE IF EXISTS product_specs")
    op.execute("DROP TABLE IF EXISTS products")

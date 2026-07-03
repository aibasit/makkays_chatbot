"""Idempotent local development seed script for Module 02."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from app.dependencies import get_settings


CREATE_CRM_SCHEMA_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'lead_status') THEN
        CREATE TYPE lead_status AS ENUM ('New', 'Contacted', 'Qualified', 'Closed');
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS crm_leads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  phone TEXT,
  company TEXT,
  product_interest TEXT,
  message TEXT,
  status lead_status NOT NULL DEFAULT 'New',
  assigned_to TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crm_leads_tenant_status ON crm_leads (tenant_id, status);
"""

INSERT_LOCAL_DEV_LEAD_SQL = """
INSERT INTO crm_leads (tenant_id, name, email, message)
SELECT :tenant_id, 'Local Dev Lead', 'local-dev-lead@example.com', 'Seeded local development lead'
WHERE NOT EXISTS (
    SELECT 1
    FROM crm_leads
    WHERE tenant_id = :tenant_id
      AND email = 'local-dev-lead@example.com'
);
"""


def seed_local_dev() -> None:
    """Create the documented local CRM schema and seed DEFAULT_TENANT_ID once synchronously."""
    settings = get_settings()
    engine = create_engine(settings.db.supabase_db_url_sync.get_secret_value())
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        connection.execute(text(CREATE_CRM_SCHEMA_SQL))
        connection.execute(
            text(INSERT_LOCAL_DEV_LEAD_SQL),
            {"tenant_id": settings.db.default_tenant_id},
        )
    engine.dispose()


def main() -> None:
    """Run the local development seed workflow."""
    seed_local_dev()


if __name__ == "__main__":
    main()

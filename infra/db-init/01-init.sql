-- Runs once on first db container start (local dev). Migrations own the schema; this only
-- enables extensions and creates the low-privilege runtime roles (A-TO-Z-PLAN.md §F.2).
-- Managed environments (Neon) create these out-of-band; CI does it in a workflow step.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'seo_app') THEN
    CREATE ROLE seo_app LOGIN PASSWORD 'seo_app_dev' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'seo_readonly') THEN
    CREATE ROLE seo_readonly LOGIN PASSWORD 'seo_ro_dev' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO seo_app, seo_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO seo_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO seo_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO seo_app;

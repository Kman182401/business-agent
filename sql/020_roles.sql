-- Create database roles for application ownership and runtime access.
-- Replace the placeholder passwords before executing.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT FROM pg_roles WHERE rolname = 'app_owner'
  ) THEN
    CREATE ROLE app_owner LOGIN PASSWORD 'nhwsQOWoQTYjzftSs8u7QEb4XNOFlxrV';
  END IF;

  IF NOT EXISTS (
    SELECT FROM pg_roles WHERE rolname = 'app_user'
  ) THEN
    CREATE ROLE app_user LOGIN PASSWORD 'dTEUhfeG1JKl/CjH/nTpRx4Za0gU0kL6';
  END IF;
END$$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app_user;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app_user;

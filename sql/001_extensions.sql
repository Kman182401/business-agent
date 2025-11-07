-- Enable required extensions for the Front Desk reservation database.
CREATE EXTENSION IF NOT EXISTS pgcrypto;          -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS btree_gist;        -- equality for GiST exclusion constraints
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

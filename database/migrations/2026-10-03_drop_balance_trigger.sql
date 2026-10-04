-- Drop the trigger that added each account transaction to the balance of its
-- account. Account.add_transaction now updates the balance itself, so a
-- database that keeps the trigger counts every transaction twice, and the
-- framework refuses to use it. Run once against a PostgreSQL database created
-- from the former schema.sql; databases created by the framework never have
-- the trigger.
--
--   psql "$DSN" -v ON_ERROR_STOP=1 -f 2026-10-03_drop_balance_trigger.sql

BEGIN;

DROP TRIGGER IF EXISTS balance_update ON account_transactions;

DROP FUNCTION IF EXISTS update_balance();

COMMIT;

-- Rename the columns whose names were inconsistent with the rest of the
-- schema, and the objects that depend on those names. Run once against a
-- database created from an earlier schema.sql; new databases already use these
-- names. Independent of 2026-09-28_unify_model_column_names.sql.
--
--   psql "$DSN" -v ON_ERROR_STOP=1 -f 2026-09-28_unify_schema_column_names.sql

BEGIN;

ALTER TABLE algo_run RENAME COLUMN algo_env TO env;

ALTER TABLE stock_ohlc RENAME COLUMN symbol_id TO stock_ohlc_id;

-- Match the sequence name that schema.sql gives new databases.
ALTER SEQUENCE stock_ohlc_symbol_id_seq RENAME TO stock_ohlc_stock_ohlc_id_seq;

ALTER TABLE accounts RENAME COLUMN modified_tstamp TO modify_tstamp;

-- The balance trigger writes the renamed column.
CREATE OR REPLACE FUNCTION update_balance()
    RETURNS TRIGGER
    LANGUAGE PLPGSQL
    AS
$$
DECLARE
    negative bool;
    b float;
    credit float;
BEGIN
    SELECT
        allow_negative,
        balance,
        credit_line
    FROM
        accounts
    WHERE
        account_id = NEW .account_id
    INTO negative, b, credit;

    UPDATE
        accounts
    SET
        balance = balance + NEW .amount,
        modify_tstamp = 'now()'
    WHERE
        account_id = NEW .account_id;

    RETURN NEW;

END;
$$;

COMMIT;

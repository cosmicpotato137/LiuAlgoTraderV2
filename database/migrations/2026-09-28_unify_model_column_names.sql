-- Rename the columns whose names differed from the model attributes in
-- liualgotrader/db/models. Run once against a database created from an earlier
-- schema.sql; new databases already use these names.
--
--   psql "$DSN" -v ON_ERROR_STOP=1 -f 2026-09-28_unify_model_column_names.sql

BEGIN;

ALTER TABLE algo_run RENAME COLUMN algo_name TO strategy_name;

ALTER TABLE algo_run RENAME COLUMN ref_algo_run TO ref_algo_run_id;

ALTER TABLE portfolio RENAME COLUMN size TO portfolio_size;

ALTER TABLE portfolio RENAME COLUMN assets TO asset_type;

ALTER TABLE trade_analysis RENAME COLUMN start_tstamp TO start_time;

ALTER TABLE trade_analysis RENAME COLUMN end_tstamp TO end_time;

COMMIT;

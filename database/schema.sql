CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE trade_operation AS ENUM ('buy', 'sell', 'sell_short', 'buy_short');

CREATE TYPE trade_env AS ENUM ('PAPER', 'PROD');

CREATE TYPE asset_type AS ENUM ('US_EQUITIES', 'CRYPTO');

CREATE SEQUENCE IF NOT EXISTS transaction_id_seq START 1;

CREATE TABLE IF NOT EXISTS algo_run (
    algo_run_id serial PRIMARY KEY,
    strategy_name text NOT NULL,
    env text NOT NULL,
    build_number text NOT NULL,
    parameters jsonb,
    start_time timestamp DEFAULT current_timestamp,
    end_time timestamp,
    end_reason text,
    batch_id text NOT NULL DEFAULT '',
    ref_algo_run_id integer REFERENCES algo_run(algo_run_id)
);

CREATE INDEX ON algo_run(batch_id);

CREATE INDEX ON algo_run(start_time);

CREATE TABLE IF NOT EXISTS new_trades (
    trade_id serial PRIMARY KEY,
    algo_run_id integer NOT NULL REFERENCES algo_run(algo_run_id),
    symbol text NOT NULL,
    operation trade_operation NOT NULL,
    qty numeric (24, 10) NOT NULL,
    price decimal (8, 2) NOT NULL,
    indicators jsonb NOT NULL,
    client_time text,
    tstamp timestamp DEFAULT current_timestamp,
    stop_price decimal (8, 2),
    target_price decimal (8, 2),
    expire_tstamp timestamp,
    trade_fee numeric (9, 2) NOT NULL DEFAULT 0.0
);

CREATE INDEX ON new_trades(symbol);

CREATE INDEX ON new_trades(algo_run_id);

CREATE INDEX ON new_trades(tstamp);

CREATE TABLE IF NOT EXISTS ticker_data (
    symbol text PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL,
    tags text [ ],
    similar_tickers text [ ],
    industry text,
    sector text,
    exchange text,
    short_ratio float,
    create_tstamp timestamp DEFAULT current_timestamp,
    modify_tstamp timestamp
);

CREATE INDEX ON ticker_data(sector);

CREATE INDEX ON ticker_data(industry);

CREATE INDEX ON ticker_data(tags);

CREATE INDEX ON ticker_data(similar_tickers);

CREATE TABLE IF NOT EXISTS trending_tickers (
    trending_id serial PRIMARY KEY,
    batch_id text NOT NULL,
    symbol text NOT NULL,
    create_tstamp timestamp with time zone DEFAULT current_timestamp,
    scanner_name text NOT NULL DEFAULT 'momentum'
);

CREATE INDEX ON trending_tickers(batch_id);

CREATE INDEX IF NOT EXISTS trending_tickers_scanner_idx ON trending_tickers(scanner_name);

CREATE INDEX IF NOT EXISTS trending_tickers_tstamp_idx ON trending_tickers(create_tstamp);

INSERT INTO
    trending_tickers (symbol, batch_id)
SELECT
    distinct t.symbol,
    r.batch_id
FROM
    new_trades AS t,
    algo_run AS r
WHERE
    t.algo_run_id = r.algo_run_id
    AND batch_id != '';

CREATE TABLE IF NOT EXISTS stock_ohlc (
    stock_ohlc_id serial PRIMARY KEY,
    symbol text NOT NULL,
    symbol_date date NOT NULL,
    open float NOT NULL,
    high float NOT NULL,
    low float NOT NULL,
    close float NOT NULL,
    volume int NOT NULL,
    indicators JSONB,
    modify_tstamp timestamp,
    create_tstamp timestamp DEFAULT current_timestamp,
    UNIQUE(symbol, symbol_date)
);

CREATE INDEX ON stock_ohlc(symbol);

CREATE INDEX ON stock_ohlc(symbol_date);

CREATE TABLE IF NOT EXISTS gain_loss (
    gain_loss_id serial PRIMARY KEY,
    symbol text NOT NULL,
    algo_run_id integer NOT NULL REFERENCES algo_run(algo_run_id),
    gain_percentage decimal (5, 2) NOT NULL,
    gain_value decimal (8, 2) NOT NULL,
    tstamp timestamp DEFAULT current_timestamp,
    UNIQUE(symbol, algo_run_id)
);

CREATE INDEX ON gain_loss(symbol, algo_run_id);

CREATE TABLE IF NOT EXISTS trade_analysis (
    trade_analysis_id serial PRIMARY KEY,
    symbol text NOT NULL,
    algo_run_id integer NOT NULL REFERENCES algo_run(algo_run_id),
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    gain_percentage decimal (5, 2) NOT NULL,
    gain_value decimal (8, 2) NOT NULL,
    r_units decimal(4, 2),
    tstamp timestamp with time zone DEFAULT current_timestamp,
    UNIQUE(symbol, algo_run_id, start_time)
);

CREATE TABLE IF NOT EXISTS optimizer_run (
    optimizer_run_id serial PRIMARY KEY,
    optimizer_session_id text NOT NULL,
    batch_id text NOT NULL,
    tstamp timestamp with time zone DEFAULT current_timestamp,
    parameters text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS optimizer_run_idx ON optimizer_run(optimizer_session_id);

CREATE TABLE IF NOT EXISTS keystore (
    key text PRIMARY KEY,
    value text NOT NULL,
    tstamp timestamp with time zone DEFAULT current_timestamp
);

--------------
-- Accounts --
--------------

CREATE TABLE IF NOT EXISTS accounts (
    account_id serial PRIMARY KEY,
    balance float NOT NULL DEFAULT 0.0,
    allow_negative bool NOT NULL DEFAULT FALSE,
    credit_line float NOT NULL DEFAULT 0. CHECK (credit_line > 0 or not allow_negative ),
    details JSONB,
    create_tstamp timestamp with time zone DEFAULT current_timestamp,
    modify_tstamp timestamp with time zone
);

CREATE TABLE IF NOT EXISTS account_transactions (
    transaction_id serial PRIMARY KEY,
    account_id SERIAL REFERENCES accounts(account_id),
    amount float NOT NULL,
    details JSONB,
    tstamp timestamp with time zone DEFAULT current_timestamp,
    create_tstamp timestamp with time zone DEFAULT current_timestamp
);

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

CREATE
    TRIGGER balance_update
BEFORE
    INSERT OR UPDATE
ON
    account_transactions FOR EACH ROW EXECUTE PROCEDURE update_balance();

---------------
-- Portfolio --
---------------

CREATE TABLE IF NOT EXISTS portfolio (
    portfolio_id text PRIMARY KEY,
    portfolio_size int NOT NULL,
    parameters JSONB,
    expire_tstamp timestamp with time zone,
    tstamp timestamp with time zone DEFAULT current_timestamp,
    account_id int REFERENCES accounts(account_id),
    asset_type asset_type NOT NULL DEFAULT 'US_EQUITIES',
    external_account_id text,
    broker text
);

CREATE INDEX IF NOT EXISTS portfolio_idx ON portfolio(account_id);

CREATE TABLE IF NOT EXISTS portfolio_batch_ids (
    assoc_id serial PRIMARY KEY,
    portfolio_id text NOT NULL REFERENCES portfolio(portfolio_id),
    batch_id text NOT NULL
);

CREATE INDEX ON portfolio_batch_ids(batch_id);

CREATE INDEX ON portfolio_batch_ids(portfolio_id);

CREATE TABLE IF NOT EXISTS trade_plan (
    trade_plan_id uuid DEFAULT uuid_generate_v4 (),
    portfolio_id text NOT NULL REFERENCES portfolio(portfolio_id),
    start_date date NOT NULL,
    strategy_name text NOT NULL,
    parameters JSONB,
    create_tstamp timestamp with time zone DEFAULT current_timestamp,
    modify_tstamp timestamp with time zone,
    expire_tstamp timestamp with time zone,
    PRIMARY KEY (trade_plan_id)
);

CREATE FUNCTION update_modify_tstamp_action()
RETURNS TRIGGER AS $$
BEGIN
    NEW.modify_tstamp = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_trade_plan_modify_tstamp
    BEFORE UPDATE
    ON
        trade_plan
    FOR EACH ROW
EXECUTE PROCEDURE update_modify_tstamp_action();

CREATE TABLE IF NOT EXISTS trade_plan_execution_audit (
    execution_id serial PRIMARY KEY,
    trade_plan_id uuid REFERENCES trade_plan(trade_plan_id),
    details JSONB,
    started_on timestamp with time zone DEFAULT current_timestamp,
    ended_on timestamp with time zone DEFAULT current_timestamp
);

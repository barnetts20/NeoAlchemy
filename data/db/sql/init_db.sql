-- ======================================================
-- TimescaleDB schema for Alchemy trading project
-- ======================================================

-- -------------------------
-- 1. Assets table
-- -------------------------
CREATE TABLE IF NOT EXISTS assets (
    asset_id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,        -- "AAPL", "BTC/USD"
    asset_type TEXT NOT NULL,            -- 'stock' | 'crypto'
    name TEXT,                           -- Optional display name
    exchange TEXT,                       -- NASDAQ, NYSE, CRYPTO, etc
    currency TEXT,                       -- USD, USDT, etc (useful later)
    tradable BOOLEAN DEFAULT TRUE,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE assets
ADD CONSTRAINT asset_type_check
CHECK (asset_type IN ('stock', 'crypto'));
INSERT INTO assets (symbol, asset_type, name, exchange, currency)
VALUES
  ('AAPL', 'stock', 'Apple Inc', 'NASDAQ', 'USD'),
  ('VGT', 'stock', 'Vanguard Tech ETF', 'NASDAQ', 'USD'),
  ('BTC/USD', 'crypto', 'Bitcoin', 'ALPACA', 'USD');
-- -------------------------
-- 2. 1-minute OHLCV bars
-- -------------------------
CREATE TABLE IF NOT EXISTS stock_candles_1m (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume BIGINT,
    trade_count BIGINT,
    vwap NUMERIC,
    PRIMARY KEY (symbol, ts)
);

SELECT create_hypertable('stock_candles_1m', 'ts', chunk_time_interval => interval '7 days', if_not_exists => TRUE);

-- Enable compression for old 1m data
ALTER TABLE stock_candles_1m SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'ts DESC',
    timescaledb.compress_segmentby = 'symbol'
);

-- SELECT add_compression_policy('stock_candles_1m', INTERVAL '30 days');

-- Example retention: keep raw 1m bars for 1 year
-- SELECT add_retention_policy('stock_candles_1m', INTERVAL '1 year');

-- -------------------------
-- 3. 5-minute OHLCV bars
-- -------------------------
CREATE TABLE IF NOT EXISTS stock_candles_5m (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume BIGINT,
    trade_count BIGINT,
    vwap NUMERIC,
    PRIMARY KEY (symbol, ts)
);

SELECT create_hypertable('stock_candles_5m', 'ts', chunk_time_interval => interval '30 days', if_not_exists => TRUE);

ALTER TABLE stock_candles_5m SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'ts DESC',
    timescaledb.compress_segmentby = 'symbol'
);

-- SELECT add_compression_policy('stock_candles_5m', INTERVAL '90 days');

-- -------------------------
-- 4. 1-hour OHLCV bars
-- -------------------------
CREATE TABLE IF NOT EXISTS stock_candles_1h (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume BIGINT,
    trade_count BIGINT,
    vwap NUMERIC,
    PRIMARY KEY (symbol, ts)
);

SELECT create_hypertable('stock_candles_1h', 'ts', chunk_time_interval => interval '90 days', if_not_exists => TRUE);

ALTER TABLE stock_candles_1h SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'ts DESC',
    timescaledb.compress_segmentby = 'symbol'
);

-- SELECT add_compression_policy('stock_candles_1h', INTERVAL '180 days');

-- -------------------------
-- 5. 1-day OHLCV bars
-- -------------------------
CREATE TABLE IF NOT EXISTS stock_candles_1d (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume BIGINT,
    trade_count BIGINT,
    vwap NUMERIC,
    PRIMARY KEY (symbol, ts)
);

SELECT create_hypertable('stock_candles_1d', 'ts', chunk_time_interval => interval '1 month', if_not_exists => TRUE);

ALTER TABLE stock_candles_1d SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'ts DESC',
    timescaledb.compress_segmentby = 'symbol'
);

-- Compress 1d data older than 1 year
-- SELECT add_compression_policy('stock_candles_1d', INTERVAL '365 days');

-- -------------------------
-- 2. 1-minute OHLCV bars
-- -------------------------
CREATE TABLE IF NOT EXISTS crypto_candles_1m (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume NUMERIC,
    trade_count BIGINT,
    vwap NUMERIC,
    PRIMARY KEY (symbol, ts)
);

SELECT create_hypertable('crypto_candles_1m', 'ts', chunk_time_interval => interval '7 days', if_not_exists => TRUE);

-- Enable compression for old 1m data
ALTER TABLE crypto_candles_1m SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'ts DESC',
    timescaledb.compress_segmentby = 'symbol'
);

-- SELECT add_compression_policy('crypto_candles_1m', INTERVAL '30 days');

-- Example retention: keep raw 1m bars for 1 year
-- SELECT add_retention_policy('crypto_candles_1m', INTERVAL '1 year');

-- -------------------------
-- 3. 5-minute OHLCV bars
-- -------------------------
CREATE TABLE IF NOT EXISTS crypto_candles_5m (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume NUMERIC,
    trade_count BIGINT,
    vwap NUMERIC,
    PRIMARY KEY (symbol, ts)
);

SELECT create_hypertable('crypto_candles_5m', 'ts', chunk_time_interval => interval '30 days', if_not_exists => TRUE);

ALTER TABLE crypto_candles_5m SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'ts DESC',
    timescaledb.compress_segmentby = 'symbol'
);

-- SELECT add_compression_policy('crypto_candles_5m', INTERVAL '90 days');

-- -------------------------
-- 4. 1-hour OHLCV bars
-- -------------------------
CREATE TABLE IF NOT EXISTS crypto_candles_1h (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume NUMERIC,
    trade_count BIGINT,
    vwap NUMERIC,
    PRIMARY KEY (symbol, ts)
);

SELECT create_hypertable('crypto_candles_1h', 'ts', chunk_time_interval => interval '90 days', if_not_exists => TRUE);

ALTER TABLE crypto_candles_1h SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'ts DESC',
    timescaledb.compress_segmentby = 'symbol'
);

-- SELECT add_compression_policy('crypto_candles_1h', INTERVAL '180 days');

-- -------------------------
-- 5. 1-day OHLCV bars
-- -------------------------
CREATE TABLE IF NOT EXISTS crypto_candles_1d (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume NUMERIC,
    trade_count BIGINT,
    vwap NUMERIC,
    PRIMARY KEY (symbol, ts)
);

SELECT create_hypertable('crypto_candles_1d', 'ts', chunk_time_interval => interval '1 month', if_not_exists => TRUE);

ALTER TABLE crypto_candles_1d SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'ts DESC',
    timescaledb.compress_segmentby = 'symbol'
);

-- Compress 1d data older than 1 year
-- SELECT add_compression_policy('crypto_candles_1d', INTERVAL '365 days');

-- Optional retention: keep daily bars indefinitely or set policy if desired
-- SELECT add_retention_policy('crypto_candles_1d', INTERVAL '10 years');

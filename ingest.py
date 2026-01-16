import asyncio
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from dateutil.relativedelta import relativedelta
from typing import List, Optional, Tuple
import selectors # Add this import at the top
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame 
from db_connection import get_conn 
from project_context import STOCK_HISTORIC_DATA_CLIENT, CRYPTO_HISTORIC_DATA_CLIENT
from psycopg import AsyncConnection
from logger import logger

# --- Constants ---
TIMEFRAMES = [TimeFrame.Day, TimeFrame.Hour, TimeFrame.Minute5, TimeFrame.Minute]

# Map asset_type + timeframe to table name
TABLE_MAP = {
    "stock": {"1D": "stock_candles_1d", "1H": "stock_candles_1h", "1M": "stock_candles_1m", "5M": "stock_candles_5m"},
    "crypto": {"1D": "crypto_candles_1d", "1H": "crypto_candles_1h", "1M": "crypto_candles_1m", "5M": "crypto_candles_5m"}
}

# --- Utilities ---
def get_tf_key(tf: TimeFrame) -> str:
    if tf.unit.name == "Day": return "1D"
    if tf.unit.name == "Hour": return "1H"
    return f"{tf.amount}M"

def timeframe_delta(tf: TimeFrame) -> timedelta:
    mapping = {"Day": timedelta(days=tf.amount), "Hour": timedelta(hours=tf.amount), "Minute": timedelta(minutes=tf.amount)}
    return mapping.get(tf.unit.name, timedelta(minutes=1))

def get_table(asset_type: str, tf: TimeFrame) -> str:
    return TABLE_MAP[asset_type][get_tf_key(tf)]

# --- Database Ops ---
async def get_existing_range(conn: AsyncConnection, asset_type: str, tf: TimeFrame, symbol: str):
    table = get_table(asset_type, tf)
    async with conn.cursor() as cur:
        await cur.execute(f"SELECT MIN(ts), MAX(ts) FROM {table} WHERE symbol = %s;", (symbol,))
        return await cur.fetchone()

async def upsert_bars(conn: AsyncConnection, asset_type: str, tf: TimeFrame, symbol: str, bars: list):
    if not bars: return
    table = get_table(asset_type, tf)
    sql = f"""
        INSERT INTO {table} (symbol, ts, open, high, low, close, volume, trade_count, vwap)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, ts) DO UPDATE SET
            open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,
            volume=EXCLUDED.volume, trade_count=EXCLUDED.trade_count, vwap=EXCLUDED.vwap;
    """
    params = [(symbol, b.timestamp, b.open, b.high, b.low, b.close, b.volume, b.trade_count, b.vwap) for b in bars]
    async with conn.cursor() as cur:
        await cur.executemany(sql, params)
    logger.info(f"Upserted {len(bars)} {asset_type} bars for {symbol} into {table}")

# --- Core Logic ---
async def ingest_chunk(conn: AsyncConnection, asset_type: str, symbol: str, tf: TimeFrame, start: datetime, end: datetime):
    min_ts, max_ts = await get_existing_range(conn, asset_type, tf, symbol)
    
    # Gap Detection
    fetch_ranges = []
    if min_ts is None:
        fetch_ranges.append((start, end))
    else:
        if start < min_ts: fetch_ranges.append((start, min_ts - timeframe_delta(tf)))
        if end > max_ts: fetch_ranges.append((max_ts + timeframe_delta(tf), end))

    if not fetch_ranges: return None

    client = STOCK_HISTORIC_DATA_CLIENT if asset_type == "stock" else CRYPTO_HISTORIC_DATA_CLIENT
    last_processed_ts = None

    for r_start, r_end in fetch_ranges:
        curr = r_start
        while curr <= r_end:
            # Dynamic Request Handling
            if asset_type == "stock":
                req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=curr, end=r_end, limit=5000, adjustment="all")
                res = client.get_stock_bars(req)
            else:
                req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=curr, end=r_end, limit=5000)
                res = client.get_crypto_bars(req)

            bars = res.data.get(symbol, [])
            if not bars: break
            
            await upsert_bars(conn, asset_type, tf, symbol, bars)
            last_processed_ts = bars[-1].timestamp
            curr = last_processed_ts + timeframe_delta(tf)
    
    return last_processed_ts

async def ingest_asset(asset_type: str, symbol: str, tf: TimeFrame, start: datetime, end: datetime):
    async with await get_conn() as conn:
        curr = start
        while curr < end:
            loop_start = time.perf_counter()
            last_ts = await ingest_chunk(conn, asset_type, symbol, tf, curr, end)
            if not last_ts: break
            
            curr = last_ts + timeframe_delta(tf)
            # Rate limit throttle (~200 req/min)
            sleep_time = 0.3 - (time.perf_counter() - loop_start)
            if sleep_time > 0: await asyncio.sleep(sleep_time)

async def main_ingest(asset_type: str):
    async with await get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT symbol FROM assets WHERE asset_type=%s AND active=TRUE;", (asset_type,))
            symbols = [row[0] for row in await cur.fetchall()]

    # Stocks usually have a 15-min delay for free tier, Crypto is usually real-time
    lookback = 16 if asset_type == "stock" else 1
    start_date = datetime.now(timezone.utc) - relativedelta(years=5)
    end_date = datetime.now(timezone.utc) - timedelta(minutes=lookback)

    for symbol in symbols:
        for tf in TIMEFRAMES:
            try:
                await ingest_asset(asset_type, symbol, tf, start_date, end_date)
            except Exception as e:
                logger.error(f"Failed {asset_type} {symbol} {tf}: {e}")

# ... rest of your code ...

if __name__ == "__main__":
    # Windows-specific fix for Psycopg + Asyncio
    if sys.platform == "win32":
        loop_factory = lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
    else:
        loop_factory = None

    try:
        asyncio.run(main_ingest("crypto"), loop_factory=loop_factory)
        asyncio.run(main_ingest("stock"), loop_factory=loop_factory)
    except KeyboardInterrupt:
        logger.info("Ingest interrupted by user")
import asyncio
import os
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..","..",".."))
if PROJECT_ROOT not in sys.path: sys.path.append(PROJECT_ROOT)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame   
from data.db.connection import get_conn 
from datetime import datetime, timezone, timedelta
from dateutil.relativedelta import relativedelta
from typing import List, Optional, Tuple
from project_context import CRYPTO_HISTORIC_DATA_CLIENT as DATA_CLIENT  # Or the crypto client if separate
from psycopg import AsyncConnection
from utils.logger import logger

TIMEFRAMES = [
    TimeFrame.Day,
    TimeFrame.Hour,
    TimeFrame.Minute5,
    TimeFrame.Minute,
]

TIMEFRAME_TABLE_MAP = {
    "1D": "crypto_candles_1d",
    "1H": "crypto_candles_1h",
    "1M": "crypto_candles_1m",
    "5M": "crypto_candles_5m",
}

def timeframe_delta(tf: TimeFrame) -> timedelta:
    if tf.amount == 1 and tf.unit.name == "Day":
        return timedelta(days=1)
    elif tf.amount == 1 and tf.unit.name == "Hour":
        return timedelta(hours=1)
    elif tf.amount == 5 and tf.unit.name == "Minute":
        return timedelta(minutes=5)
    elif tf.amount == 1 and tf.unit.name == "Minute":
        return timedelta(minutes=1)
    else:
        raise ValueError(f"Unsupported timeframe {tf}")

def get_table_for_timeframe(tf) -> str:
    if tf.amount == 1 and tf.unit.name == "Day":
        return TIMEFRAME_TABLE_MAP["1D"]
    elif tf.amount == 1 and tf.unit.name == "Hour":
        return TIMEFRAME_TABLE_MAP["1H"]
    elif tf.amount == 5 and tf.unit.name == "Minute":
        return TIMEFRAME_TABLE_MAP["5M"]
    elif tf.amount == 1 and tf.unit.name == "Minute":
        return TIMEFRAME_TABLE_MAP["1M"]    
    else:
        raise ValueError(f"No table defined for timeframe {tf}")
    
async def get_existing_range(conn: AsyncConnection, timeframe: TimeFrame, symbol: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Return min and max timestamps for a given symbol in crypto_candles_1d."""
    sql = f"""
        SELECT MIN(ts), MAX(ts)
        FROM {get_table_for_timeframe(timeframe)}
        WHERE symbol = %s;
    """
    async with conn.cursor() as cur:
        await cur.execute(sql, (symbol,))
        return await cur.fetchone()

async def upsert_bars(conn: AsyncConnection, timeframe: TimeFrame, symbol:str, bars: list):
    """Upsert a batch of bars into crypto_candles_1d."""
    table = get_table_for_timeframe(timeframe)
    if not bars:
        return
    sql = f"""
        INSERT INTO {table} (symbol, ts, open, high, low, close, volume, trade_count, vwap)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, ts) DO UPDATE
        SET open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            trade_count = EXCLUDED.trade_count,
            vwap = EXCLUDED.vwap;
    """
    async with conn.cursor() as cur:
        await cur.executemany(
            sql,
            [
                (
                    symbol,
                    bar.timestamp,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume, 
                    bar.trade_count,
                    bar.vwap,
                )
                for bar in bars
            ],
        )
    logger.info(f"Upserted {len(bars)} bars for {symbol} into {table}")

async def ingest_chunk(conn: AsyncConnection, symbol: str, timeframe: TimeFrame, start: datetime, end: datetime) -> Optional[datetime]:
    """Ingest daily crypto bars for a symbol into TimescaleDB."""
    min_ts, max_ts = await get_existing_range(conn, timeframe, symbol)

    # Determine what ranges need fetching
    fetch_ranges = []
    bars = []
    if min_ts is None and max_ts is None:
        # No data exists
        fetch_ranges.append((start, end))
    else:
        if start < min_ts:
            fetch_ranges.append((start, min_ts - timeframe_delta(timeframe)))
        if end > max_ts:
            fetch_ranges.append((max_ts + timeframe_delta(timeframe), end))

    if not fetch_ranges:
        logger.info(f"No gaps detected for {symbol}, nothing to ingest")
        return

    for range_start, range_end in fetch_ranges:
        current_start = range_start
        while current_start <= range_end:
            request = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=timeframe,
                start=current_start,
                end=range_end,
                limit=5000,
            )
            req = DATA_CLIENT.get_crypto_bars(request)
            bars = req.data.get(symbol,[])
            if not bars:
                break
            await upsert_bars(conn, timeframe, symbol, bars)

            # Move to next page
            last_ts = bars[-1].timestamp
            current_start = last_ts + timeframe_delta(timeframe)

    logger.info(f"Completed ingest for {symbol} ({start} -> {end})")
    # at the end of ingest_chunk
    if bars:
        return bars[-1].timestamp
    return None

async def ingest_range(symbol: str, timeframe: TimeFrame, start: datetime, end: datetime):
    """Backfills crypto bars from start to end using chunked requests."""
    range_start_time = time.perf_counter()
    async with await get_conn() as conn:
        current_start = start

        while current_start < end:
            cycle_start = time.perf_counter()  # high-precision timestamp
            last_ts = await ingest_chunk(conn, symbol, timeframe, current_start, end)
            if not last_ts:
                logger.info(f"No more data available for {symbol} {timeframe}")
                break

            delta = timeframe_delta(timeframe)
            current_start = last_ts + delta

            execution_time = time.perf_counter() - cycle_start
            sleep_time = .3 - execution_time # rate limit is 200 per minute = 60/200 = .3 sec min turn around to keep under limit
            if sleep_time > 0:
                await asyncio.sleep(sleep_time) # Throttle to avoid hitting API limits
    
    logger.info(
        f"Ingest range complete | symbol={symbol} "
        f"timeframe={timeframe} "
        f"elapsed={time.perf_counter() - range_start_time:.2f}s"
    )

async def get_assets() -> List[str]:
    """Return a list of symbols for all crypto assets."""
    async with await get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT symbol FROM assets WHERE asset_type='crypto' AND active=TRUE;")
            rows = await cur.fetchall()
            return [row[0] for row in rows]

async def ingest():
    """Top-level function to ingest all crypto assets for all timeframes."""
    ingest_start_time = time.perf_counter()
    symbols = await get_assets()
    start_date = datetime.now(timezone.utc) - relativedelta(years=5)
    end_date = datetime.now(timezone.utc)

    for symbol in symbols:         
        logger.info(f"Starting ingest for {symbol}")
        for tf in TIMEFRAMES:
            try:
                logger.info(f"Ingesting timeframe {tf}")
                await ingest_range(symbol, tf, start_date, end_date)
            except Exception as e:
                logger.error(f"Error ingesting {symbol} {tf}: {e}")
    
    logger.info(
        f"Crypto ingest complete | symbols={len(symbols)} "
        f"elapsed={time.perf_counter() - ingest_start_time:.2f}s"
    )

if __name__ == "__main__":
    asyncio.run(ingest())

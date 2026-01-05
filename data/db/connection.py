import os
import sys

import psycopg
import asyncio
import selectors
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",".."))
if PROJECT_ROOT not in sys.path: sys.path.append(PROJECT_ROOT)

from project_context import SETTINGS, SECRETS
from utils.logger import logger

DB_HOST = SETTINGS["db"]["host"]
DB_PORT = SETTINGS["db"]["port"]
DB_NAME = SECRETS["db"]["name"]
DB_USER = SECRETS["db"]["user"]
DB_PASSWORD = SECRETS["db"]["password"]

async def get_conn():
    conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"
    try:
        # This returns an AsyncConnection
        conn = await psycopg.AsyncConnection.connect(conninfo)
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to DB: {e}")
        raise

async def test_connection():
    conn = await get_conn()
    async with conn.cursor() as cur:
        await cur.execute("SELECT now();")
        row = await cur.fetchone()
        print(row)
    await conn.close()

asyncio.run(
    test_connection(),
    loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
)
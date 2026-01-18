from psycopg import AsyncConnection
import os
import asyncio
import selectors
from project_context import SETTINGS, SECRETS
from logger import logger

DB_HOST = SETTINGS["db"]["host"]
DB_PORT = SETTINGS["db"]["port"]
DB_NAME = SECRETS["db"]["name"]
DB_USER = SECRETS["db"]["user"]
DB_PASSWORD = SECRETS["db"]["password"]

async def get_conn() -> AsyncConnection:
    """Get database connection based on environment"""
    
    # Detect environment
    env = os.getenv('ENVIRONMENT', 'local')  # default to 'local'
    
    # Load config
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'db_config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    db_config = config[env]
    
    conn_string = (
        f"postgresql://{db_config['user']}:{db_config['password']}"
        f"@{db_config['host']}:{db_config['port']}/{db_config['database']}"
    )
    
    conn = await AsyncConnection.connect(conn_string)
    return conn

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
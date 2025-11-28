# db_ops.py

import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime

from logs.log_config import apolo_trader_logger as logger
DB_PATH = "data/trading.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # enables dict-like access
    try:
        yield conn
    finally:
        conn.close()

def initialize_database_tables():
    with get_db_connection() as conn:
        cur = conn.cursor()

        # bot_control table (unchanged)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_control (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                is_running BOOLEAN DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("INSERT OR IGNORE INTO bot_control (id, is_running) VALUES (1, 1);")
        
        conn.commit()
        logger.info("✅ SQLite tables initialized.")

# get bot status
def get_bot_status():
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT is_running FROM bot_control WHERE id = 1")
        row = cur.fetchone()
        return bool(row['is_running']) if row else True  # default to True


# start or stop the bot
def startStopBotOp(status: bool):
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE bot_control
            SET is_running = ?
            WHERE id = 1
        """, (int(status),))
        conn.commit()
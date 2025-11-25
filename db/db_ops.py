import os
import sqlite3
import sys
from contextlib import contextmanager

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logs.log_config import binance_trader_logger as logger

# SQLite file path
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

        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                quantity REAL NOT NULL,
                notional_usd REAL,
                status TEXT DEFAULT 'OPEN',
                current_pnl_pct REAL DEFAULT 0.0,
                current_pnl_usd REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                entry_order_id INTEGER,
                tp_order_id INTEGER,
                sl_order_id INTEGER,
                fill_price REAL,
                exchange TEXT
            );
        """)
        
        # table to start or stop the bot
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_control (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                is_running BOOLEAN DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # insert default row if not exists, value 1 means bot is running
        cur.execute("""
            INSERT OR IGNORE INTO bot_control (id, is_running)
            VALUES (1, 1);
        """)
        
        conn.commit()
        print("✅ SQLite tables initialized.")

# ────────────────
# Settings & Positions (same logic, SQLite syntax)
# ────────────────
def insert_position_with_orders(chat_id: int, signal: dict, order_result: dict, exchange: str = "BINANCE"):
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO positions (
                chat_id, symbol, side, entry_price, stop_loss, take_profit,
                quantity, notional_usd,
                entry_order_id, tp_order_id, sl_order_id, exchange
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, (
            chat_id,
            signal['symbol'],
            signal['side'].upper(),
            float(signal['entry']),
            float(signal['stop_loss']),
            float(signal['take_profit']),
            float(order_result['quantity']),
            float(order_result['notional']),
            order_result['entry_order_id'],
            order_result['tp_order_id'],
            order_result['sl_order_id'],
            exchange
        ))
        pos_id = cur.fetchone()[0]
        conn.commit()
        logger.info(f"Inserted position ID {pos_id} for {signal['symbol']} on {exchange}")
        return pos_id

def get_open_positions():
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, chat_id, symbol, side, entry_price, stop_loss, take_profit,
                   quantity, notional_usd, entry_order_id, tp_order_id, sl_order_id
            FROM positions 
            WHERE status = 'OPEN'
            ORDER BY created_at DESC
        """)
        return [dict(row) for row in cur.fetchall()]
    
# Get all positions
def get_all_positions():
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, chat_id, symbol, side, entry_price, stop_loss, take_profit,
                   quantity, notional_usd, status, current_pnl_pct, current_pnl_usd,
                   created_at, updated_at, entry_order_id, tp_order_id, sl_order_id,
                   fill_price, exchange
            FROM positions 
            ORDER BY created_at DESC
        """)
        return [dict(row) for row in cur.fetchall()]    

def update_position_pnl(position_id: int, pnl_pct: float, pnl_usd: float, 
                       status: str = None, fill_price: float = None):
    with get_db_connection() as conn:
        cur = conn.cursor()
        if status or fill_price:
            updates = []
            params = []
            if fill_price is not None:
                updates.append("fill_price = ?")
                params.append(fill_price)
            if status:
                updates.append("status = ?")
                params.append(status)
            updates.extend(["current_pnl_pct = ?", "current_pnl_usd = ?", "updated_at = CURRENT_TIMESTAMP"])
            params.extend([pnl_pct, pnl_usd, position_id])
            query = f"UPDATE positions SET {', '.join(updates)} WHERE id = ?"
            cur.execute(query, params)
        else:
            cur.execute("""
                UPDATE positions
                SET current_pnl_pct = ?, current_pnl_usd = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (pnl_pct, pnl_usd, position_id))
        conn.commit()

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

# if __name__ == "__main__":
#     initialize_database_tables()        
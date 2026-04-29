# ============================================================
#  backend/database.py
#  Creates and manages the SQLite database schema.
#  All trading data lives here — trades, orders, P&L snapshots.
# ============================================================

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'journal.db')


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row       # rows behave like dicts
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_db():
    """Create all tables if they don't already exist."""
    conn = get_conn()

    conn.executescript('''
        -- ── Executed trades (from kite.trades()) ────────────
        CREATE TABLE IF NOT EXISTS trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        TEXT UNIQUE,
            order_id        TEXT,
            exchange_order_id TEXT,
            tradingsymbol   TEXT NOT NULL,
            exchange        TEXT,
            transaction_type TEXT,        -- BUY or SELL
            quantity        INTEGER,
            price           REAL,
            product         TEXT,         -- MIS, CNC, NRML
            order_type      TEXT,         -- MARKET, LIMIT etc.
            trade_date      TEXT,         -- YYYY-MM-DD
            trade_time      TEXT,         -- HH:MM:SS
            fill_timestamp  TEXT,
            synced_at       TEXT DEFAULT (datetime('now'))
        );

        -- ── Computed P&L per closed position ────────────────
        CREATE TABLE IF NOT EXISTS pnl_records (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tradingsymbol   TEXT NOT NULL,
            trade_date      TEXT NOT NULL,
            entry_price     REAL,
            exit_price      REAL,
            quantity        INTEGER,
            transaction_type TEXT,
            pnl             REAL,
            pnl_pct         REAL,
            product         TEXT,
            holding_duration TEXT,         -- e.g. "2h 30m" or "3d"
            synced_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(tradingsymbol, trade_date, entry_price, exit_price)
        );

        -- ── Daily equity snapshots ───────────────────────────
        CREATE TABLE IF NOT EXISTS equity_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date   TEXT UNIQUE,
            portfolio_value REAL,
            cash            REAL,
            holdings_value  REAL,
            day_pnl         REAL,
            synced_at       TEXT DEFAULT (datetime('now'))
        );

        -- ── Holdings (long-term positions) ───────────────────
        CREATE TABLE IF NOT EXISTS holdings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tradingsymbol   TEXT UNIQUE,
            exchange        TEXT,
            quantity        INTEGER,
            average_price   REAL,
            last_price      REAL,
            pnl             REAL,
            day_change      REAL,
            day_change_pct  REAL,
            synced_at       TEXT DEFAULT (datetime('now'))
        );

        -- ── Sync log ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS sync_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type   TEXT,
            status      TEXT,
            records     INTEGER DEFAULT 0,
            message     TEXT,
            synced_at   TEXT DEFAULT (datetime('now'))
        );
    ''')

    conn.commit()
    conn.close()
    print('[DB] Schema initialised')


if __name__ == '__main__':
    init_db()
    print('[DB] Done')

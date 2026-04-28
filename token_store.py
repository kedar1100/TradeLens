# ============================================================
#  backend/token_store.py
#  Saves and loads the Kite access token from SQLite.
#  Tokens are valid only for the current trading day —
#  after midnight Kite invalidates them automatically.
# ============================================================

import sqlite3
import os
from datetime import date

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'tokens.db')


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id           INTEGER PRIMARY KEY,
            access_token TEXT NOT NULL,
            created_date TEXT NOT NULL
        )
    ''')
    conn.commit()
    return conn


def save_token(access_token: str):
    """Save today's access token, replacing any previous one."""
    conn = _get_conn()
    conn.execute('DELETE FROM tokens')
    conn.execute(
        'INSERT INTO tokens (access_token, created_date) VALUES (?, ?)',
        (access_token, str(date.today()))
    )
    conn.commit()
    conn.close()
    print(f'[TokenStore] Access token saved for {date.today()}')


def load_token() -> str | None:
    """
    Return today's access token, or None if expired / not found.
    Kite tokens reset every day at midnight IST.
    """
    conn = _get_conn()
    row = conn.execute(
        'SELECT access_token, created_date FROM tokens ORDER BY id DESC LIMIT 1'
    ).fetchone()
    conn.close()

    if not row:
        return None

    access_token, created_date = row
    if created_date != str(date.today()):
        print('[TokenStore] Token is from a previous day — needs re-login')
        return None

    return access_token


def clear_token():
    """Force logout — delete stored token."""
    conn = _get_conn()
    conn.execute('DELETE FROM tokens')
    conn.commit()
    conn.close()
    print('[TokenStore] Token cleared')

# ============================================================
#  backend/sync.py
#  Pulls data from Kite API and stores it in SQLite.
#  Called automatically after login and on demand via /api/sync.
# ============================================================

import os
import json
from datetime import datetime, date, timedelta
from backend.database import get_conn, init_db
from backend.kite_client import get_kite


# ─────────────────────────────────────────────
#  MAIN SYNC ENTRY POINT
# ─────────────────────────────────────────────

def sync_all() -> dict:
    """
    Pull all data from Kite and store in DB.
    Returns a summary dict with counts.
    """
    init_db()
    kite = get_kite()
    if not kite:
        return {'error': 'Not authenticated'}

    results = {}

    results['trades']    = sync_trades(kite)
    results['holdings']  = sync_holdings(kite)
    results['positions'] = sync_positions(kite)
    results['pnl']       = compute_pnl()

    _log_sync('full_sync', 'success', message=json.dumps(results))
    print(f'[Sync] Complete: {results}')
    return results


# ─────────────────────────────────────────────
#  INDIVIDUAL SYNC FUNCTIONS
# ─────────────────────────────────────────────

def sync_trades(kite) -> int:
    """Fetch today's executed trades from Kite and store them."""
    try:
        raw_trades = kite.trades()
    except Exception as e:
        _log_sync('trades', 'error', message=str(e))
        print(f'[Sync] trades failed: {e}')
        return 0

    if not raw_trades:
        print('[Sync] No trades today')
        return 0

    conn  = get_conn()
    count = 0

    for t in raw_trades:
        fill_ts = str(t.get('fill_timestamp', ''))
        trade_date = fill_ts[:10] if fill_ts else str(date.today())
        trade_time = fill_ts[11:19] if len(fill_ts) > 10 else ''

        try:
            conn.execute('''
                INSERT OR IGNORE INTO trades
                    (trade_id, order_id, exchange_order_id, tradingsymbol,
                     exchange, transaction_type, quantity, price, product,
                     order_type, trade_date, trade_time, fill_timestamp)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                str(t.get('trade_id', '')),
                str(t.get('order_id', '')),
                str(t.get('exchange_order_id', '')),
                t.get('tradingsymbol', ''),
                t.get('exchange', ''),
                t.get('transaction_type', ''),
                int(t.get('quantity', 0)),
                float(t.get('price', 0)),
                t.get('product', ''),
                t.get('order_type', ''),
                trade_date,
                trade_time,
                fill_ts,
            ))
            if conn.execute('SELECT changes()').fetchone()[0]:
                count += 1
        except Exception as e:
            print(f'[Sync] Trade insert error: {e}')

    conn.commit()
    conn.close()
    _log_sync('trades', 'success', records=count)
    print(f'[Sync] Trades — {count} new records')
    return count


def sync_holdings(kite) -> int:
    """Fetch current holdings and update the holdings table."""
    try:
        raw = kite.holdings()
    except Exception as e:
        _log_sync('holdings', 'error', message=str(e))
        return 0

    conn  = get_conn()
    count = 0

    # Wipe and re-insert (holdings change daily)
    conn.execute('DELETE FROM holdings')

    for h in raw:
        try:
            conn.execute('''
                INSERT OR REPLACE INTO holdings
                    (tradingsymbol, exchange, quantity, average_price,
                     last_price, pnl, day_change, day_change_pct)
                VALUES (?,?,?,?,?,?,?,?)
            ''', (
                h.get('tradingsymbol', ''),
                h.get('exchange', ''),
                int(h.get('quantity', 0)),
                float(h.get('average_price', 0)),
                float(h.get('last_price', 0)),
                float(h.get('pnl', 0)),
                float(h.get('day_change', 0)),
                float(h.get('day_change_percentage', 0)),
            ))
            count += 1
        except Exception as e:
            print(f'[Sync] Holding insert error: {e}')

    conn.commit()
    conn.close()
    _log_sync('holdings', 'success', records=count)
    print(f'[Sync] Holdings — {count} records')
    return count


def sync_positions(kite) -> int:
    """
    Fetch today's positions and compute a daily equity snapshot.
    Positions = intraday (day) + carry-forward (net).
    """
    try:
        positions = kite.positions()
    except Exception as e:
        _log_sync('positions', 'error', message=str(e))
        return 0

    day_positions = positions.get('day', [])
    net_positions = positions.get('net', [])
    all_positions = day_positions + net_positions

    # ── Compute day P&L from all positions ───────────────────
    day_pnl = sum(float(p.get('pnl', 0)) for p in day_positions)

    # ── Save daily snapshot ───────────────────────────────────
    conn = get_conn()
    try:
        conn.execute('''
            INSERT OR REPLACE INTO equity_snapshots
                (snapshot_date, day_pnl)
            VALUES (?, ?)
        ''', (str(date.today()), round(day_pnl, 2)))
        conn.commit()
    except Exception as e:
        print(f'[Sync] Snapshot error: {e}')
    conn.close()

    _log_sync('positions', 'success', records=len(all_positions))
    print(f'[Sync] Positions — {len(all_positions)} total, Day P&L: ₹{day_pnl:.2f}')
    return len(all_positions)


# ─────────────────────────────────────────────
#  P&L COMPUTATION  (from stored trades)
# ─────────────────────────────────────────────

def compute_pnl() -> int:
    """
    Match BUY and SELL trades per symbol per day.
    Compute realised P&L for each closed position.
    Stored in pnl_records table.
    """
    conn   = get_conn()
    trades = conn.execute('''
        SELECT tradingsymbol, transaction_type, quantity, price,
               trade_date, product
        FROM trades
        ORDER BY tradingsymbol, trade_date, trade_time
    ''').fetchall()

    if not trades:
        conn.close()
        return 0

    # ── Group trades by symbol + date ────────────────────────
    from collections import defaultdict
    groups = defaultdict(lambda: {'BUY': [], 'SELL': []})

    for t in trades:
        key = (t['tradingsymbol'], t['trade_date'])
        groups[key][t['transaction_type']].append({
            'qty':     t['quantity'],
            'price':   t['price'],
            'product': t['product'],
        })

    inserted = 0
    for (symbol, trade_date), sides in groups.items():
        buys  = sides['BUY']
        sells = sides['SELL']

        if not buys or not sells:
            continue

        avg_buy  = sum(b['price'] * b['qty'] for b in buys)  / sum(b['qty'] for b in buys)
        avg_sell = sum(s['price'] * s['qty'] for s in sells) / sum(s['qty'] for s in sells)
        qty      = min(sum(b['qty'] for b in buys), sum(s['qty'] for s in sells))
        pnl      = (avg_sell - avg_buy) * qty
        pnl_pct  = ((avg_sell - avg_buy) / avg_buy) * 100 if avg_buy else 0
        product  = buys[0]['product']

        try:
            conn.execute('''
                INSERT OR IGNORE INTO pnl_records
                    (tradingsymbol, trade_date, entry_price, exit_price,
                     quantity, transaction_type, pnl, pnl_pct, product)
                VALUES (?,?,?,?,?,?,?,?,?)
            ''', (symbol, trade_date,
                  round(avg_buy, 4), round(avg_sell, 4),
                  qty, 'LONG',
                  round(pnl, 2), round(pnl_pct, 4),
                  product))
            if conn.execute('SELECT changes()').fetchone()[0]:
                inserted += 1
        except Exception as e:
            print(f'[PnL] Insert error for {symbol}: {e}')

    conn.commit()
    conn.close()
    print(f'[PnL] Computed {inserted} new P&L records')
    return inserted


# ─────────────────────────────────────────────
#  QUERY HELPERS  (used by API routes)
# ─────────────────────────────────────────────

def get_trade_history(days: int = 30) -> list[dict]:
    """Return trades from the last N days as a list of dicts."""
    conn  = get_conn()
    since = str(date.today() - timedelta(days=days))
    rows  = conn.execute('''
        SELECT * FROM trades
        WHERE trade_date >= ?
        ORDER BY trade_date DESC, trade_time DESC
    ''', (since,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pnl_history(days: int = 30) -> list[dict]:
    """Return P&L records from the last N days."""
    conn  = get_conn()
    since = str(date.today() - timedelta(days=days))
    rows  = conn.execute('''
        SELECT * FROM pnl_records
        WHERE trade_date >= ?
        ORDER BY trade_date DESC
    ''', (since,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_summary_metrics(days: int = 30) -> dict:
    """
    Return aggregated metrics for the dashboard cards:
    net P&L, win rate, total trades, best/worst trade.
    """
    records = get_pnl_history(days)

    if not records:
        return {
            'net_pnl': 0, 'total_trades': 0,
            'win_rate': 0, 'avg_win': 0, 'avg_loss': 0,
            'best_trade': 0, 'worst_trade': 0,
            'profit_factor': 0,
        }

    winners = [r for r in records if r['pnl'] > 0]
    losers  = [r for r in records if r['pnl'] <= 0]

    net_pnl      = sum(r['pnl'] for r in records)
    win_rate     = len(winners) / len(records) * 100 if records else 0
    avg_win      = sum(r['pnl'] for r in winners) / len(winners) if winners else 0
    avg_loss     = sum(r['pnl'] for r in losers)  / len(losers)  if losers  else 0
    gross_profit = sum(r['pnl'] for r in winners)
    gross_loss   = abs(sum(r['pnl'] for r in losers))
    pf           = gross_profit / gross_loss if gross_loss else float('inf')
    best         = max((r['pnl'] for r in records), default=0)
    worst        = min((r['pnl'] for r in records), default=0)

    return {
        'net_pnl':       round(net_pnl, 2),
        'total_trades':  len(records),
        'win_rate':      round(win_rate, 2),
        'avg_win':       round(avg_win, 2),
        'avg_loss':      round(avg_loss, 2),
        'best_trade':    round(best, 2),
        'worst_trade':   round(worst, 2),
        'profit_factor': round(pf, 3),
    }


def get_equity_curve(days: int = 90) -> list[dict]:
    """Return daily equity snapshots for the equity curve chart."""
    conn  = get_conn()
    since = str(date.today() - timedelta(days=days))
    rows  = conn.execute('''
        SELECT snapshot_date, day_pnl, portfolio_value
        FROM equity_snapshots
        WHERE snapshot_date >= ?
        ORDER BY snapshot_date ASC
    ''', (since,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_instrument_breakdown(days: int = 30) -> list[dict]:
    """Return P&L grouped by instrument, sorted best to worst."""
    conn  = get_conn()
    since = str(date.today() - timedelta(days=days))
    rows  = conn.execute('''
        SELECT
            tradingsymbol,
            COUNT(*) as total_trades,
            SUM(pnl) as net_pnl,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
            AVG(pnl_pct) as avg_return_pct
        FROM pnl_records
        WHERE trade_date >= ?
        GROUP BY tradingsymbol
        ORDER BY net_pnl DESC
    ''', (since,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
#  INTERNAL HELPERS
# ─────────────────────────────────────────────

def _log_sync(sync_type: str, status: str, records: int = 0, message: str = ''):
    try:
        conn = get_conn()
        conn.execute('''
            INSERT INTO sync_log (sync_type, status, records, message)
            VALUES (?,?,?,?)
        ''', (sync_type, status, records, message))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─────────────────────────────────────────────
if __name__ == '__main__':
    from backend.database import init_db
    init_db()
    result = sync_all()
    print(result)

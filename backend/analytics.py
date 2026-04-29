# ============================================================
#  backend/analytics.py — Advanced Analytics Engine
#  Sharpe Ratio, Sortino, Max Drawdown, CAGR, Calmar,
#  Win streak, Time analysis, Risk metrics
# ============================================================

import math
from datetime import date, datetime, timedelta
from collections import defaultdict


RISK_FREE_RATE = 0.065      # India 10Y bond ~6.5%
TRADING_DAYS   = 252


# ─────────────────────────────────────────────
#  MAIN ENTRY — call this from Flask routes
# ─────────────────────────────────────────────

def compute_advanced_metrics(pnl_records: list[dict], initial_capital: float = 100_000) -> dict:
    """
    Takes a list of pnl_records from the DB and returns
    every advanced metric the dashboard needs.
    """
    if not pnl_records:
        return _empty_metrics()

    # Build daily P&L series (date → total pnl that day)
    daily_pnl = _build_daily_pnl(pnl_records)

    # Build equity curve (running sum from initial capital)
    equity_curve = _build_equity_curve(daily_pnl, initial_capital)

    return {
        **_return_metrics(equity_curve, initial_capital),
        **_risk_metrics(equity_curve, daily_pnl),
        **_drawdown_metrics(equity_curve),
        **_trade_metrics(pnl_records),
        **_streak_metrics(pnl_records),
        **_time_metrics(pnl_records),
        'equity_curve':   equity_curve,       # list of {date, value}
        'daily_pnl_series': [
            {'date': d, 'pnl': round(p, 2)}
            for d, p in sorted(daily_pnl.items())
        ],
    }


# ─────────────────────────────────────────────
#  RETURN METRICS
# ─────────────────────────────────────────────

def _return_metrics(equity_curve: list[dict], initial_capital: float) -> dict:
    if len(equity_curve) < 2:
        return {'total_return_pct': 0, 'cagr_pct': 0, 'annualised_vol_pct': 0}

    start_val = equity_curve[0]['value']
    end_val   = equity_curve[-1]['value']

    total_return = (end_val - start_val) / start_val * 100

    # CAGR — compound annual growth rate
    n_days = len(equity_curve)
    n_years = n_days / TRADING_DAYS
    cagr = ((end_val / start_val) ** (1 / max(n_years, 1/252)) - 1) * 100 if start_val > 0 else 0

    # Annualised volatility from daily returns
    returns = _daily_returns(equity_curve)
    vol = _std(returns) * math.sqrt(TRADING_DAYS) * 100 if returns else 0

    return {
        'total_return_pct':   round(total_return, 2),
        'cagr_pct':           round(cagr, 2),
        'annualised_vol_pct': round(vol, 2),
        'start_value':        round(start_val, 2),
        'end_value':          round(end_val, 2),
    }


# ─────────────────────────────────────────────
#  RISK METRICS
# ─────────────────────────────────────────────

def _risk_metrics(equity_curve: list[dict], daily_pnl: dict) -> dict:
    returns = _daily_returns(equity_curve)
    if not returns:
        return {'sharpe_ratio': 0, 'sortino_ratio': 0, 'calmar_ratio': 0}

    daily_rf = RISK_FREE_RATE / TRADING_DAYS

    # ── Sharpe ────────────────────────────────
    excess  = [r - daily_rf for r in returns]
    std_all = _std(excess)
    sharpe  = (_mean(excess) / std_all) * math.sqrt(TRADING_DAYS) if std_all else 0

    # ── Sortino (only downside deviation) ─────
    downside = [r for r in returns if r < 0]
    std_down = _std(downside) * math.sqrt(TRADING_DAYS) if downside else 0
    ann_ret  = _mean(returns) * TRADING_DAYS
    sortino  = (ann_ret - RISK_FREE_RATE) / std_down if std_down else 0

    # ── Calmar (CAGR / max drawdown) ──────────
    dd       = _max_drawdown_pct(equity_curve)
    start_v  = equity_curve[0]['value']
    end_v    = equity_curve[-1]['value']
    n_years  = len(equity_curve) / TRADING_DAYS
    cagr     = ((end_v / start_v) ** (1 / max(n_years, 1/252)) - 1) * 100 if start_v > 0 else 0
    calmar   = cagr / abs(dd) if dd != 0 else 0

    return {
        'sharpe_ratio':  round(sharpe,  3),
        'sortino_ratio': round(sortino, 3),
        'calmar_ratio':  round(calmar,  3),
    }


# ─────────────────────────────────────────────
#  DRAWDOWN METRICS
# ─────────────────────────────────────────────

def _drawdown_metrics(equity_curve: list[dict]) -> dict:
    if len(equity_curve) < 2:
        return {'max_drawdown_pct': 0, 'max_drawdown_value': 0,
                'avg_drawdown_pct': 0, 'recovery_days': 0}

    values     = [e['value'] for e in equity_curve]
    peak       = values[0]
    max_dd_pct = 0
    max_dd_val = 0
    drawdowns  = []

    in_drawdown   = False
    dd_start_peak = 0
    dd_start_idx  = 0

    for i, v in enumerate(values):
        if v > peak:
            if in_drawdown:
                # Recovered — measure recovery length
                drawdowns.append({
                    'pct': (v - dd_start_peak) / dd_start_peak * 100,
                    'recovery_days': i - dd_start_idx
                })
            peak        = v
            in_drawdown = False
        else:
            dd_pct = (v - peak) / peak * 100
            dd_val = v - peak
            if dd_pct < max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_val = dd_val
            if not in_drawdown and dd_pct < -0.001:
                in_drawdown   = True
                dd_start_peak = peak
                dd_start_idx  = i

    avg_dd  = _mean([d['pct'] for d in drawdowns]) if drawdowns else 0
    avg_rec = _mean([d['recovery_days'] for d in drawdowns]) if drawdowns else 0

    return {
        'max_drawdown_pct':   round(max_dd_pct, 2),
        'max_drawdown_value': round(max_dd_val, 2),
        'avg_drawdown_pct':   round(avg_dd,     2),
        'avg_recovery_days':  round(avg_rec,     1),
    }


# ─────────────────────────────────────────────
#  TRADE-LEVEL METRICS
# ─────────────────────────────────────────────

def _trade_metrics(records: list[dict]) -> dict:
    if not records:
        return {}

    pnls    = [r['pnl'] for r in records]
    winners = [p for p in pnls if p > 0]
    losers  = [p for p in pnls if p <= 0]

    win_rate      = len(winners) / len(pnls) * 100 if pnls else 0
    avg_win       = _mean(winners) if winners else 0
    avg_loss      = _mean(losers)  if losers  else 0
    gross_profit  = sum(winners)
    gross_loss    = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss else float('inf')

    # Expectancy = average $ you make per trade
    expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)

    # Risk/Reward ratio
    rr_ratio = abs(avg_win / avg_loss) if avg_loss else 0

    return {
        'total_trades':   len(records),
        'total_winners':  len(winners),
        'total_losers':   len(losers),
        'win_rate_pct':   round(win_rate,      2),
        'avg_win':        round(avg_win,        2),
        'avg_loss':       round(avg_loss,       2),
        'gross_profit':   round(gross_profit,   2),
        'gross_loss':     round(gross_loss,     2),
        'profit_factor':  round(profit_factor,  3) if profit_factor != float('inf') else 'inf',
        'expectancy':     round(expectancy,     2),
        'rr_ratio':       round(rr_ratio,       2),
        'best_trade':     round(max(pnls),      2),
        'worst_trade':    round(min(pnls),      2),
        'avg_trade_pnl':  round(_mean(pnls),    2),
    }


# ─────────────────────────────────────────────
#  STREAK METRICS
# ─────────────────────────────────────────────

def _streak_metrics(records: list[dict]) -> dict:
    if not records:
        return {}

    sorted_recs = sorted(records, key=lambda r: r.get('trade_date', ''))
    pnls = [r['pnl'] for r in sorted_recs]

    max_win_streak  = 0
    max_loss_streak = 0
    cur_win         = 0
    cur_loss        = 0

    for p in pnls:
        if p > 0:
            cur_win  += 1
            cur_loss  = 0
            max_win_streak = max(max_win_streak, cur_win)
        else:
            cur_loss += 1
            cur_win   = 0
            max_loss_streak = max(max_loss_streak, cur_loss)

    # Current streak
    cur_streak      = 0
    cur_streak_type = ''
    for p in reversed(pnls):
        if cur_streak == 0:
            cur_streak_type = 'win' if p > 0 else 'loss'
            cur_streak = 1
        elif (p > 0 and cur_streak_type == 'win') or (p <= 0 and cur_streak_type == 'loss'):
            cur_streak += 1
        else:
            break

    return {
        'max_win_streak':   max_win_streak,
        'max_loss_streak':  max_loss_streak,
        'current_streak':   cur_streak,
        'current_streak_type': cur_streak_type,
    }


# ─────────────────────────────────────────────
#  TIME-BASED PATTERNS
# ─────────────────────────────────────────────

def _time_metrics(records: list[dict]) -> dict:
    """
    Best/worst day of week, best/worst month.
    Helps traders spot when they perform best.
    """
    if not records:
        return {}

    day_names   = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

    by_weekday = defaultdict(list)
    by_month   = defaultdict(list)

    for r in records:
        try:
            d = datetime.strptime(r['trade_date'], '%Y-%m-%d')
            by_weekday[day_names[d.weekday()]].append(r['pnl'])
            by_month[month_names[d.month - 1]].append(r['pnl'])
        except Exception:
            pass

    weekday_pnl = {
        day: round(sum(pnls), 2)
        for day, pnls in by_weekday.items()
    }
    month_pnl = {
        mon: round(sum(pnls), 2)
        for mon, pnls in by_month.items()
    }

    best_day  = max(weekday_pnl, key=weekday_pnl.get) if weekday_pnl else '—'
    worst_day = min(weekday_pnl, key=weekday_pnl.get) if weekday_pnl else '—'

    return {
        'weekday_pnl':   weekday_pnl,
        'month_pnl':     month_pnl,
        'best_weekday':  best_day,
        'worst_weekday': worst_day,
    }


# ─────────────────────────────────────────────
#  INTERNAL HELPERS
# ─────────────────────────────────────────────

def _build_daily_pnl(records: list[dict]) -> dict:
    daily = defaultdict(float)
    for r in records:
        daily[r['trade_date']] += r['pnl']
    return dict(daily)


def _build_equity_curve(daily_pnl: dict, initial_capital: float) -> list[dict]:
    running = initial_capital
    curve   = []
    for d in sorted(daily_pnl.keys()):
        running += daily_pnl[d]
        curve.append({'date': d, 'value': round(running, 2)})
    return curve


def _daily_returns(equity_curve: list[dict]) -> list[float]:
    values  = [e['value'] for e in equity_curve]
    returns = []
    for i in range(1, len(values)):
        prev = values[i-1]
        if prev != 0:
            returns.append((values[i] - prev) / prev)
    return returns


def _max_drawdown_pct(equity_curve: list[dict]) -> float:
    values = [e['value'] for e in equity_curve]
    peak   = values[0]
    max_dd = 0
    for v in values:
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100 if peak else 0
        if dd < max_dd:
            max_dd = dd
    return round(max_dd, 2)


def _mean(lst: list) -> float:
    return sum(lst) / len(lst) if lst else 0


def _std(lst: list) -> float:
    if len(lst) < 2:
        return 0
    m   = _mean(lst)
    var = sum((x - m) ** 2 for x in lst) / (len(lst) - 1)
    return math.sqrt(var)


def _empty_metrics() -> dict:
    return {
        'total_return_pct': 0, 'cagr_pct': 0, 'annualised_vol_pct': 0,
        'sharpe_ratio': 0, 'sortino_ratio': 0, 'calmar_ratio': 0,
        'max_drawdown_pct': 0, 'max_drawdown_value': 0,
        'avg_drawdown_pct': 0, 'avg_recovery_days': 0,
        'total_trades': 0, 'win_rate_pct': 0, 'profit_factor': 0,
        'expectancy': 0, 'rr_ratio': 0,
        'max_win_streak': 0, 'max_loss_streak': 0,
        'current_streak': 0, 'current_streak_type': '',
        'best_weekday': '—', 'worst_weekday': '—',
        'weekday_pnl': {}, 'month_pnl': {},
        'equity_curve': [], 'daily_pnl_series': [],
    }
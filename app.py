# ============================================================
#  app.py — Flask server + Zerodha Kite OAuth login flow
# ============================================================
#
#  FLOW:
#   1. User visits /              → redirected to /login
#   2. /login                     → redirected to Kite login page
#   3. User logs in on Kite       → Kite redirects to /callback
#   4. /callback                  → exchanges request_token for
#                                   access_token, saves it, goes to /
#   5. /                          → dashboard (authenticated)
#
# ============================================================

import os
from flask import Flask, redirect, request, session, jsonify, render_template_string
from dotenv import load_dotenv
from kiteconnect import KiteConnect, exceptions as KiteExceptions

from backend.token_store import save_token, clear_token, load_token
from backend.kite_client  import get_kite, build_unauthenticated_kite, is_authenticated
from backend.database     import init_db
from backend.sync         import (
    sync_all, get_trade_history, get_pnl_history,
    get_summary_metrics, get_equity_curve, get_instrument_breakdown
)
from backend.analytics    import compute_advanced_metrics

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-this')

init_db()    # make sure all tables exist on every startup


# ─────────────────────────────────────────────
#  AUTH ROUTES
# ─────────────────────────────────────────────

@app.route('/login')
def login():
    """
    Step 1: Build the Kite login URL and redirect the user there.
    Kite will show their own login page.
    After the user logs in, Kite redirects to REDIRECT_URL with
    a `request_token` query parameter.
    """
    kite = build_unauthenticated_kite()
    login_url = kite.login_url()
    print(f'[Auth] Redirecting to Kite login: {login_url}')
    return redirect(login_url)


@app.route('/callback')
def callback():
    """
    Step 2: Kite redirects here after a successful login.
    URL will look like:
        /callback?request_token=abc123&action=login&status=success

    We exchange the request_token for an access_token using our
    API secret. The access_token is what we use for all future calls.
    """
    request_token = request.args.get('request_token')
    status        = request.args.get('status')

    # ── Handle failed / cancelled login ─────────────────────
    if status != 'success' or not request_token:
        error = request.args.get('message', 'Login failed or cancelled')
        print(f'[Auth] Login failed: {error}')
        return redirect(f'/?error={error}')

    # ── Exchange request_token → access_token ────────────────
    try:
        kite    = build_unauthenticated_kite()
        session_data = kite.generate_session(
            request_token,
            api_secret=os.getenv('KITE_API_SECRET')
        )

        access_token = session_data['access_token']
        user_name    = session_data.get('user_name', '')
        user_id      = session_data.get('user_id', '')

        # ── Persist token ────────────────────────────────────
        save_token(access_token)

        # ── Save user info in Flask session (not sensitive) ──
        session['user_name'] = user_name
        session['user_id']   = user_id

        print(f'[Auth] Login successful — {user_name} ({user_id})')

        # ── Auto-sync data after login ────────────────────────
        try:
            sync_all()
        except Exception as e:
            print(f'[Auth] Auto-sync failed (non-fatal): {e}')

        return redirect('/')

    except KiteExceptions.TokenException as e:
        print(f'[Auth] Token exchange failed: {e}')
        return redirect(f'/?error=Token+exchange+failed:+{str(e)}')

    except Exception as e:
        print(f'[Auth] Unexpected error: {e}')
        return redirect(f'/?error=Unexpected+error')


@app.route('/logout')
def logout():
    """Clear stored token and Flask session."""
    kite = get_kite()
    if kite:
        try:
            kite.invalidate_access_token()     # Tell Kite to revoke the token
        except Exception:
            pass                                # Best effort

    clear_token()
    session.clear()
    print('[Auth] User logged out')
    return redirect('/')


# ─────────────────────────────────────────────
#  API ROUTES  (authenticated, return JSON)
# ─────────────────────────────────────────────

def require_auth(fn):
    """Decorator — returns 401 JSON if not authenticated."""
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_authenticated():
            return jsonify({'error': 'Not authenticated', 'login_url': '/login'}), 401
        return fn(*args, **kwargs)
    return wrapper


@app.route('/api/status')
def api_status():
    """Health check + auth status. Frontend polls this on load."""
    authenticated = is_authenticated()
    return jsonify({
        'authenticated': authenticated,
        'user_name': session.get('user_name', ''),
        'user_id':   session.get('user_id', ''),
    })


@app.route('/api/profile')
@require_auth
def api_profile():
    """Return Kite user profile."""
    kite = get_kite()
    try:
        profile = kite.profile()
        return jsonify(profile)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/holdings')
@require_auth
def api_holdings():
    """Return current holdings."""
    kite = get_kite()
    try:
        holdings = kite.holdings()
        return jsonify(holdings)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/positions')
@require_auth
def api_positions():
    """Return open positions (day + net)."""
    kite = get_kite()
    try:
        positions = kite.positions()
        return jsonify(positions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/trades')
@require_auth
def api_trades():
    """Return today's executed trades."""
    kite = get_kite()
    try:
        trades = kite.trades()
        return jsonify(trades)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/orders')
@require_auth
def api_orders():
    """Return all orders for today."""
    kite = get_kite()
    try:
        orders = kite.orders()
        return jsonify(orders)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
#  ANALYTICS API  (from local DB)
# ─────────────────────────────────────────────

@app.route('/api/sync')
@require_auth
def api_sync():
    """Manually trigger a full data sync from Kite."""
    result = sync_all()
    return jsonify(result)


@app.route('/api/analytics/summary')
@require_auth
def api_summary():
    """Dashboard metrics cards — net P&L, win rate, etc."""
    days = int(request.args.get('days', 30))
    return jsonify(get_summary_metrics(days))


@app.route('/api/analytics/trades')
@require_auth
def api_trade_history():
    """Full trade history from local DB."""
    days = int(request.args.get('days', 30))
    return jsonify(get_trade_history(days))


@app.route('/api/analytics/pnl')
@require_auth
def api_pnl_history():
    """Closed P&L records from local DB."""
    days = int(request.args.get('days', 30))
    return jsonify(get_pnl_history(days))


@app.route('/api/analytics/equity')
@require_auth
def api_equity():
    """Daily equity curve for the chart."""
    days = int(request.args.get('days', 90))
    return jsonify(get_equity_curve(days))


@app.route('/api/analytics/instruments')
@require_auth
def api_instruments():
    """P&L breakdown by instrument."""
    days = int(request.args.get('days', 30))
    return jsonify(get_instrument_breakdown(days))


@app.route('/api/analytics/advanced')
@require_auth
def api_advanced():
    """
    Full advanced metrics — Sharpe, Sortino, Calmar, drawdown,
    streaks, weekday P&L, equity curve, CAGR. Powers the analytics page.
    """
    days    = int(request.args.get('days', 90))
    capital = float(request.args.get('capital', 100_000))
    records = get_pnl_history(days)
    metrics = compute_advanced_metrics(records, initial_capital=capital)
    # Convert inf to string for JSON serialisation
    if metrics.get('profit_factor') == float('inf'):
        metrics['profit_factor'] = 'inf'
    return jsonify(metrics)


# ─────────────────────────────────────────────
#  MAIN ROUTE  (serves the dashboard or login)
# ─────────────────────────────────────────────

@app.route('/')
def index():
    error = request.args.get('error', '')
    if not is_authenticated():
        return render_template_string(LOGIN_PAGE, error=error)
    dashboard_path = os.path.join(os.path.dirname(__file__), 'frontend', 'dashboard.html')
    with open(dashboard_path) as f:
        return f.read()


@app.route('/analytics')
def analytics_page():
    if not is_authenticated():
        return redirect('/login')
    apath = os.path.join(os.path.dirname(__file__), 'frontend', 'analytics.html')
    with open(apath) as f:
        return f.read()


# ─────────────────────────────────────────────
#  MINIMAL HTML TEMPLATES (inline for simplicity)
#  Replace with proper Jinja templates / React later
# ─────────────────────────────────────────────

LOGIN_PAGE = '''<!DOCTYPE html>
<html>
<head>
  <title>TradeLens — Login</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #f5f5f0;
           display: flex; align-items: center; justify-content: center;
           height: 100vh; margin: 0; }
    .card { background: #fff; border-radius: 12px; padding: 40px 48px;
            border: 1px solid #e0e0d8; max-width: 360px; width: 100%;
            text-align: center; }
    h1 { font-size: 22px; margin-bottom: 6px; }
    h1 span { color: #1D9E75; }
    p  { color: #888; font-size: 13px; margin-bottom: 28px; }
    a.btn { display: inline-block; background: #1D9E75; color: #fff;
            text-decoration: none; padding: 11px 32px; border-radius: 8px;
            font-size: 14px; font-weight: 500; }
    .error { color: #993C1D; font-size: 12px; margin-top: 14px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Trade<span>Lens</span></h1>
    <p>Trading Journal & Analytics Platform</p>
    <a class="btn" href="/login">Login with Zerodha</a>
    {% if error %}
      <div class="error">{{ error }}</div>
    {% endif %}
  </div>
</body>
</html>'''

DASHBOARD_STUB = '''<!DOCTYPE html>
<html>
<head>
  <title>TradeLens — Dashboard</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #f5f5f0;
           margin: 0; padding: 32px; }
    .topbar { display: flex; justify-content: space-between;
              align-items: center; margin-bottom: 24px; }
    h1 { font-size: 20px; }
    h1 span { color: #1D9E75; }
    a { font-size: 13px; color: #888; }
    .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
             gap: 12px; }
    .card { background: #fff; border-radius: 10px; padding: 20px 24px;
            border: 1px solid #e0e0d8; }
    .label { font-size: 11px; color: #888; margin-bottom: 6px; }
    .val { font-size: 20px; font-weight: 500; }
    pre { background: #f5f5f0; border-radius: 8px; padding: 16px;
          font-size: 12px; margin-top: 24px; overflow: auto; }
  </style>
</head>
<body>
  <div class="topbar">
    <h1>Trade<span>Lens</span> &nbsp;<small style="font-size:13px;color:#888">{{ user_name }}</small></h1>
    <a href="/logout">Logout</a>
  </div>

  <div class="cards">
    <div class="card"><div class="label">Status</div><div class="val" style="color:#1D9E75">Connected</div></div>
    <div class="card"><div class="label">Positions</div><div class="val" id="pos-count">...</div></div>
    <div class="card"><div class="label">Today\'s Trades</div><div class="val" id="trade-count">...</div></div>
    <div class="card"><div class="label">Holdings</div><div class="val" id="hold-count">...</div></div>
  </div>

  <pre id="debug">Loading data from Kite API...</pre>

  <script>
    async function load() {
      try {
        const [pos, trades, holdings] = await Promise.all([
          fetch('/api/positions').then(r => r.json()),
          fetch('/api/trades').then(r => r.json()),
          fetch('/api/holdings').then(r => r.json()),
        ]);
        document.getElementById('pos-count').textContent =
          (pos.net || []).length + (pos.day || []).length;
        document.getElementById('trade-count').textContent = trades.length;
        document.getElementById('hold-count').textContent  = holdings.length;
        document.getElementById('debug').textContent =
          JSON.stringify({ positions: pos, trades, holdings }, null, 2);
      } catch(e) {
        document.getElementById('debug').textContent = 'Error: ' + e.message;
      }
    }
    load();
  </script>
</body>
</html>'''


# ─────────────────────────────────────────────
if __name__ == '__main__':
    print('''
╔══════════════════════════════════════════╗
║  TradeLens — Flask dev server starting  ║
║  Visit: http://127.0.0.1:5000           ║
╚══════════════════════════════════════════╝
    ''')
    app.run(debug=True, port=5000)
# TradeLens — Trading Journal & Analytics Platform

A full-stack trading journal built on **Zerodha Kite Connect API**. Automatically syncs your trade history, computes risk-adjusted performance metrics, and visualises everything in a clean dashboard.

---

## Screenshots
![Dashboard preview](https://github.com/kedar1100/TradeLens/blob/main/img/dashboard.png)
![Analytics preview](https://github.com/kedar1100/TradeLencs/blob/main/img/analytics.png)
---

## What it does

- **OAuth login** via Zerodha Kite Connect — one click, no manual token handling
- **Auto-syncs** trades, positions, and holdings on every login
- **Computes** Sharpe ratio, Sortino ratio, CAGR, max drawdown, win rate, profit factor, expectancy
- **Visualises** equity curve, daily P&L bars, monthly heatmap, instrument breakdown
- **Analytics page** — deep-dive into drawdown analysis, win/loss streaks, weekday P&L patterns

---

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, Flask |
| Kite API | `kiteconnect` SDK (OAuth2) |
| Database | SQLite (via Python `sqlite3`) |
| Analytics | Pure Python — NumPy-free Sharpe/Sortino/drawdown |
| Frontend | Vanilla JS + Chart.js 4.4 |
| Deploy | Render (free tier) |

---

## Project structure

```
trading_journal/
├── app.py                  # Flask server — all routes
├── requirements.txt
├── .env.example
│
├── backend/
│   ├── analytics.py        # Sharpe, Sortino, CAGR, drawdown engine
│   ├── database.py         # SQLite schema + connection
│   ├── kite_client.py      # Authenticated KiteConnect singleton
│   ├── sync.py             # Kite API → SQLite data pipeline
│   └── token_store.py      # Access token persistence
│
├── frontend/
│   ├── dashboard.html      # Main dashboard
│   └── analytics.html      # Advanced analytics page
```

---

## API endpoints

| Method | Route | Description |
|---|---|---|
| `GET` | `/login` | Redirect to Kite OAuth login |
| `GET` | `/callback` | Handle Kite redirect, exchange token |
| `GET` | `/logout` | Invalidate token, clear session |
| `GET` | `/api/status` | Auth status + user info |
| `GET` | `/api/sync` | Trigger full Kite data sync |
| `GET` | `/api/analytics/summary` | Metrics cards (net P&L, win rate…) |
| `GET` | `/api/analytics/trades` | Full trade history |
| `GET` | `/api/analytics/pnl` | Closed P&L records |
| `GET` | `/api/analytics/advanced` | Sharpe, Sortino, drawdown, streaks |
| `GET` | `/api/analytics/instruments` | P&L by instrument |

All analytics endpoints accept a `?days=30` query param.

---

## Running locally

**1. Clone and install**
```bash
git clone https://github.com/yourusername/tradelens
cd tradelens
pip install -r requirements.txt
```

**2. Set up environment**
```bash
cp .env.example .env
# Fill in KITE_API_KEY, KITE_API_SECRET, FLASK_SECRET_KEY
```

**3. Set redirect URL in Kite developer console**

Go to [kite.trade/developers](https://kite.trade/developers) → your app → set:
```
Redirect URL:  http://127.0.0.1:5000/callback
Postback URL:  http://127.0.0.1:5000/postback
```

**5. Run**
```bash
python app.py
# Visit http://127.0.0.1:5000
```

## Author

**Kedar Oza**
[GitHub](https://github.com/kedar1100) · [LinkedIn](https://linkedin.com/in/kedar-oza1100)

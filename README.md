# TradeLens — Trading Journal & Analytics Platform

A full-stack trading journal built on **Zerodha Kite Connect API**. Automatically syncs your trade history, computes risk-adjusted performance metrics, and visualises everything in a clean dashboard.

---

## Live Demo
> **[tradelens.onrender.com](https://tradelens.onrender.com)** ← replace with your deployed URL

![Dashboard preview](https://placehold.co/900x480/f4f3ee/1D9E75?text=TradeLens+Dashboard)

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
├── seed_demo_data.py       # Populate DB with demo trades
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
│
└── data/
    ├── journal.db          # SQLite database (git-ignored)
    └── tokens.db           # Token store (git-ignored)
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

**4. (Optional) Seed demo data**
```bash
python seed_demo_data.py
```

**5. Run**
```bash
python app.py
# Visit http://127.0.0.1:5000
```

---

## Deploying to Render

**1. Push to GitHub**
```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/yourusername/tradelens
git push -u origin main
```

**2. Create a new Web Service on [render.com](https://render.com)**
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Add environment variables: `KITE_API_KEY`, `KITE_API_SECRET`, `FLASK_SECRET_KEY`

**3. Update Kite redirect URL**
```
Redirect URL: https://your-app-name.onrender.com/callback
```

---

## Key concepts

**Why SQLite?**
Trade data is append-only and single-user. SQLite is zero-config, fast enough for thousands of trades, and deploys as a single file. No Postgres setup needed.

**Why pure Python analytics?**
The Sharpe, Sortino, and drawdown calculations are ~50 lines of standard math. Pulling in NumPy/Pandas for that adds dependency weight with no real benefit at this scale.

**Token expiry handling**
Kite access tokens expire daily at midnight IST. The `token_store.py` module automatically detects stale tokens by comparing the creation date — no cron job needed.

---

## Author

**Kedar Chandraprakash Oza**
[GitHub](https://github.com/kedar1100) · [LinkedIn](https://linkedin.com/in/kedar-oza1100)
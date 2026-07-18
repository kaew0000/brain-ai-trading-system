# Brain Bot V14 Phase 4 — Command Office Deployment Guide

## Quick Start (30 seconds)

```bash
# 1. Start backend (Python/FastAPI)
cd brain_bot_v14/
python run_testnet.bat          # Windows
./run_testnet.sh                # Linux/Mac/Termux

# 2. Dashboard opens automatically at:
#    http://localhost:8000
#    (React SPA served from dashboard/dist/)
```

## Architecture

```
Browser ──→ FastAPI (port 8000) ──→ Binance API
              │
              ├── /api/*          REST endpoints
              ├── /ws/*           WebSocket streams
              ├── /assets/*       Vite static JS/CSS
              └── /*              → dashboard/dist/index.html (SPA)
```

## Dashboard Pages

| URL            | Page                  | Data Source                          |
|----------------|-----------------------|--------------------------------------|
| /              | Overview              | /api/decision + /ws/events + intel   |
| /agents        | Agent Floor           | /api/agents + /api/agents/telemetry  |
| /debate        | Debate Room           | /api/agents/reasoning + /agents/graph|
| /missions      | Mission Board         | /api/missions + /ws/missions         |
| /portfolio     | Portfolio Center      | /api/journal + /api/paper + signals  |
| /intelligence  | Market Intelligence   | /api/intelligence + /api/futures     |
| /memory        | AI Memory Center      | /api/journal explanations + messages |
| /replay        | Trade Replay          | /api/journal + /api/forward_test     |
| /commander     | Commander Console     | /api/command + /api/chat             |
| /health        | System Health         | /api/system/health + /api/ml/*       |

## WebSocket Subscriptions

| Socket          | Updates                          | Reconnects |
|-----------------|----------------------------------|------------|
| /ws/events      | All EventBus messages (live)     | Auto 2s    |
| /ws/decision    | CEO decision every cycle         | Auto 2s    |
| /ws/agents      | Agent state changes              | Auto 2s    |
| /ws/missions    | Mission lifecycle updates        | Auto 2s    |
| /ws/ml          | ML advisor predictions           | Auto 2s    |
| /ws/signals     | New trade signals                | Auto 2s    |

## Re-building the Frontend

```bash
cd dashboard_src/
npm install
npm run dev        # Dev mode with HMR at http://localhost:3000
                   # (proxies /api and /ws to localhost:8000)

npm run build      # Production build → ../fixed/dashboard/dist/
```

## File Structure

```
brain_bot_v14/
├── main.py                    # Entry point — starts API + trading loop
├── run_paper.bat/.sh          # Paper mode (no real orders)
├── run_testnet.bat/.sh        # Testnet mode (fake money)
├── run_live.bat/.sh           # Live trading (real money — confirm required)
│
├── api/app.py                 # FastAPI — serves React SPA + all endpoints
├── dashboard/
│   ├── index.html             # Legacy CDN dashboard (fallback)
│   └── dist/                  # Vite production build (primary)
│       ├── index.html
│       └── assets/
│           ├── index-*.js     # React bundle (~345kB, ~106kB gzip)
│           └── index-*.css    # Tailwind CSS (~23kB, ~5kB gzip)
│
├── system_health/             # Phase 3A — Watchdog, Heartbeat, Reconciliation
├── research/                  # Phase 3B — Data Lake, Feature Store
├── ml/                        # Phase 3C — ML Advisor, Model Registry
│
└── dashboard_src/             # React TypeScript source (Phase 4)
    ├── src/
    │   ├── types/api.ts       # All API response types
    │   ├── lib/api.ts         # Fetch helpers + WebSocket manager
    │   ├── stores/index.ts    # Zustand global state
    │   ├── hooks/useData.ts   # Data polling + WS subscription
    │   ├── components/
    │   │   ├── common/        # Panel, StatCard, DataTable, etc.
    │   │   └── layout/        # Sidebar nav + top bar
    │   └── pages/             # 10 dashboard pages
    ├── tailwind.config.cjs
    └── vite.config.ts

```

## Environment Variables

```bash
EXECUTION_MODE=testnet     # paper | testnet | live
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
BINANCE_TESTNET_API_KEY=...
BINANCE_TESTNET_API_SECRET=...
```

## Tech Stack

**Backend:** Python 3.10+ · FastAPI · SQLite · scikit-learn · schedule
**Frontend:** React 18 · TypeScript · Vite 5 · Tailwind CSS 3 · Framer Motion · Zustand · React Router v6
**Realtime:** WebSocket (FastAPI native) · 5s REST polling fallback

## Notes

- Dashboard auto-opens on `http://localhost:8000` when `main.py` starts
- All 10 pages are real-time — no mock data anywhere
- Polling intervals: decision 5s · health 8s · markets 10s · ML 15s
- WebSocket auto-reconnects every 2s on disconnect
- The `/commander` chat requires the `/api/chat` endpoint (may return 404 if bot version doesn't have it — shows error in chat, doesn't crash)
- Phase 3 ML models need 30+ labelled trades before first retrain fires

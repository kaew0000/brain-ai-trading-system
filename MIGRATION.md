# MIGRATION — World chat & meetings (V16 §83)

## Required
Rebuild the dashboard and restart the backend, then Ctrl+F5:

    cd dashboard_src && npm ci && npm run build

Log in first (open `/?token=<API key>` or use the login form): without a session every `/api/*` call returns 401.

## New settings (optional; defaults shown)
    WORLD_CHAT_ENABLED=true
    WORLD_CHAT_STORE_PATH=world/data/runtime/chat.json
    WORLD_CHAT_MAX_MESSAGES_PER_CHANNEL=500
    WORLD_CHAT_MAX_TEXT_CHARS=2000
    WORLD_MEETING_TURN_INTERVAL_SECONDS=3.0
    WORLD_MEETING_MIN_TURNS=5
    WORLD_MEETING_MAX_TURNS=50
    WORLD_MEETING_DEFAULT_TURNS=20

## Behaviour changes
- New World tab `Studio` (default). Other tabs are unchanged.
- New endpoints under `/api/world/chat/*`; `GET /api/world/chat/health` reports store/meeting/driver state.
- A meeting that was live when the process stopped is restored as `stopped`.

## Rollback
`WORLD_CHAT_ENABLED=false` (endpoints answer 503) or `git revert` the commit. Delete `world/data/runtime/chat.json` to clear history.

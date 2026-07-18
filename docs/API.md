# Brain Bot V16 API Documentation

## REST API

### GET /api/config

Returns runtime configuration.

---

### GET /api/status

Returns system status.

---

### POST /api/command

Execute system commands.

Supported Commands

- START
- STOP
- PAUSE
- RESUME
- PAPER
- LIVE

---

### GET /api/health

Health information.

---

### GET /api/risk

Current Risk Report.

---

### GET /api/scanner

Scanner snapshot.

---

### GET /api/ranking

Latest opportunity ranking.

---

## WebSocket

### /ws/command

Bi-directional command channel.

### Events

SYSTEM_STATUS

TRADE_OPEN

TRADE_CLOSE

SCANNER_UPDATE

RANKING_UPDATE

RISK_ALERT

ERROR

LOG
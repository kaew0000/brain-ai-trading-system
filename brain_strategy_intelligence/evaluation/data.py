"""DataAdapter implementations: SYNTHETIC (tests/demo only) and CSV (real data you supply).

Brain Bot's own data layer is NOT wrapped here because no stable public candle-history interface was verified
in the audit; implement `interfaces.DataAdapter` against it (see docs/INTEGRATION.md).
"""

from __future__ import annotations

import csv
import math
import random
from datetime import UTC, datetime
from pathlib import Path

from ..errors import DataError
from ..schemas import Candle

TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
}


class SyntheticDataAdapter:
    """Random-walk candles with alternating trend/range regimes. NOT market data - every result carries the label."""

    def __init__(self, n: int = 3000, seed: int = 7, bar_seconds: int = 900, start_price: float = 100.0) -> None:
        self.n, self.seed, self.bar_seconds, self.start_price = n, seed, bar_seconds, start_price
        self.label = f"SYNTHETIC(seed={seed},n={n})"
        self.regime_labels: list[str] = []

    def get_candles(
        self,
        symbol: str = "SYNUSDT",
        timeframe: str = "15m",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Candle]:
        rng = random.Random(self.seed)
        price, ts = self.start_price, 1_600_000_000
        out: list[Candle] = []
        self.regime_labels = []
        while len(out) < self.n:
            length = rng.randint(150, 400)
            trending = rng.random() < 0.5
            drift = rng.choice((-1, 1)) * 0.0006 if trending else 0.0
            level = price
            for _ in range(length):
                if len(out) >= self.n:
                    break
                shock = rng.gauss(0, 0.004)
                ret = drift + shock if trending else -0.05 * math.log(price / level) + shock
                new = max(price * math.exp(ret), 1e-6)
                hi = max(price, new) * (1 + abs(rng.gauss(0, 0.0015)))
                lo = min(price, new) * (1 - abs(rng.gauss(0, 0.0015)))
                out.append(Candle(ts=ts, open=price, high=hi, low=lo, close=new, volume=abs(rng.gauss(1000, 200))))
                self.regime_labels.append("TREND" if trending else "RANGE")
                price, ts = new, ts + self.bar_seconds
        return out


class CSVDataAdapter:
    """CSV columns: ts,open,high,low,close[,volume]. ts = epoch seconds or ISO-8601. Fails closed on any bad row."""

    def __init__(self, path: str | Path, label: str | None = None) -> None:
        self.path = Path(path)
        self.label = label or f"CSV:{self.path.name}"

    def get_candles(
        self, symbol: str = "", timeframe: str = "", start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]:
        if not self.path.is_file():
            raise DataError(f"data file not found: {self.path}")
        out: list[Candle] = []
        with self.path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            need = {"ts", "open", "high", "low", "close"}
            if not reader.fieldnames or not need <= {f.strip().lower() for f in reader.fieldnames}:
                raise DataError(f"CSV must have columns {sorted(need)}")
            for ln, row in enumerate(reader, start=2):
                r = {k.strip().lower(): v for k, v in row.items()}
                try:
                    raw = r["ts"].strip()
                    ts = int(raw) if raw.isdigit() else int(datetime.fromisoformat(raw).astimezone(UTC).timestamp())
                    out.append(
                        Candle(
                            ts=ts,
                            open=float(r["open"]),
                            high=float(r["high"]),
                            low=float(r["low"]),
                            close=float(r["close"]),
                            volume=float(r.get("volume") or 0.0),
                        )
                    )
                except (ValueError, KeyError, TypeError) as exc:
                    raise DataError(f"bad CSV row at line {ln}: {exc}") from exc
        s, e = (int(start.timestamp()) if start else None), (int(end.timestamp()) if end else None)
        return [c for c in out if (s is None or c.ts >= s) and (e is None or c.ts <= e)]

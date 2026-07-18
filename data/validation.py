"""
Data Layer: Validation

validate_ohlcv(df) checks an OHLCV DataFrame before it is passed to any
feature/regime/decision engine.

Checks
------
  - Required columns present (open, high, low, close, volume)
  - high >= low for every row
  - No missing (NaN) values in OHLCV columns
  - Datetime index is monotonic increasing (no out-of-order rows)
  - No duplicate timestamps

On failure, returns (False, reasons). Callers should log and either
drop bad rows (via clean_ohlcv) or skip the cycle entirely.
"""

from __future__ import annotations

import pandas as pd

from utils.logger import get_logger

logger = get_logger(__name__)

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def validate_ohlcv(df: pd.DataFrame, label: str = "") -> tuple[bool, list[str]]:
    """
    Validate an OHLCV DataFrame.

    Returns
    -------
    (is_valid, reasons) — is_valid is True only if reasons is empty.
    """
    reasons: list[str] = []

    if df is None or len(df) == 0:
        return False, ["empty dataframe"]

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        reasons.append(f"missing columns: {missing_cols}")
        # Can't run further checks without the columns
        return False, reasons

    nan_counts = df[list(REQUIRED_COLUMNS)].isna().sum()
    nan_cols = {c: int(n) for c, n in nan_counts.items() if n > 0}
    if nan_cols:
        reasons.append(f"NaN values present: {nan_cols}")

    bad_hl = (df["high"] < df["low"]).sum()
    if bad_hl > 0:
        reasons.append(f"{int(bad_hl)} rows where high < low")

    if isinstance(df.index, pd.DatetimeIndex):
        if not df.index.is_monotonic_increasing:
            reasons.append("datetime index is not monotonic increasing")
        dup_count = int(df.index.duplicated().sum())
        if dup_count > 0:
            reasons.append(f"{dup_count} duplicate timestamps")

    if reasons:
        logger.warning(f"validate_ohlcv [{label}] FAILED: {'; '.join(reasons)}")
        return False, reasons

    return True, []


def clean_ohlcv(df: pd.DataFrame, label: str = "") -> pd.DataFrame:
    """
    Best-effort cleanup of an OHLCV DataFrame:
      - drop duplicate timestamps (keep last)
      - sort by index
      - forward-fill small NaN gaps in OHLC, drop volume NaNs
      - drop rows where high < low

    Returns a cleaned copy. Does not raise; logs what it changed.
    """
    if df is None or len(df) == 0:
        return df

    out = df.copy()
    n0 = len(out)

    if isinstance(out.index, pd.DatetimeIndex):
        if out.index.duplicated().any():
            out = out[~out.index.duplicated(keep="last")]
        if not out.index.is_monotonic_increasing:
            out = out.sort_index()

    for col in ("open", "high", "low", "close"):
        if col in out.columns and out[col].isna().any():
            out[col] = out[col].ffill().bfill()

    if "volume" in out.columns and out["volume"].isna().any():
        out["volume"] = out["volume"].fillna(0.0)

    if "high" in out.columns and "low" in out.columns:
        bad = out["high"] < out["low"]
        if bad.any():
            out = out[~bad]

    n1 = len(out)
    if n1 != n0:
        logger.warning(f"clean_ohlcv [{label}]: {n0 - n1} rows removed during cleanup")

    return out

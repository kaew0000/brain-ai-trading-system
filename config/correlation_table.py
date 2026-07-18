"""
config/correlation_table.py — V16 Phase 2A: static correlation reference

VERSION 1 — TIER-BASED, NOT COMPUTED. This is a hand-curated approximation
of which symbols tend to move together, not a statistical measurement.
No real correlation data exists anywhere in this codebase yet: the
scanner (scanner/market_scanner.py) only ever keeps the LATEST snapshot
per symbol, no historical price series — so Pearson/rolling correlation
simply isn't computable today. docs/architecture.md §16 already flags
this as open ("Correlation Engine — needs a decision on data source...
Not started"); this table is that decision for now, deliberately chosen
over blocking Capital Allocation on infrastructure that doesn't exist.

**Real (price-history-based) correlation is planned to replace this** —
see architecture.md §17 for the follow-up note. When it lands, this file
and correlation_engine.py's tier lookup are what gets replaced; nothing
else in portfolio/ should need to change, since capital_manager.py only
ever consumes CorrelationEngine's (tier, penalty) output, never this
table directly.

Design: two-level grouping rather than a hand-written NxN pair matrix
(infeasible to maintain at ~300 symbols — that's 44,850 pairs). Every
symbol maps to one fine-grained CLUSTER; every cluster belongs to one
coarser SUPER_GROUP.
  - same cluster              → HIGH
  - different cluster,
    same super-group          → MEDIUM
  - different super-group     → LOW
  - either symbol not listed  → UNKNOWN (most conservative — see
                                 correlation_engine.py for why UNKNOWN
                                 gets the harshest penalty, not a neutral
                                 one)

This is deliberately NOT the same taxonomy as the eventual Sector Engine
(2B, portfolio/sector_engine.py — Layer1/Meme/DeFi/Gaming/etc. per the
original brief). Correlation clusters group by "tends to move together";
sectors group by "same business category" — related but not identical
(e.g. LINK and GRT are both "oracle/infra" for correlation purposes, but
the brief's sector list doesn't have an Oracle bucket at all). 2B should
decide independently whether to reuse, reference, or diverge from this
file — flagging so that decision doesn't get made by accident via import.

Coverage: ~100 major/mid-cap USDT perpetuals, not all ~300 the scanner
covers. Anything not listed resolves to UNKNOWN via correlation_engine.py,
not an exception — a new/thin-history symbol appearing in the scanner
universe before someone curates its entry is expected, not a bug.
"""
from __future__ import annotations

from typing import Dict, Optional

# ── symbol → cluster ─────────────────────────────────────────────────────
# Keys are base symbols without the USDT suffix (correlation_engine.py
# strips "USDT"/"BUSD" before lookup) so this table doesn't have to be
# quote-asset-aware.

SYMBOL_CLUSTERS: Dict[str, str] = {
    # -- Majors (BTC + ETH explicitly, per the brief's own "BTC ETH = High" example) --
    "BTC": "MAJORS", "ETH": "MAJORS",

    # -- Large-cap L1 --
    "SOL": "LARGE_CAP_L1", "BNB": "LARGE_CAP_L1", "ADA": "LARGE_CAP_L1",
    "AVAX": "LARGE_CAP_L1", "DOT": "LARGE_CAP_L1", "TON": "LARGE_CAP_L1",
    "NEAR": "LARGE_CAP_L1", "APT": "LARGE_CAP_L1", "SUI": "LARGE_CAP_L1",
    "SEI": "LARGE_CAP_L1",

    # -- Mid-cap / legacy L1 --
    "ATOM": "MID_CAP_L1", "ALGO": "MID_CAP_L1", "EOS": "MID_CAP_L1",
    "XTZ": "MID_CAP_L1", "ICP": "MID_CAP_L1", "FTM": "MID_CAP_L1",
    "S": "MID_CAP_L1", "KAVA": "MID_CAP_L1", "CFX": "MID_CAP_L1",
    "ETC": "MID_CAP_L1",

    # -- L2 / scaling --
    "ARB": "L2_SCALING", "OP": "L2_SCALING", "MATIC": "L2_SCALING",
    "POL": "L2_SCALING", "STRK": "L2_SCALING", "ZK": "L2_SCALING",
    "MANTA": "L2_SCALING", "METIS": "L2_SCALING",

    # -- Meme --
    "DOGE": "MEME", "SHIB": "MEME", "PEPE": "MEME", "FLOKI": "MEME",
    "BONK": "MEME", "WIF": "MEME", "MEME": "MEME", "1000SATS": "MEME",
    "ORDI": "MEME",

    # -- DeFi blue-chip --
    "UNI": "DEFI_BLUECHIP", "AAVE": "DEFI_BLUECHIP", "MKR": "DEFI_BLUECHIP",
    "CRV": "DEFI_BLUECHIP", "LDO": "DEFI_BLUECHIP", "SNX": "DEFI_BLUECHIP",
    "COMP": "DEFI_BLUECHIP", "SUSHI": "DEFI_BLUECHIP", "1INCH": "DEFI_BLUECHIP",
    "PENDLE": "DEFI_BLUECHIP",

    # -- Oracle / infra --
    "LINK": "ORACLE_INFRA", "GRT": "ORACLE_INFRA", "BAND": "ORACLE_INFRA",
    "API3": "ORACLE_INFRA",

    # -- AI / data --
    "FET": "AI_DATA", "RENDER": "AI_DATA", "TAO": "AI_DATA",
    "WLD": "AI_DATA", "OCEAN": "AI_DATA", "AGIX": "AI_DATA",
    "AKT": "AI_DATA",

    # -- Gaming / metaverse --
    "SAND": "GAMING_METAVERSE", "MANA": "GAMING_METAVERSE",
    "AXS": "GAMING_METAVERSE", "GALA": "GAMING_METAVERSE",
    "IMX": "GAMING_METAVERSE", "ILV": "GAMING_METAVERSE",
    "BEAMX": "GAMING_METAVERSE",

    # -- Privacy --
    "XMR": "PRIVACY", "ZEC": "PRIVACY", "SCRT": "PRIVACY",

    # -- Legacy payments --
    "XRP": "PAYMENTS_LEGACY", "XLM": "PAYMENTS_LEGACY", "LTC": "PAYMENTS_LEGACY",
    "BCH": "PAYMENTS_LEGACY", "TRX": "PAYMENTS_LEGACY",

    # -- Derivatives / perps-native protocols --
    "GMX": "DERIVATIVES_PROTOCOL", "DYDX": "DERIVATIVES_PROTOCOL",
    "RUNE": "DERIVATIVES_PROTOCOL", "INJ": "DERIVATIVES_PROTOCOL",
    "GNS": "DERIVATIVES_PROTOCOL",

    # -- RWA / stablecoin-adjacent yield --
    "ONDO": "RWA", "ENA": "RWA",
}

# ── cluster → super-group ────────────────────────────────────────────────

CLUSTER_SUPER_GROUP: Dict[str, str] = {
    "MAJORS":               "BLUE_CHIP",
    "LARGE_CAP_L1":         "BLUE_CHIP",
    "MID_CAP_L1":           "ALT_ECOSYSTEM",
    "L2_SCALING":           "ALT_ECOSYSTEM",
    "DEFI_BLUECHIP":        "ALT_ECOSYSTEM",
    "ORACLE_INFRA":         "ALT_ECOSYSTEM",
    "AI_DATA":              "ALT_ECOSYSTEM",
    "GAMING_METAVERSE":     "ALT_ECOSYSTEM",
    "DERIVATIVES_PROTOCOL": "ALT_ECOSYSTEM",
    "RWA":                  "ALT_ECOSYSTEM",
    "MEME":                 "MEME",
    "PRIVACY":              "PRIVACY",
    "PAYMENTS_LEGACY":      "LEGACY_PAYMENTS",
}


def cluster_of(base_symbol: str) -> Optional[str]:
    return SYMBOL_CLUSTERS.get(base_symbol.upper())


def super_group_of(base_symbol: str) -> Optional[str]:
    cluster = cluster_of(base_symbol)
    return CLUSTER_SUPER_GROUP.get(cluster) if cluster else None

"""
config/sector_table.py — V16 Phase 2B: static sector reference

VERSION 1 — HAND-CURATED, NOT DERIVED. Same category of decision as
config/correlation_table.py (see that file's module docstring for the
full precedent): no on-chain/business-category data source exists
anywhere in this codebase, so "which business category does this symbol
belong to" is a curated lookup table, not a computed classification.

Deliberately NOT the same taxonomy as config/correlation_table.py
------------------------------------------------------------------------
correlation_table.py groups symbols by "tends to move together"
(CLUSTER/SUPER_GROUP, price-behavior driven). This table groups symbols
by "same business category" (SECTOR, product/use-case driven). The two
often agree (e.g. DOGE is both MEME-correlated and Meme-sector) but not
always (e.g. LINK is ORACLE_INFRA-clustered for correlation purposes,
but this table's fixed 13-sector list has no dedicated Oracle bucket
distinct from Infrastructure) — portfolio/correlation_table.py's own
docstring flags this divergence as an intentional, already-made decision
so it doesn't happen by accident via import. portfolio/sector_engine.py
and portfolio/correlation_engine.py each own their own table; neither
imports the other's.

Sectors (fixed list, 13 total, "Unknown" is a first-class bucket, not
an error state)
------------------------------------------------------------------------
    Layer1, Layer2, DeFi, Meme, AI, Infrastructure, Exchange,
    Stablecoin, Privacy, Oracle, Gaming, RWA, Unknown

Coverage: ~110 major/mid-cap USDT perpetuals — not all ~300 the scanner
covers. Anything not listed resolves to "Unknown" (see sector_of()
below), matching this table's own explicit sector rather than raising —
a new/thin-history symbol appearing in the scanner universe before
someone curates its entry is expected, not a bug. Unlike
correlation_table.py's CorrelationTier.UNKNOWN (deliberately the
*harshest* penalty), an unclassified sector here is intentionally
neutral: sector exposure/diversification math treats "Unknown" as one
sector among the other 12, competing for the same max_sector_pct cap
like any other — there is no analogous "penalize the unverified case
harder" reasoning for sector exposure the way there is for correlation
risk.

**Meant to be extended, not replaced wholesale.** Add new symbol entries
to SYMBOL_SECTORS as they're needed; the 13-sector list itself should
change rarely, since portfolio/sector_engine.py's diversification-score
math assumes a roughly-stable sector universe from cycle to cycle.
"""
from __future__ import annotations


# ── Fixed sector list ───────────────────────────────────────────────────────
# Order matters only for documentation/iteration purposes below — lookups
# are by dict key, not list position.

SECTORS = (
    "Layer1",
    "Layer2",
    "DeFi",
    "Meme",
    "AI",
    "Infrastructure",
    "Exchange",
    "Stablecoin",
    "Privacy",
    "Oracle",
    "Gaming",
    "RWA",
    "Unknown",
)

UNKNOWN_SECTOR = "Unknown"

# ── symbol → sector ──────────────────────────────────────────────────────────
# Keys are base symbols without the USDT/BUSD/USDC/FDUSD suffix —
# portfolio/sector_engine.py strips it before lookup, exactly mirroring
# correlation_engine.py's _base_symbol() convention, so this table
# doesn't have to be quote-asset-aware.

SYMBOL_SECTORS: dict[str, str] = {
    # -- Layer1 --
    "BTC": "Layer1", "ETH": "Layer1", "SOL": "Layer1", "BNB": "Layer1",
    "ADA": "Layer1", "AVAX": "Layer1", "DOT": "Layer1", "TON": "Layer1",
    "NEAR": "Layer1", "APT": "Layer1", "SUI": "Layer1", "SEI": "Layer1",
    "ATOM": "Layer1", "ALGO": "Layer1", "EOS": "Layer1", "XTZ": "Layer1",
    "ICP": "Layer1", "FTM": "Layer1", "S": "Layer1", "KAVA": "Layer1",
    "CFX": "Layer1", "ETC": "Layer1", "XRP": "Layer1", "XLM": "Layer1",
    "LTC": "Layer1", "BCH": "Layer1", "TRX": "Layer1", "HBAR": "Layer1",
    "EGLD": "Layer1", "FLOW": "Layer1", "KAS": "Layer1", "CELO": "Layer1",

    # -- Layer2 / scaling --
    "ARB": "Layer2", "OP": "Layer2", "MATIC": "Layer2", "POL": "Layer2",
    "STRK": "Layer2", "ZK": "Layer2", "MANTA": "Layer2", "METIS": "Layer2",
    "IMX": "Layer2", "BLAST": "Layer2",

    # -- DeFi --
    "UNI": "DeFi", "AAVE": "DeFi", "MKR": "DeFi", "CRV": "DeFi",
    "LDO": "DeFi", "SNX": "DeFi", "COMP": "DeFi", "SUSHI": "DeFi",
    "1INCH": "DeFi", "PENDLE": "DeFi", "GMX": "DeFi", "DYDX": "DeFi",
    "RUNE": "DeFi", "INJ": "DeFi", "GNS": "DeFi", "CAKE": "DeFi",
    "JOE": "DeFi", "BAL": "DeFi",

    # -- Meme --
    "DOGE": "Meme", "SHIB": "Meme", "PEPE": "Meme", "FLOKI": "Meme",
    "BONK": "Meme", "WIF": "Meme", "MEME": "Meme", "1000SATS": "Meme",
    "ORDI": "Meme", "POPCAT": "Meme", "BRETT": "Meme",

    # -- AI --
    "FET": "AI", "RENDER": "AI", "TAO": "AI", "WLD": "AI",
    "OCEAN": "AI", "AGIX": "AI", "AKT": "AI", "ARKM": "AI",

    # -- Infrastructure (oracle/data/interop/dev-tooling, kept distinct
    #    from "AI" and from correlation_table.py's own ORACLE_INFRA
    #    cluster — see module docstring on why the taxonomies diverge) --
    "LINK": "Infrastructure", "GRT": "Infrastructure", "BAND": "Infrastructure",
    "API3": "Infrastructure", "SCRT": "Infrastructure",

    # -- Exchange tokens --
    # Note: BNB is classified as Layer1 above (it is BNB Chain's native
    # gas/L1 asset first), not here, even though Binance is also an
    # exchange — avoids double-modeling one symbol into two sectors.
    "OKB": "Exchange", "CRO": "Exchange", "GT": "Exchange", "KCS": "Exchange",
    "HT": "Exchange", "LEO": "Exchange",

    # -- Stablecoin-adjacent (perp markets on stable-yield/RWA-stable
    #    protocols; true stablecoins like USDC/USDT aren't traded as
    #    directional perps so won't appear as scanner symbols, but the
    #    bucket exists for protocol tokens tied to stablecoin yield) --
    "USDD": "Stablecoin", "FRAX": "Stablecoin", "FDUSD": "Stablecoin",

    # -- Privacy --
    "XMR": "Privacy", "ZEC": "Privacy", "DASH": "Privacy",

    # -- Oracle --
    # (kept separate from "Infrastructure" per the brief's explicit
    # 13-sector list — LINK is the canonical example and is deliberately
    # placed under Infrastructure above, not here, since LINK's primary
    # use case (price oracle feeds) already anchors Infrastructure;
    # this bucket exists for the brief's explicit list and picks up any
    # future oracle-specific symbol curated in on its own.)

    # -- Gaming --
    "SAND": "Gaming", "MANA": "Gaming", "AXS": "Gaming", "GALA": "Gaming",
    "ILV": "Gaming", "BEAMX": "Gaming", "PIXEL": "Gaming", "MAGIC": "Gaming",
    "YGG": "Gaming",

    # -- RWA --
    "ONDO": "RWA", "ENA": "RWA", "POLYX": "RWA", "TRU": "RWA",
}


def sector_of(base_symbol: str) -> str:
    """
    Looks up an already-suffix-stripped base symbol (e.g. "BTC", not
    "BTCUSDT") directly against the table. Returns UNKNOWN_SECTOR
    ("Unknown") for anything not listed — never raises, mirroring
    correlation_table.py's cluster_of() returning None for the same
    case, except here the "not listed" case has its own named sector
    rather than an absent value, since PortfolioLimits.max_sector_pct
    needs every symbol to resolve to *some* sector to be enforceable.
    """
    return SYMBOL_SECTORS.get(base_symbol.upper(), UNKNOWN_SECTOR)

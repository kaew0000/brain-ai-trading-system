"""tests/test_sector_engine.py — V16 Phase 2B

Every position is a minimal duck-typed stand-in (symbol/notional only) —
SectorEngine never touches PortfolioPosition.sector (see its module
docstring), so these tests don't need the full PortfolioPosition
constructor.
"""
from __future__ import annotations

import pytest

from config.sector_table import SECTORS, SYMBOL_SECTORS, UNKNOWN_SECTOR, sector_of
from portfolio.sector_engine import SectorEngine

pytestmark = pytest.mark.unit


class _Pos:
    def __init__(self, symbol, notional):
        self.symbol = symbol
        self.notional = notional


# ── config/sector_table.py ───────────────────────────────────────────────

class TestSectorTable:

    def test_sectors_tuple_has_thirteen_entries(self):
        assert len(SECTORS) == 13

    def test_all_required_sectors_present(self):
        required = {
            "Layer1", "Layer2", "DeFi", "Meme", "AI", "Infrastructure",
            "Exchange", "Stablecoin", "Privacy", "Oracle", "Gaming",
            "RWA", "Unknown",
        }
        assert set(SECTORS) == required

    def test_unknown_sector_constant(self):
        assert UNKNOWN_SECTOR == "Unknown"

    def test_sector_of_known_symbol(self):
        assert sector_of("BTC") == "Layer1"

    def test_sector_of_unknown_symbol_returns_unknown(self):
        assert sector_of("SOMECOINNOBODYHASHEARDOF") == UNKNOWN_SECTOR

    def test_sector_of_case_insensitive(self):
        assert sector_of("btc") == "Layer1"

    def test_every_table_value_is_a_valid_sector(self):
        for symbol, sector in SYMBOL_SECTORS.items():
            assert sector in SECTORS, f"{symbol} maps to invalid sector {sector}"

    def test_table_has_substantial_coverage(self):
        # not exhaustive by design (see module docstring) but should cover
        # a meaningful slice of the majors
        assert len(SYMBOL_SECTORS) >= 80

    @pytest.mark.parametrize("symbol,expected", [
        ("BTC", "Layer1"), ("ETH", "Layer1"), ("SOL", "Layer1"), ("BNB", "Layer1"),
        ("ARB", "Layer2"), ("OP", "Layer2"),
        ("UNI", "DeFi"), ("AAVE", "DeFi"),
        ("DOGE", "Meme"), ("PEPE", "Meme"),
        ("FET", "AI"), ("RENDER", "AI"),
        ("LINK", "Infrastructure"),
        ("XMR", "Privacy"), ("ZEC", "Privacy"),
        ("SAND", "Gaming"), ("AXS", "Gaming"),
        ("ONDO", "RWA"),
        ("OKB", "Exchange"),
    ])
    def test_known_classifications(self, symbol, expected):
        assert sector_of(symbol) == expected


# ── SectorEngine.sector_of ───────────────────────────────────────────────

class TestSectorEngineLookup:

    def test_sector_of_strips_usdt_suffix(self):
        assert SectorEngine.sector_of("BTCUSDT") == "Layer1"

    def test_sector_of_strips_busd_suffix(self):
        assert SectorEngine.sector_of("ETHBUSD") == "Layer1"

    def test_sector_of_strips_usdc_suffix(self):
        assert SectorEngine.sector_of("SOLUSDC") == "Layer1"

    def test_sector_of_strips_fdusd_suffix(self):
        assert SectorEngine.sector_of("DOGEFDUSD") == "Meme"

    def test_sector_of_lowercase_symbol(self):
        assert SectorEngine.sector_of("btcusdt") == "Layer1"

    def test_sector_of_unknown_returns_unknown_bucket(self):
        assert SectorEngine.sector_of("NOTASYMBOLUSDT") == "Unknown"

    def test_sector_of_symbol_without_suffix_still_resolves(self):
        assert SectorEngine.sector_of("BTC") == "Layer1"

    def test_sectors_class_attribute_matches_table(self):
        assert SectorEngine.SECTORS == SECTORS


# ── SectorEngine.exposure_by_sector ──────────────────────────────────────

class TestExposureBySector:

    def test_empty_positions_returns_empty_dict(self):
        assert SectorEngine.exposure_by_sector([]) == {}

    def test_single_position(self):
        positions = [_Pos("BTCUSDT", 10000.0)]
        assert SectorEngine.exposure_by_sector(positions) == {"Layer1": 10000.0}

    def test_multiple_positions_same_sector_sum(self):
        positions = [_Pos("BTCUSDT", 5000.0), _Pos("ETHUSDT", 3000.0)]
        assert SectorEngine.exposure_by_sector(positions) == {"Layer1": 8000.0}

    def test_multiple_positions_different_sectors(self):
        positions = [_Pos("BTCUSDT", 5000.0), _Pos("UNIUSDT", 2000.0), _Pos("DOGEUSDT", 1000.0)]
        exposure = SectorEngine.exposure_by_sector(positions)
        assert exposure == {"Layer1": 5000.0, "DeFi": 2000.0, "Meme": 1000.0}

    def test_unknown_symbol_grouped_under_unknown(self):
        positions = [_Pos("TOTALLYFAKEUSDT", 500.0)]
        assert SectorEngine.exposure_by_sector(positions) == {"Unknown": 500.0}

    def test_zero_notional_position_still_appears(self):
        positions = [_Pos("BTCUSDT", 0.0)]
        assert SectorEngine.exposure_by_sector(positions) == {"Layer1": 0.0}


# ── SectorEngine.sector_exposure_pct ─────────────────────────────────────

class TestSectorExposurePct:

    def test_zero_balance_returns_zero(self):
        positions = [_Pos("BTCUSDT", 5000.0)]
        assert SectorEngine.sector_exposure_pct(positions, "Layer1", 0.0) == 0.0

    def test_negative_balance_returns_zero(self):
        positions = [_Pos("BTCUSDT", 5000.0)]
        assert SectorEngine.sector_exposure_pct(positions, "Layer1", -100.0) == 0.0

    def test_normal_pct_calculation(self):
        positions = [_Pos("BTCUSDT", 5000.0)]
        assert SectorEngine.sector_exposure_pct(positions, "Layer1", 10000.0) == pytest.approx(0.5)

    def test_sector_with_no_exposure_returns_zero(self):
        positions = [_Pos("BTCUSDT", 5000.0)]
        assert SectorEngine.sector_exposure_pct(positions, "Gaming", 10000.0) == 0.0

    def test_can_exceed_one_at_high_leverage(self):
        positions = [_Pos("BTCUSDT", 50000.0)]
        assert SectorEngine.sector_exposure_pct(positions, "Layer1", 10000.0) == pytest.approx(5.0)


# ── SectorEngine.diversification_score(_from_exposure) ──────────────────

class TestDiversificationScore:

    def test_no_positions_returns_100(self):
        assert SectorEngine.diversification_score([]) == 100.0

    def test_single_sector_fully_concentrated_returns_zero(self):
        positions = [_Pos("BTCUSDT", 10000.0)]
        assert SectorEngine.diversification_score(positions) == pytest.approx(0.0)

    def test_two_equal_sectors_scores_fifty(self):
        positions = [_Pos("BTCUSDT", 5000.0), _Pos("UNIUSDT", 5000.0)]
        # HHI = 0.5^2 + 0.5^2 = 0.5 -> score = 100*(1-0.5) = 50
        assert SectorEngine.diversification_score(positions) == pytest.approx(50.0)

    def test_more_sectors_scores_higher_than_fewer(self):
        two_sector = [_Pos("BTCUSDT", 5000.0), _Pos("UNIUSDT", 5000.0)]
        four_sector = [_Pos("BTCUSDT", 2500.0), _Pos("UNIUSDT", 2500.0),
                        _Pos("DOGEUSDT", 2500.0), _Pos("FETUSDT", 2500.0)]
        assert (SectorEngine.diversification_score(four_sector)
                > SectorEngine.diversification_score(two_sector))

    def test_score_bounded_between_zero_and_hundred(self):
        positions = [_Pos("BTCUSDT", 1234.0), _Pos("UNIUSDT", 5678.0), _Pos("DOGEUSDT", 91.0)]
        score = SectorEngine.diversification_score(positions)
        assert 0.0 <= score <= 100.0

    def test_uneven_split_scores_lower_than_even_split_same_sector_count(self):
        even   = [_Pos("BTCUSDT", 5000.0), _Pos("UNIUSDT", 5000.0)]
        uneven = [_Pos("BTCUSDT", 9000.0), _Pos("UNIUSDT", 1000.0)]
        assert (SectorEngine.diversification_score(even)
                > SectorEngine.diversification_score(uneven))

    def test_from_exposure_matches_positions_version(self):
        positions = [_Pos("BTCUSDT", 3000.0), _Pos("UNIUSDT", 7000.0)]
        exposure = SectorEngine.exposure_by_sector(positions)
        assert (SectorEngine.diversification_score_from_exposure(exposure)
                == SectorEngine.diversification_score(positions))

    def test_from_exposure_empty_dict(self):
        assert SectorEngine.diversification_score_from_exposure({}) == 100.0

    def test_from_exposure_all_zero_values(self):
        assert SectorEngine.diversification_score_from_exposure({"Layer1": 0.0, "DeFi": 0.0}) == 100.0

    def test_from_exposure_never_negative(self):
        exposure = {"Layer1": 1.0, "DeFi": 1.0, "Meme": 1.0, "AI": 1.0, "Gaming": 1.0}
        assert SectorEngine.diversification_score_from_exposure(exposure) >= 0.0


# ── SectorEngine.most_concentrated_sector ────────────────────────────────

class TestMostConcentratedSector:

    def test_no_positions_returns_none(self):
        assert SectorEngine.most_concentrated_sector([]) is None

    def test_single_position(self):
        positions = [_Pos("BTCUSDT", 5000.0)]
        assert SectorEngine.most_concentrated_sector(positions) == ("Layer1", 5000.0)

    def test_returns_largest_sector(self):
        positions = [_Pos("BTCUSDT", 1000.0), _Pos("UNIUSDT", 9000.0)]
        assert SectorEngine.most_concentrated_sector(positions) == ("DeFi", 9000.0)

    def test_three_way_split_returns_biggest(self):
        positions = [_Pos("BTCUSDT", 100.0), _Pos("UNIUSDT", 9000.0), _Pos("DOGEUSDT", 500.0)]
        sector, exposure = SectorEngine.most_concentrated_sector(positions)
        assert sector == "DeFi"
        assert exposure == 9000.0

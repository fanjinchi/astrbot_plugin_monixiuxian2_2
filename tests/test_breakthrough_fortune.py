"""Tests for the post-breakthrough fortune wheel.

Covers:
- Fortune config loading and defaults
- Level-window filtering for weapons/heart methods/pills
- Weighted random choice with seeded rng
- roll_breakthrough_fortune branch behaviour and messages
- Empty pools and "nothing" outcomes
"""

import random

import pytest

from tests.helpers import load_module

_fortune_mod = load_module("breakthrough_fortune", "core/breakthrough_fortune.py")

get_fortune_config = _fortune_mod.get_fortune_config
filter_items_by_level = _fortune_mod.filter_items_by_level
weighted_random_choice = _fortune_mod.weighted_random_choice
roll_breakthrough_fortune = _fortune_mod.roll_breakthrough_fortune
format_fortune_message = _fortune_mod.format_fortune_message


WEAPONS = [
    {"name": "木剑", "required_level_index": 0, "rank": "凡品", "shop_weight": 100},
    {"name": "精钢剑", "required_level_index": 0, "rank": "凡品", "shop_weight": 80},
    {"name": "碧水灵剑", "required_level_index": 10, "rank": "灵品", "shop_weight": 50},
    {"name": "太虚道剑", "required_level_index": 28, "rank": "道品", "shop_weight": 1},
]

HEART_METHODS = [
    {"name": "长春功", "required_level_index": 0, "rank": "凡品", "shop_weight": 100},
    {"name": "焚天诀", "required_level_index": 10, "rank": "圣品", "shop_weight": 20},
]

PILLS = [
    {"name": "回生丹", "required_level_index": 0, "rank": "仙品", "shop_weight": 10},
    {
        "name": "修炼加速丹",
        "required_level_index": 0,
        "rank": "凡品",
        "shop_weight": 100,
    },
    {
        "name": "玄元加速丹",
        "required_level_index": 10,
        "rank": "地品",
        "shop_weight": 50,
    },
]


def _game_config(overrides: dict | None = None) -> dict:
    base = {"fortune": {}}
    if overrides:
        base["fortune"].update(overrides)
    return base


class TestFortuneConfig:
    def test_defaults_populated(self):
        cfg = get_fortune_config({})
        assert cfg["weapon_rate"] == pytest.approx(0.12)
        assert cfg["heart_method_rate"] == pytest.approx(0.08)
        assert cfg["pill_rate"] == pytest.approx(0.20)
        assert cfg["level_window"] == 10
        assert cfg["pill_count_min"] == 1
        assert cfg["pill_count_max"] == 2

    def test_overrides_respected(self):
        cfg = get_fortune_config(_game_config({"weapon_rate": 0.5, "level_window": 5}))
        assert cfg["weapon_rate"] == pytest.approx(0.5)
        assert cfg["level_window"] == 5

    def test_rates_clamped_to_valid_range(self):
        cfg = get_fortune_config(_game_config({"weapon_rate": 1.5, "pill_rate": -0.1}))
        assert cfg["weapon_rate"] == pytest.approx(1.0)
        assert cfg["pill_rate"] == pytest.approx(0.0)

    def test_pill_count_bounds_sanitized(self):
        cfg = get_fortune_config(
            _game_config({"pill_count_min": 3, "pill_count_max": 1})
        )
        assert cfg["pill_count_min"] == 3
        assert cfg["pill_count_max"] == 3


class TestLevelFiltering:
    def test_includes_items_within_window(self):
        result = filter_items_by_level(WEAPONS, new_level_index=10, level_window=10)
        names = {w["name"] for w in result}
        assert "碧水灵剑" in names
        assert "木剑" in names

    def test_excludes_items_far_below_level(self):
        result = filter_items_by_level(WEAPONS, new_level_index=35, level_window=10)
        names = {w["name"] for w in result}
        assert "太虚道剑" in names
        assert "碧水灵剑" not in names

    def test_excludes_items_above_level(self):
        result = filter_items_by_level(WEAPONS, new_level_index=5, level_window=10)
        names = {w["name"] for w in result}
        assert "碧水灵剑" not in names
        assert "木剑" in names

    def test_excludes_zero_weight_items(self):
        items = [{"name": "幽灵剑", "required_level_index": 0, "shop_weight": 0}]
        assert filter_items_by_level(items, 10) == []


class TestWeightedRandomChoice:
    def test_deterministic_with_seed(self):
        rng = random.Random(42)
        chosen = weighted_random_choice(WEAPONS, rng)
        # With a fixed seed the choice must be deterministic.
        rng2 = random.Random(42)
        assert chosen == weighted_random_choice(WEAPONS, rng2)

    def test_returns_none_for_empty_pool(self):
        assert weighted_random_choice([], random.Random(0)) is None

    def test_returns_none_when_total_weight_is_zero(self):
        items = [{"name": "无重", "shop_weight": 0}]
        assert weighted_random_choice(items, random.Random(0)) is None

    def test_higher_weight_items_win_more_often(self):
        items = [
            {"name": "common", "shop_weight": 1000},
            {"name": "rare", "shop_weight": 1},
        ]
        rng = random.Random(0)
        common_wins = 0
        for _ in range(1000):
            if weighted_random_choice(items, rng)["name"] == "common":
                common_wins += 1
        assert common_wins > 900


class TestFortuneRoll:
    def test_weapon_drop(self):
        cfg = _game_config({"weapon_rate": 1.0, "heart_method_rate": 0, "pill_rate": 0})
        result = roll_breakthrough_fortune(
            random.Random(0), cfg, 35, WEAPONS, HEART_METHODS, PILLS
        )
        assert result is not None
        assert result["type"] == "weapon"
        assert len(result["items"]) == 1
        assert "机缘天降" in result["message"]

    def test_heart_method_drop(self):
        cfg = _game_config({"weapon_rate": 0, "heart_method_rate": 1.0, "pill_rate": 0})
        result = roll_breakthrough_fortune(
            random.Random(0), cfg, 10, WEAPONS, HEART_METHODS, PILLS
        )
        assert result is not None
        assert result["type"] == "heart_method"
        assert "福至心灵" in result["message"]

    def test_pill_drop_count_and_message(self):
        cfg = _game_config({"weapon_rate": 0, "heart_method_rate": 0, "pill_rate": 1.0})
        # Run many times to verify count bounds.
        counts = []
        rng = random.Random(0)
        for _ in range(200):
            result = roll_breakthrough_fortune(
                rng, cfg, 10, WEAPONS, HEART_METHODS, PILLS
            )
            assert result is not None
            assert result["type"] == "pill"
            total = sum(item["count"] for item in result["items"])
            assert 1 <= total <= 2
            counts.append(total)
            assert "仙缘际会" in result["message"]
        assert any(c == 1 for c in counts)
        assert any(c == 2 for c in counts)

    def test_nothing_outcome(self):
        cfg = _game_config({"weapon_rate": 0, "heart_method_rate": 0, "pill_rate": 0})
        result = roll_breakthrough_fortune(
            random.Random(0), cfg, 35, WEAPONS, HEART_METHODS, PILLS
        )
        assert result is None

    def test_empty_pool_returns_none(self):
        cfg = _game_config({"weapon_rate": 1.0, "heart_method_rate": 0, "pill_rate": 0})
        result = roll_breakthrough_fortune(
            random.Random(0), cfg, 35, [], HEART_METHODS, PILLS
        )
        assert result is None

    def test_format_fortune_message_empty(self):
        assert format_fortune_message(None) == ""

    def test_format_fortune_message_non_empty(self):
        result = {
            "type": "weapon",
            "items": [{"name": "木剑", "count": 1, "data": {}}],
            "message": "🎁 机缘天降，获得武器【木剑】（凡品）！",
        }
        assert "机缘天降" in format_fortune_message(result)

"""Tests for growth model (Plan A) and breakthrough fail-streak pity.

Covers:
- _roll_growth_points deterministic behaviour with seeded random
- _apply_pity_bonus edge cases (guarantee, cap, zero streak)
- Player model breakthrough_fail_streak field round-trip
- Migration v27 schema changes
- game_config.json skill_system new keys
"""

import json
import random

import pytest

from tests.helpers import load_module

# Load modules that are free of runtime relative imports
_models = load_module("models_test", "models.py")
Player = _models.Player

# growth_utils is a new module with pure functions; load it once written
# _growth = load_module("growth_utils", "core/growth_utils.py")


# ------------------------------------------------------------------
# Helpers (mirroring the pure functions that will live in growth_utils)
# ------------------------------------------------------------------


def _roll_growth_points(
    rng: random.Random,
    combat_points: int,
    weights: dict[str, float],
) -> dict[str, int]:
    """Roll combat attribute growth points."""
    attrs = list(weights.keys())
    probs = [weights[a] for a in attrs]
    total = sum(probs)
    cum = [0.0]
    for p in probs:
        cum.append(cum[-1] + p / total)
    cum[-1] = 1.0

    result: dict[str, int] = dict.fromkeys(attrs, 0)
    for _ in range(combat_points):
        r = rng.random()
        for i, a in enumerate(attrs):
            if cum[i] <= r < cum[i + 1]:
                result[a] += 1
                break
    return result


def _apply_pity_bonus(
    base_rate: float,
    streak: int,
    pity_step: float,
    pity_guarantee: int,
) -> float:
    """Apply fail-streak pity bonus after base rate + pill cap.

    Returns the final success rate capped at 1.0.
    """
    if streak >= pity_guarantee:
        return 1.0
    bonus = streak * pity_step
    return min(base_rate + bonus, 1.0)


# ------------------------------------------------------------------
# Tests: growth roll
# ------------------------------------------------------------------


class TestGrowthRoll:
    def test_hp_not_in_combat_pool(self):
        """HP must never be rolled as a combat attribute."""
        weights = {"damage": 0.6, "agility": 0.25, "speed": 0.15}
        rng = random.Random(42)
        result = _roll_growth_points(rng, 5, weights)
        assert "hp" not in result
        assert sum(result.values()) == 5

    def test_weights_produce_expected_distribution(self):
        """Large sample should approximate configured weights."""
        weights = {"damage": 0.6, "agility": 0.25, "speed": 0.15}
        rng = random.Random(0)
        total = {"damage": 0, "agility": 0, "speed": 0}
        trials = 10_000
        for _ in range(trials):
            pts = _roll_growth_points(rng, 5, weights)
            for k, v in pts.items():
                total[k] += v
        grand = sum(total.values())
        ratios = {k: v / grand for k, v in total.items()}
        assert ratios["damage"] == pytest.approx(0.6, abs=0.02)
        assert ratios["agility"] == pytest.approx(0.25, abs=0.02)
        assert ratios["speed"] == pytest.approx(0.15, abs=0.02)

    def test_deterministic_with_same_seed(self):
        """Same seed must produce identical results."""
        weights = {"damage": 0.6, "agility": 0.25, "speed": 0.15}
        r1 = _roll_growth_points(random.Random(123), 5, weights)
        r2 = _roll_growth_points(random.Random(123), 5, weights)
        assert r1 == r2


# ------------------------------------------------------------------
# Tests: pity bonus
# ------------------------------------------------------------------


class TestPityBonus:
    def test_zero_streak_no_bonus(self):
        assert _apply_pity_bonus(0.5, 0, 0.05, 19) == 0.5

    def test_streak_adds_bonus(self):
        assert _apply_pity_bonus(0.5, 3, 0.05, 19) == pytest.approx(0.65)

    def test_guarantee_triggers_100_percent(self):
        assert _apply_pity_bonus(0.05, 19, 0.05, 19) == 1.0
        assert _apply_pity_bonus(0.05, 25, 0.05, 19) == 1.0

    def test_rate_capped_at_1(self):
        assert _apply_pity_bonus(0.9, 5, 0.05, 19) == 1.0

    def test_high_base_rate_with_low_streak(self):
        assert _apply_pity_bonus(0.95, 1, 0.05, 19) == 1.0


# ------------------------------------------------------------------
# Tests: Player model
# ------------------------------------------------------------------


class TestPlayerModel:
    def test_breakthrough_fail_streak_default(self):
        p = Player(user_id="test")
        assert p.breakthrough_fail_streak == 0

    def test_breakthrough_fail_streak_round_trip(self):
        p = Player(user_id="test")
        p.breakthrough_fail_streak = 5
        assert p.breakthrough_fail_streak == 5


# ------------------------------------------------------------------
# Tests: game_config keys
# ------------------------------------------------------------------


class TestGameConfigKeys:
    def test_skill_system_has_expected_keys(self):
        with open("config/game_config.json", encoding="utf-8") as f:
            cfg = json.load(f)
        ss = cfg["skill_system"]
        assert "random_growth_step" in ss
        # New keys added by this change
        assert "growth_weights" in ss
        assert "hp_growth_step" in ss
        assert "breakthrough_pity_step" in ss
        assert "breakthrough_pity_guarantee" in ss

    def test_growth_weights_sum_to_one(self):
        with open("config/game_config.json", encoding="utf-8") as f:
            cfg = json.load(f)
        weights = cfg["skill_system"]["growth_weights"]
        assert set(weights.keys()) == {"damage", "agility", "speed"}
        assert sum(weights.values()) == pytest.approx(1.0, abs=0.001)

    def test_hp_growth_step_positive(self):
        with open("config/game_config.json", encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg["skill_system"]["hp_growth_step"] > 0

    def test_pity_guarantee_reasonable(self):
        with open("config/game_config.json", encoding="utf-8") as f:
            cfg = json.load(f)
        ss = cfg["skill_system"]
        assert 0 < ss["breakthrough_pity_step"] <= 0.1
        assert ss["breakthrough_pity_guarantee"] >= 5


# ------------------------------------------------------------------
# Tests: migration v27
# ------------------------------------------------------------------


class TestMigrationV27:
    def test_migration_script_exists(self):
        import ast

        with open("data/migration.py", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        decorators = [
            node.decorator_list[0].args[0].value  # type: ignore[arg-type]
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.decorator_list
            and isinstance(node.decorator_list[0], ast.Call)
            and isinstance(node.decorator_list[0].args[0], ast.Constant)
        ]
        assert 27 in decorators, "Migration v27 must be registered"

    def test_latest_version_bumped(self):
        with open("data/migration.py", encoding="utf-8") as f:
            source = f.read()
        assert "LATEST_DB_VERSION = 31" in source

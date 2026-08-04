"""Tests for the formula-driven breakthrough system."""

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_package_module

_config_mod = load_package_module(
    "config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager"
)
ConfigManager = _config_mod.ConfigManager

_models_mod = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models")
Player = _models_mod.Player

_bh_mod = load_package_module(
    "handlers/breakthrough_handler.py",
    "astrbot_plugin_monixiuxian2_2.handlers.breakthrough_handler",
)
BreakthroughHandler = _bh_mod.BreakthroughHandler

_bm_mod = load_package_module(
    "core/breakthrough_manager.py",
    "astrbot_plugin_monixiuxian2_2.core.breakthrough_manager",
)
BreakthroughManager = _bm_mod.BreakthroughManager

PLUGIN_ROOT = _config_mod.Path(__file__).resolve().parent.parent


@pytest.fixture
def config_manager():
    """Real ConfigManager loaded from the plugin config directory."""
    return ConfigManager(PLUGIN_ROOT)


@pytest.fixture
def base_config():
    """Minimal config with the updated death probability range."""
    return {"VALUES": {"BREAKTHROUGH_DEATH_PROBABILITY": [0.005, 0.03]}}


@pytest.fixture
def db_mock():
    """Minimal async database mock."""
    db = MagicMock()
    db.update_player = AsyncMock()
    return db


@pytest.fixture
def breakthrough_manager(db_mock, config_manager, base_config):
    """BreakthroughManager with real config and mocked dependencies."""
    return BreakthroughManager(
        db_mock,
        config_manager,
        base_config,
        skill_manager=None,
        storage_ring_manager=MagicMock(),
        pill_manager=MagicMock(),
    )


class FakeEvent:
    """Minimal event stand-in for handler tests."""

    def __init__(self, sender_name="Test"):
        self._sender_name = sender_name

    def get_sender_name(self):
        return self._sender_name

    def plain_result(self, text):
        return type("Result", (), {"text": text})()


@pytest.mark.asyncio
async def test_breakthrough_info_panel_level_one(config_manager):
    """Panel shows current and next level names in 1-based semantics."""
    player = Player(
        user_id="u1",
        user_name="Test",
        level_index=1,
        cultivation_type="灵修",
        experience=config_manager.get_exp_needed(1),
    )
    handler = BreakthroughHandler(
        MagicMock(), config_manager, {"VALUES": {}}, skill_manager=None
    )
    handler.pill_manager = MagicMock()
    handler.pill_manager.update_temporary_effects = AsyncMock()
    handler.pill_manager.get_breakthrough_modifiers.return_value = {
        "temp_bonus": 0.0,
        "permanent_death_multiplier": 1.0,
        "has_temp_effects": False,
    }

    event = FakeEvent()
    coro = handler.handle_breakthrough_info.__wrapped__(handler, player, event)
    results = [result async for result in coro]

    assert len(results) == 1
    text = results[0].text
    assert "练气一阶" in text
    assert "练气二阶" in text
    assert str(config_manager.get_exp_needed(1)) in text
    assert "基础成功率：100.0%" in text


@pytest.mark.asyncio
async def test_breakthrough_info_max_level(config_manager):
    """A level 99 player sees the highest-level prompt instead of a target."""
    player = Player(
        user_id="u1",
        level_index=99,
        cultivation_type="灵修",
        experience=10**12,
    )
    handler = BreakthroughHandler(
        MagicMock(), config_manager, {"VALUES": {}}, skill_manager=None
    )
    handler.pill_manager = MagicMock()
    handler.pill_manager.update_temporary_effects = AsyncMock()
    handler.pill_manager.get_breakthrough_modifiers.return_value = {
        "temp_bonus": 0.0,
        "permanent_death_multiplier": 1.0,
        "has_temp_effects": False,
    }

    event = FakeEvent()
    results = [
        result
        async for result in handler.handle_breakthrough_info.__wrapped__(
            handler, player, event
        )
    ]

    assert len(results) == 1
    assert "最高境界" in results[0].text


def test_check_breakthrough_requirements_max_level(breakthrough_manager):
    """Level 99 players cannot attempt another breakthrough."""
    player = Player(user_id="u1", level_index=99, cultivation_type="灵修")
    can, msg = breakthrough_manager.check_breakthrough_requirements(player)
    assert not can
    assert "最高境界" in msg


@pytest.mark.asyncio
async def test_breakthrough_failure_penalty_uses_current_level_exp(
    breakthrough_manager, config_manager, monkeypatch
):
    """Failure penalty is E(L) * failure_penalty_rate, not total EXP percent."""
    player = Player(
        user_id="u1",
        level_index=10,
        cultivation_type="灵修",
        experience=10**7,
        hp=100,
        damage=10,
        agility=5,
        speed=5,
        armor_value=0,
    )
    required = config_manager.get_exp_needed(10)
    penalty = int(required * config_manager.get_failure_penalty_rate())

    # Force failure (random >= success rate) and avoid death.
    monkeypatch.setattr(random, "random", MagicMock(side_effect=[0.9, 0.9]))
    monkeypatch.setattr(random, "uniform", lambda _a, _b: 0.01)

    success, msg, died = await breakthrough_manager.execute_breakthrough(player)
    assert not success
    assert not died
    assert player.experience == 10**7 - penalty
    assert str(penalty) in msg


class TestLevelUpRatePermanentBonus:
    """level_up_rate participates in breakthrough success rate (spec: level-progression)."""

    def test_zero_level_up_rate_unchanged(self, breakthrough_manager, config_manager):
        """level_up_rate=0 (current fleet-wide state) keeps the old behavior exactly."""
        player = Player(
            user_id="u1", level_index=41, cultivation_type="灵修", level_up_rate=0
        )
        base = config_manager.get_success_rate(42, "灵修")

        rate, info = breakthrough_manager.calculate_breakthrough_success_rate(player)

        assert rate == pytest.approx(base)
        assert "永久加成" not in info

    def test_positive_level_up_rate_added_to_base(
        self, breakthrough_manager, config_manager
    ):
        """level_up_rate=5 adds +5% to the base rate and shows an info line."""
        player = Player(
            user_id="u1", level_index=41, cultivation_type="灵修", level_up_rate=5
        )
        base = config_manager.get_success_rate(42, "灵修")

        rate, info = breakthrough_manager.calculate_breakthrough_success_rate(player)

        assert rate == pytest.approx(base + 0.05)
        assert "永久加成：+5.0%" in info

    def test_permanent_bonus_subject_to_pill_cap(
        self, breakthrough_manager, config_manager
    ):
        """Permanent bonus merges into the pre-cap sum, so the pill max rate still clamps."""
        player = Player(
            user_id="u1", level_index=41, cultivation_type="灵修", level_up_rate=5
        )

        rate, info = breakthrough_manager.calculate_breakthrough_success_rate(
            player, pill_name="化神丹"
        )

        # base 0.50 + 0.05 permanent + 0.77 pill = 1.32 -> capped by 化神丹 max 0.95
        assert rate == pytest.approx(0.95)
        assert "永久加成：+5.0%" in info

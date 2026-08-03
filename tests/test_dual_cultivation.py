"""Tests for the fixed dual-cultivation reward formula."""

from unittest.mock import MagicMock

import pytest

from tests.helpers import load_package_module


_models_mod = load_package_module(
    "models.py", "astrbot_plugin_monixiuxian2_2.models"
)
Player = _models_mod.Player

_dual_mod = load_package_module(
    "managers/dual_cultivation_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.dual_cultivation_manager",
)
DualCultivationManager = _dual_mod.DualCultivationManager


@pytest.fixture
def fake_db():
    """Minimal database mock for the manager constructor."""
    return MagicMock()


@pytest.fixture
def fake_config():
    """AstrBot-style config with base EXP per minute."""
    return {"VALUES": {"BASE_EXP_PER_MINUTE": 100}}


@pytest.fixture
def fake_config_manager():
    """ConfigManager mock exposing the dual-cultivation game config."""
    cm = MagicMock()
    cm.game_config = {
        "dual_cultivation": {
            "k_hours": 2,
            "realm_factor": "linear",
        }
    }
    return cm


@pytest.fixture
def manager(fake_db, fake_config, fake_config_manager):
    """DualCultivationManager using default linear realm factor."""
    return DualCultivationManager(fake_db, fake_config, fake_config_manager)


@pytest.fixture
def player():
    """A level-1 player with a default Wuxing spiritual root (speed 1.0)."""
    return Player(user_id="u1", user_name="A", level_index=1, spiritual_root="金灵根")


def test_calculate_exp_gain_linear_level_one(manager, player):
    """Level 1 (t=1) with default root speed 1.0 yields 2h of closed-cultivation EXP."""
    gain = manager._calculate_exp_gain(player)
    expected = 2 * 100 * 60 * 1.0 * 1
    assert gain == expected


def test_calculate_exp_gain_power15(manager, player, fake_config_manager):
    """Level 11 (t=2) with power1.5 uses t^1.5 as the realm factor."""
    player.level_index = 11
    fake_config_manager.game_config["dual_cultivation"]["realm_factor"] = "power1.5"
    gain = manager._calculate_exp_gain(player)
    expected = int(2 * 100 * 60 * 1.0 * (2 ** 1.5))
    assert gain == expected


def test_calculate_exp_gain_power2(manager, player, fake_config_manager):
    """Level 50 (t=5) with power2 uses t^2 as the realm factor."""
    player.level_index = 50
    fake_config_manager.game_config["dual_cultivation"]["realm_factor"] = "power2"
    gain = manager._calculate_exp_gain(player)
    expected = int(2 * 100 * 60 * 1.0 * (5 * 5))
    assert gain == expected


def test_calculate_exp_gain_unknown_factor_fallback(
    manager, player, fake_config_manager
):
    """An unknown realm_factor falls back to linear."""
    fake_config_manager.game_config["dual_cultivation"]["realm_factor"] = "unknown"
    gain = manager._calculate_exp_gain(player)
    expected = 2 * 100 * 60 * 1.0 * 1
    assert gain == expected


def test_help_text_includes_k_hours_and_formula(manager):
    """The help text mentions the fixed K hours and multiplier formula."""
    text = manager.get_help_text()
    assert "K=2" in text
    assert "境界系数" in text
    assert "灵根倍率" in text
    assert "冷却时间" in text

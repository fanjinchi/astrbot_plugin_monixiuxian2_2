"""Regression tests for pill manager new-attribute migration."""

import pytest
from unittest.mock import AsyncMock

from tests.helpers import load_package_module

_config_mod = load_package_module("config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager")
ConfigManager = _config_mod.ConfigManager

_pill_mod = load_package_module("core/pill_manager.py", "astrbot_plugin_monixiuxian2_2.core.pill_manager")
PillManager = _pill_mod.PillManager
_Player = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models").Player

PLUGIN_ROOT = _config_mod.Path(__file__).resolve().parent.parent


@pytest.fixture
def config_manager():
    return ConfigManager(PLUGIN_ROOT)


@pytest.fixture
def pill_manager(config_manager):
    db = AsyncMock()
    return PillManager(db, config_manager)


def test_ensure_non_negative_attributes_handles_new_attrs(pill_manager):
    """_ensure_non_negative_attributes must only touch existing Player fields."""
    player = _Player(user_id="u1", damage=10, agility=5, speed=5, hp=100, armor_value=5)
    player.hp = -10
    pill_manager._ensure_non_negative_attributes(player)
    assert player.hp == 0


def test_pill_attribute_effects_map_to_new_keys(pill_manager):
    """Legacy physical/magic multipliers are folded into the four main attributes."""
    player = _Player(user_id="u1")
    player.set_active_pill_effects([
        {
            "pill_name": "test",
            "expiry_time": 9999999999,
            "physical_damage_multiplier": 0.2,
            "magic_damage_multiplier": 0.1,
            "physical_defense_multiplier": 0.15,
            "magic_defense_multiplier": 0.05,
        }
    ])
    multipliers = pill_manager.calculate_pill_attribute_effects(player)
    assert multipliers["damage"] == 1.3  # 1.0 + 0.2 + 0.1
    assert multipliers["armor_value"] == 1.2  # 1.0 + 0.15 + 0.05
    assert "physical_damage" not in multipliers
    assert "physical_defense" not in multipliers


def test_pill_multipliers_apply_to_total_attributes():
    """get_total_attributes must read the new pill multiplier keys."""
    player = _Player(
        user_id="u1", damage=100, agility=50, speed=50, hp=100, armor_value=50
    )
    equipped = []
    pill_multipliers = {
        "damage": 1.5,
        "agility": 1.0,
        "speed": 1.0,
        "hp": 1.2,
        "armor_value": 1.1,
    }
    total = player.get_total_attributes(equipped, pill_multipliers)
    assert total["damage"] == 150
    assert total["hp"] == 120
    assert total["armor_value"] == 55


@pytest.mark.asyncio
async def test_use_instant_pill_maps_restore_to_hp(pill_manager, config_manager):
    """Legacy spiritual_qi/blood_qi restore keys must map to hp in new framework."""
    player = _Player(user_id="u1", hp=50)
    player.set_pills_inventory({"test_restore": 1})
    pill_data = {"spiritual_qi_restore": 30}
    ok, msg = await pill_manager._use_instant_pill(player, "test_restore", pill_data)
    assert ok
    assert player.hp == 80


@pytest.mark.asyncio
async def test_handle_resurrection_uses_new_attrs(pill_manager):
    """Resurrection must halve the four main attributes and restore hp."""
    player = _Player(
        user_id="u1",
        has_resurrection_pill=True,
        lifespan=100,
        experience=200,
        damage=100,
        agility=50,
        speed=50,
        hp=200,
        armor_value=30,
    )
    ok = await pill_manager.handle_resurrection(player)
    assert ok
    assert not player.has_resurrection_pill
    assert player.damage == 50
    assert player.agility == 25
    assert player.speed == 25
    assert player.hp == 100
    assert player.armor_value == 15

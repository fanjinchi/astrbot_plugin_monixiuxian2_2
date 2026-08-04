"""Regression tests for equipment manager Item construction."""

import pytest

from tests.helpers import load_package_module

_config_mod = load_package_module("config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager")
ConfigManager = _config_mod.ConfigManager

_equipment_mod = load_package_module("core/equipment_manager.py", "astrbot_plugin_monixiuxian2_2.core.equipment_manager")
EquipmentManager = _equipment_mod.EquipmentManager

PLUGIN_ROOT = _config_mod.Path(__file__).resolve().parent.parent


@pytest.fixture
def config_manager():
    return ConfigManager(PLUGIN_ROOT)


@pytest.fixture
def equipment_manager(config_manager):
    return EquipmentManager(None, config_manager, None)


def test_parse_weapon_from_real_config(config_manager, equipment_manager):
    """parse_item_from_name must build a valid Item from weapons.json."""
    item = equipment_manager.parse_item_from_name(
        "青铜剑", config_manager.items_data, config_manager.weapons_data
    )
    assert item is not None
    assert item.item_type == "weapon"
    # Exact baked values from weapons.json (v3.7.1 legacy-field migration)
    assert item.damage == 15
    assert item.armor_value == 3
    assert item.base_damage == 9
    assert item.weapon_coefficient_k == pytest.approx(0.5)


def test_legacy_only_config_parses_to_zero(equipment_manager):
    """Legacy five-dim keys are ignored: a config carrying only them yields 0.

    Guards against the removed fallback (damage = max(damage, physical + magic))
    silently coming back.
    """
    legacy_weapon = {
        "id": "legacy_test_sword",
        "name": "测试遗留剑",
        "type": "weapon",
        "rank": "凡品",
        "physical_damage": 10,
        "magic_damage": 5,
        "physical_defense": 3,
        "magic_defense": 2,
        "mental_power": 8,
    }
    item = equipment_manager.parse_item_from_name(
        "测试遗留剑", {}, {"测试遗留剑": legacy_weapon}
    )
    assert item is not None
    assert item.damage == 0
    assert item.armor_value == 0


def test_parse_armor_from_real_config(config_manager, equipment_manager):
    """parse_item_from_name must build a valid Item from legacy items.json armor."""
    item = equipment_manager.parse_item_from_name(
        "玄铁甲", config_manager.items_data, config_manager.weapons_data
    )
    assert item is not None
    assert item.item_type == "armor"
    assert item.armor_value > 0


def test_parse_legacy_weapon_from_items_json(config_manager, equipment_manager):
    """Legacy 法器/武器 entries in items.json must parse without TypeError."""
    item = equipment_manager.parse_item_from_name(
        "青锋剑", config_manager.items_data, config_manager.weapons_data
    )
    assert item is not None
    assert item.item_type == "weapon"
    assert item.damage > 0


def test_parse_legacy_armor_from_items_json(config_manager, equipment_manager):
    """Legacy 法器/防具 entries in items.json must parse without TypeError."""
    item = equipment_manager.parse_item_from_name(
        "月华袍", config_manager.items_data, config_manager.weapons_data
    )
    assert item is not None
    assert item.item_type == "armor"
    assert item.armor_value > 0


def test_parse_heart_method_from_config(config_manager, equipment_manager):
    """Heart methods must resolve to main_technique items."""
    item = equipment_manager.parse_item_from_name(
        "长春功",
        config_manager.items_data,
        config_manager.weapons_data,
        config_manager.heart_methods_data,
    )
    assert item is not None
    assert item.item_type == "main_technique"
    assert item.exp_multiplier >= 0

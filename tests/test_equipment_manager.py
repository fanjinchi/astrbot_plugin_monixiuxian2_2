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
    assert item.weapon_coefficient_k != 1.0 or item.base_damage != 0


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

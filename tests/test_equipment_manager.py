"""Regression tests for equipment manager Item construction."""

import json

import pytest

from tests.helpers import load_package_module

_config_mod = load_package_module(
    "config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager"
)
ConfigManager = _config_mod.ConfigManager

_equipment_mod = load_package_module(
    "core/equipment_manager.py", "astrbot_plugin_monixiuxian2_2.core.equipment_manager"
)
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
        "青铜剑",
        config_manager.items_data,
        config_manager.weapons_data,
        config_manager.heart_methods_data,
    )
    assert item is not None
    assert item.item_type == "weapon"
    # Exact baked values from weapons.json (benchmark-piece rework:
    # attribute entries zeroed, armor follows the def/(def+K) budget)
    assert item.damage == 0
    assert item.armor_value == 15
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
        "测试遗留剑", {}, {"测试遗留剑": legacy_weapon}, {}
    )
    assert item is not None
    assert item.damage == 0
    assert item.armor_value == 0


def test_parse_armor_from_real_config(config_manager, equipment_manager):
    """parse_item_from_name must build a valid Item from items.json armor."""
    item = equipment_manager.parse_item_from_name(
        "铁叶甲",
        config_manager.items_data,
        config_manager.weapons_data,
        config_manager.heart_methods_data,
    )
    assert item is not None
    assert item.item_type == "armor"
    assert item.armor_value > 0


def test_parse_legacy_faqi_weapon_uses_equip_effects(equipment_manager):
    """Legacy 法器/武器 shape (equip_effects, no damage key) must map max() into damage."""
    legacy_faqi = {
        "type": "法器",
        "subtype": "武器",
        "rank": "凡品",
        "equip_effects": {"attack": 11},
    }
    item = equipment_manager.parse_item_from_name(
        "测试遗留法器", {"测试遗留法器": legacy_faqi}, {}, {}
    )
    assert item is not None
    assert item.item_type == "weapon"
    assert item.damage == 11


def test_parse_legacy_armor_from_items_json(config_manager, equipment_manager):
    """items.json 法器/防具条目须正确解析，含 bonus_hp 入库的 hp 直读键。"""
    item = equipment_manager.parse_item_from_name(
        "粗布法袍",
        config_manager.items_data,
        config_manager.weapons_data,
        config_manager.heart_methods_data,
    )
    assert item is not None
    assert item.item_type == "armor"
    assert item.armor_value > 0
    # 法袍族的品级阶梯在 bonus_hp（入库为 hp 键，armor-content-design）
    assert item.hp > 0


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


# --- 双链合并守卫（bd: astrbot_plugin_monixiuxian2_2-hnz）---

_CONFLICT_NAME = "冲突测试刃"


def test_source_priority_items_over_weapons_over_heart_methods(equipment_manager):
    """同名条目按 items.json > weapons.json > heart_methods.json 顺序命中。

    三源回退是战斗链与装备链合并后的唯一解析口径，优先级被悄悄改掉会
    让同名条目解析到不同配置（旧战斗链与装备链各持一份副本时正是隐患）。
    """
    items = {_CONFLICT_NAME: {"id": "from_items", "type": "weapon", "damage": 11}}
    weapons = {_CONFLICT_NAME: {"id": "from_weapons", "type": "weapon", "damage": 22}}
    heart_methods = {
        _CONFLICT_NAME: {"id": "from_heart", "passive_bonus": {"hp_percent": 0.5}}
    }

    parse = _equipment_mod.parse_item_from_name
    assert parse(_CONFLICT_NAME, items, weapons, heart_methods).item_id == "from_items"
    assert parse(_CONFLICT_NAME, {}, weapons, heart_methods).item_id == "from_weapons"
    assert parse(_CONFLICT_NAME, {}, {}, heart_methods).item_id == "from_heart"
    # 心法无 type 字段，靠 passive_bonus/skill_pool 归一到 main_technique
    assert parse(_CONFLICT_NAME, {}, {}, heart_methods).item_type == "main_technique"
    # 三源都没有该名字 → 不构造 Item（空槽位与未知名字同样被跳过）
    assert parse(_CONFLICT_NAME, {}, {}, {}) is None
    # EquipmentManager 方法必须仍是同一入口（旧调用方兼容）
    assert (
        equipment_manager.parse_item_from_name(
            _CONFLICT_NAME, items, weapons, heart_methods
        ).item_id
        == "from_items"
    )


def test_main_technique_bonus_reaches_panel_attributes(
    config_manager, equipment_manager
):
    """主修心法加成必须进 total_attrs（面板/排行榜丢失心法的回归钉子）。

    修复前 get_equipped_items 不传 heart_methods_data，main_technique 解析为
    None 被静默跳过，面板与排行榜看不到长春功 passive_bonus.hp_percent=0.1。
    """
    player = _equipment_mod.Player(
        user_id="u1",
        weapon="青铜剑",
        armor="铁叶甲",
        main_technique="长春功",
    )

    equipped = equipment_manager.get_equipped_items(
        player,
        config_manager.items_data,
        config_manager.weapons_data,
        config_manager.heart_methods_data,
    )
    assert [item.item_type for item in equipped] == [
        "weapon",
        "armor",
        "main_technique",
    ]

    total = player.get_total_attributes(equipped, pill_multipliers=None)
    without_heart = player.get_total_attributes(equipped[:2], pill_multipliers=None)
    # 长春功 route_multiplier 灵修=1.0 → 生效值即 0.1
    assert total["max_hp"] == int(without_heart["max_hp"] * 1.1)
    # 空的心法表 → 主修心法槽位解析不出，只剩武器/防具（三张表必传，契约不再允许漏传）
    skipped = equipment_manager.get_equipped_items(
        player, config_manager.items_data, config_manager.weapons_data, {}
    )
    assert [item.item_type for item in skipped] == ["weapon", "armor"]


# --- 内容不变式：物品/武器表不得遮蔽心法（bd hnz 的真实事故：legacy「龟息功」）---


def test_heart_methods_are_not_shadowed_by_other_tables(config_manager):
    """items/weapons 表出现与心法同名的条目时，该心法在三源回退里永远解析不到。"""
    heart_names = set(config_manager.heart_methods_data)
    shadowed = (
        set(config_manager.items_data) | set(config_manager.weapons_data)
    ) & heart_names
    assert not shadowed, f"以下心法名被同名物品/武器遮蔽：{sorted(shadowed)}"


def test_heart_method_gui_xi_gong_resolves_as_main_technique(
    config_manager, equipment_manager
):
    """龟息功必须解析成主修心法（legacy items.json 同名条目已删除）。

    修复前 items.json 有一条同名 legacy「功法」条目，三源回退里 items 永远先命中：
    玩家抽到龟息功后装备入口只会回「未找到功法：龟息功」，体修路线校验走不到。
    """
    item = equipment_manager.parse_item_from_name(
        "龟息功",
        config_manager.items_data,
        config_manager.weapons_data,
        config_manager.heart_methods_data,
    )
    assert item is not None
    assert item.item_type == "main_technique"
    assert json.loads(item.passive_bonus) == {"hp_percent": 0.09}
    assert item.exp_multiplier == pytest.approx(0.06)

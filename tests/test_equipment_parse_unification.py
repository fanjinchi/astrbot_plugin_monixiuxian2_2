"""Cross-chain guards for the equipment parse merge (bd: astrbot_plugin_monixiuxian2_2-hnz).

Combat (CombatEngine.build_fighter_from_player) and the panel/ranking/health chain
(EquipmentManager.get_equipped_items) must resolve equipment through the same builder
and reach identical totals.
"""

import pytest

from tests.helpers import PLUGIN_ROOT, load_package_module

_config_mod = load_package_module(
    "config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager"
)
ConfigManager = _config_mod.ConfigManager

_equipment_mod = load_package_module(
    "core/equipment_manager.py", "astrbot_plugin_monixiuxian2_2.core.equipment_manager"
)
EquipmentManager = _equipment_mod.EquipmentManager

Player = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models").Player

_combat_mod = load_package_module(
    "managers/combat_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.combat_manager",
)
CombatEngine = _combat_mod.CombatEngine


@pytest.mark.asyncio
async def test_combat_fighter_matches_equipment_chain_totals():
    """同一玩家经战斗链与面板/排行榜入口必须得到同一套属性。

    Guards the merged parse chain: while CombatEngine kept its own copy of the
    config mapping, the two chains could silently diverge (the heart-method slot
    already had: the panel chain dropped it, combat kept it). 这里走面板/排行榜/
    health 的真入口 `EquipmentManager.get_equipped_items`，而不是模块级 builder
    ——模块级直调时，入口退回旧签名（丢心法表）测试也不会红。
    """
    config_manager = ConfigManager(PLUGIN_ROOT)
    player = Player(
        user_id="u1",
        level_index=5,
        weapon="青铜剑",
        armor="铁叶甲",
        main_technique="长春功",
    )

    engine = CombatEngine(config_manager=config_manager)
    fighter = await engine.build_fighter_from_player(player)

    equipment_manager = EquipmentManager(None, config_manager, None)
    equipped = equipment_manager.get_equipped_items(
        player,
        config_manager.items_data,
        config_manager.weapons_data,
        config_manager.heart_methods_data,
    )
    attrs = player.get_total_attributes(equipped, pill_multipliers=None)

    assert [item.item_type for item in equipped] == [
        "weapon",
        "armor",
        "main_technique",
    ]
    assert fighter.max_hp == attrs["max_hp"]
    assert fighter.damage == attrs["damage"]
    assert fighter.agility == attrs["agility"]
    assert fighter.speed == attrs["speed"]
    assert fighter.armor_value == attrs["armor_value"]
    # 心法确实参与其中，否则上面的相等只说明"两条链都没加成"
    assert attrs["max_hp"] > player.base_hp

"""Regression tests for pill manager new-attribute migration."""

from unittest.mock import AsyncMock

import pytest

from tests.helpers import load_package_module

_config_mod = load_package_module(
    "config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager"
)
ConfigManager = _config_mod.ConfigManager

_pill_mod = load_package_module(
    "core/pill_manager.py", "astrbot_plugin_monixiuxian2_2.core.pill_manager"
)
PillManager = _pill_mod.PillManager
_Player = load_package_module(
    "models.py", "astrbot_plugin_monixiuxian2_2.models"
).Player

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
    player = _Player(
        user_id="u1", damage=10, agility=5, speed=5, base_hp=100, armor_value=5
    )
    player.base_hp = -10
    pill_manager._ensure_non_negative_attributes(player)
    assert player.base_hp == 0


def test_pill_attribute_effects_map_to_new_keys(pill_manager):
    """Legacy physical/magic multipliers are folded into the four main attributes."""
    player = _Player(user_id="u1")
    player.set_active_pill_effects(
        [
            {
                "pill_name": "test",
                "expiry_time": 9999999999,
                "physical_damage_multiplier": 0.2,
                "magic_damage_multiplier": 0.1,
                "physical_defense_multiplier": 0.15,
                "magic_defense_multiplier": 0.05,
            }
        ]
    )
    multipliers = pill_manager.calculate_pill_attribute_effects(player)
    assert multipliers["damage"] == 1.3  # 1.0 + 0.2 + 0.1
    assert multipliers["armor_value"] == 1.2  # 1.0 + 0.15 + 0.05
    assert "physical_damage" not in multipliers
    assert "physical_defense" not in multipliers


def test_pill_multipliers_apply_to_total_attributes():
    """get_total_attributes must read the new pill multiplier keys."""
    player = _Player(
        user_id="u1", damage=100, agility=50, speed=50, base_hp=100, armor_value=50
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
    assert total["max_hp"] == 120
    assert total["armor_value"] == 55


@pytest.mark.asyncio
async def test_apply_instant_pill_maps_restore_to_hp(pill_manager, config_manager):
    """Legacy spiritual_qi/blood_qi restore keys must map to hp in new framework.

    直接测本体：外层 _use_instant_pill 已加写锁内重读（bd -546），该包装层需要
    真实 DB 行才能跑，映射逻辑本身仍在本体里。
    """
    player = _Player(user_id="u1", base_hp=50, current_hp=50)
    player.set_pills_inventory({"test_restore": 1})
    pill_data = {"spiritual_qi_restore": 30}
    ok, msg = await pill_manager._apply_instant_pill(player, "test_restore", pill_data)
    assert ok
    assert player.current_hp == 80


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
        base_hp=200,
        current_hp=200,
        armor_value=30,
    )
    ok = await pill_manager.handle_resurrection(player)
    assert ok
    assert not player.has_resurrection_pill
    assert player.damage == 50
    assert player.agility == 25
    assert player.speed == 25
    assert player.base_hp == 100
    assert player.current_hp == 100  # 当前层被夹回新上限
    assert player.armor_value == 15


# --- bd astrbot_plugin_monixiuxian2_2-hbz：静默吞丹防线 -------------------------


@pytest.mark.asyncio
async def test_use_pill_refuses_breakthrough_pill(pill_manager):
    """「服用丹药 筑基丹」必须被拒且不扣丹、不落库（bd hbz）。

    破境丹只有 breakthrough_bonus 键，旧行为是落到 _apply_instant_pill 的空转分支：
    扣掉一颗、回「服用成功」，修为/属性/灵石全不变——筑基丹 5000 灵石，混元丹 100 亿。
    """
    player = _Player(user_id="u1", level_index=9)
    player.set_pills_inventory({"筑基丹": 1})

    ok, msg = await pill_manager.use_pill(player, "筑基丹")

    assert not ok
    assert "破境丹" in msg and "突破 筑基丹" in msg
    assert player.get_pills_inventory() == {"筑基丹": 1}
    pill_manager.db.update_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_every_breakthrough_pill_is_refused_by_use_pill(
    pill_manager, config_manager
):
    """pills.json 全表堵死：没有任何一颗能经「服用丹药」被静默吃掉（bd hbz）。

    这张表 26 条全部 subtype=breakthrough 且无任何 instant 效果键，是本次事故的
    完整受害面。表规模变化时该用例会红，提示重新确认新条目的用法。
    """
    pills = list(config_manager.pills_data.values())
    assert len(pills) == 26, "pills.json 条目数变化，请重新确认本用例的前提"
    level_index = max(p.get("required_level_index", 0) for p in pills)
    assert level_index > 0

    for pill in pills:
        player = _Player(user_id="u1", level_index=level_index)
        player.set_pills_inventory({pill["name"]: 1})
        ok, msg = await pill_manager.use_pill(player, pill["name"])
        assert not ok, pill["name"]
        assert "破境丹" in msg, pill["name"]
        assert player.get_pills_inventory() == {pill["name"]: 1}, pill["name"]
        # 逐条钉「不落库」（README 更新日志按此声明）：拒绝发生在任何写库之前。
        pill_manager.db.update_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_instant_pill_without_any_effect_key_is_refused(pill_manager):
    """通用守卫：一个可套用的效果键都没有时拒绝，不扣丹、不落库（bd hbz 防复发）。

    这条挡的是「新增丹药子类漏配效果键」的将来时——不该再靠人记得加分支。
    """
    player = _Player(user_id="u1")
    player.set_pills_inventory({"无名丹": 1})

    ok, msg = await pill_manager._apply_instant_pill(
        player, "无名丹", {"name": "无名丹"}
    )

    assert not ok
    assert "未消耗" in msg
    assert player.get_pills_inventory() == {"无名丹": 1}
    pill_manager.db.update_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_debuff_shield_pill_refused_when_shield_active(pill_manager):
    """定魂丹已有护盾时拒绝且不扣丹（bd hbz 同类，30000 灵石）。

    旧行为打印「定魂护盾已存在，无需重复使用」却照样消耗一颗并回「服用成功」。
    """
    player = _Player(user_id="u1", has_debuff_shield=True)
    player.set_pills_inventory({"定魂丹": 1})

    ok, msg = await pill_manager._apply_instant_pill(
        player, "定魂丹", {"name": "定魂丹", "blocks_next_debuff": True}
    )

    assert not ok
    assert player.has_debuff_shield
    assert player.get_pills_inventory() == {"定魂丹": 1}
    pill_manager.db.update_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_debuff_shield_pill_still_applies_without_shield(pill_manager):
    """无护盾时照常获得护盾并消耗：守住这次改动没有把正常路径一起堵掉。"""
    player = _Player(user_id="u1")
    player.set_pills_inventory({"定魂丹": 1})

    ok, _msg = await pill_manager._apply_instant_pill(
        player, "定魂丹", {"name": "定魂丹", "blocks_next_debuff": True}
    )

    assert ok
    assert player.has_debuff_shield
    assert player.get_pills_inventory() == {}

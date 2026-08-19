"""Tests for sect growth: buildings, elixir room, mainbuff, promotion, treasury."""

import pytest

from tests.helpers import load_module, load_package_module

_migration_mod = load_module("migration_sect_growth_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager

_data_mod = load_package_module(
    "data/data_manager.py",
    "astrbot_plugin_monixiuxian2_2.data.data_manager",
)
DataBase = _data_mod.DataBase

Player = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models").Player
Sect = load_package_module(
    "models_extended.py", "astrbot_plugin_monixiuxian2_2.models_extended"
).Sect

_sect_mod = load_package_module(
    "managers/sect_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.sect_manager",
)
SectManager = _sect_mod.SectManager

_skill_mod = load_package_module(
    "core/skill_manager.py",
    "astrbot_plugin_monixiuxian2_2.core.skill_manager",
)
SkillManager = _skill_mod.SkillManager

_shop_mod = load_package_module(
    "core/shop_manager.py",
    "astrbot_plugin_monixiuxian2_2.core.shop_manager",
)
ShopManager = _shop_mod.ShopManager


def _positions():
    """Position config mirroring sect_config.json (promotion/benefits)."""
    return {
        "0": {
            "name": "宗主",
            "permission": 10,
            "promotion": None,
            "benefits": {"daily_stones": 2000, "shop_discount": 0.8, "unlocks": []},
        },
        "1": {
            "name": "长老",
            "permission": 8,
            "promotion": {"contribution": 30000, "level_index": 9},
            "benefits": {"daily_stones": 800, "shop_discount": 0.85, "unlocks": []},
        },
        "2": {
            "name": "亲传弟子",
            "permission": 5,
            "promotion": {"contribution": 8000, "level_index": 6},
            "benefits": {
                "daily_stones": 300,
                "shop_discount": 0.9,
                "unlocks": ["wpn_qy_001"],
            },
        },
        "3": {
            "name": "内门弟子",
            "permission": 2,
            "promotion": {"contribution": 2000, "level_index": 4},
            "benefits": {
                "daily_stones": 100,
                "shop_discount": 0.95,
                "unlocks": ["heart_qy_001"],
            },
        },
        "4": {
            "name": "外门弟子",
            "permission": 1,
            "promotion": {"contribution": 500, "level_index": 2},
            "benefits": {"daily_stones": 0, "shop_discount": 1.0, "unlocks": []},
        },
    }


def _buildings():
    return {
        "fairyland": {
            "max_level": 5,
            "exp_bonus_per_level": 0.02,
            "upgrade_cost": [200, 400, 800, 1600, 3200],
        },
        "elixir_room": {
            "max_level": 5,
            "unlock_pills_per_level": ["炼气丹", "聚灵丹", "凝气丹"],
            "upgrade_cost": [200, 400, 800, 1600, 3200],
        },
    }


class FakeConfigManager:
    """Minimal ConfigManager stub for sect growth tests."""

    def __init__(self, construction_tasks=None):
        self.sect_config = {
            "create_cost": 10000,
            "create_level_required": 3,
            "positions": _positions(),
            "scale_ratio": 10,
            "buildings": _buildings(),
        }
        self.sect_factions = {
            "factions": [
                {
                    "id": "qingyun",
                    "name": "青云门",
                    "join_level_range": [0, 5],
                    "mainbuff": ["qy_001"],
                    "heart_methods": ["heart_qy_001"],
                    "treasures": [
                        {"type": "weapon", "id": "wpn_qy_001", "min_position": 2}
                    ],
                    "buildings": _buildings(),
                },
            ]
        }
        if construction_tasks is None:
            construction_tasks = [
                {
                    "id": "build_002",
                    "name": "输财助宗",
                    "type": "donate_stones",
                    "cost": {"stones": 500},
                    "reward": {"contribution": 40},
                    "cooldown": 3600,
                }
            ]
        self.sect_tasks = {"construction_tasks": construction_tasks}
        self.game_config = {"skill_system": {}}
        self.weapons_data = {
            "青云镇山剑": {
                "id": "wpn_qy_001",
                "name": "青云镇山剑",
                "sect_id": "qingyun",
                "treasure": True,
                "min_position": 2,
            }
        }
        self.items_data = {}
        self.pills_data = {}
        self.utility_pills_data = {}
        self.exp_pills_data = {
            "炼气丹": {"name": "炼气丹"},
            "聚灵丹": {"name": "聚灵丹"},
            "凝气丹": {"name": "凝气丹"},
        }
        self.heart_methods_data = {
            "青云心典": {
                "id": "heart_qy_001",
                "name": "青云心典",
                "sect_id": "qingyun",
                "sect_bound": True,
            }
        }
        self.skills_data = {
            "青云剑诀": {
                "id": "qy_001",
                "name": "青云剑诀",
                "trigger_skill": {
                    "name": "青云一剑",
                    "trigger_condition": "attack",
                    "trigger_rate": 0.18,
                    "effect_type": "damage_bonus",
                    "effect_value": 0.3,
                },
                "route_multiplier": {"灵修": 1.0, "体修": 1.0},
                "sect_bound": True,
            }
        }

    def get_level_name(self, level_index: int, cultivation_type: str = "灵修") -> str:
        return f"境界{level_index}"


async def _make_db(config=None) -> DataBase:
    db = DataBase(":memory:")
    await db.connect()
    await MigrationManager(db.conn, config or FakeConfigManager()).migrate()
    return db


async def _make_player(
    db: DataBase, user_id: str, level_index: int = 2, gold: int = 0
) -> Player:
    player = Player(
        user_id=user_id,
        user_name=f"道友{user_id}",
        spiritual_root="天灵根",
        level_index=level_index,
        gold=gold,
    )
    await db.create_player(player)
    return player


async def _join_qingyun(db, mgr, user_id: str, level_index: int = 2, gold: int = 0):
    await _make_player(db, user_id, level_index=level_index, gold=gold)
    success, msg = await mgr.join_sect(user_id, "青云门")
    assert success, msg
    return await db.ext.get_sect_by_faction_id("qingyun")


# ===== 4.1 洞天加成 =====


@pytest.mark.asyncio
async def test_fairyland_exp_bonus_scales_with_level():
    """Fairyland bonus equals exp_bonus_per_level * level for sect members."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    sect = await _join_qingyun(db, mgr, "u1")

    player = await db.get_player_by_id("u1")
    assert await mgr.get_fairyland_exp_bonus(player) == (0.0, 0)

    sect.sect_fairyland = 2
    await db.ext.update_sect(sect)
    bonus, level = await mgr.get_fairyland_exp_bonus(player)
    assert bonus == pytest.approx(0.04)
    assert level == 2

    # 无宗门玩家无加成
    await _make_player(db, "u2")
    player2 = await db.get_player_by_id("u2")
    assert await mgr.get_fairyland_exp_bonus(player2) == (0.0, 0)
    await db.close()


# ===== 4.2 丹房 =====


@pytest.mark.asyncio
async def test_elixir_room_claim_and_daily_reset():
    """Elixir room grants the level-unlocked pill once per day."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    sect = await _join_qingyun(db, mgr, "u1")

    # 丹房未建成
    success, msg = await mgr.claim_elixir("u1")
    assert not success
    assert "尚未建成" in msg

    sect.elixir_room_level = 1
    await db.ext.update_sect(sect)

    success, msg = await mgr.claim_elixir("u1")
    assert success, msg
    assert "炼气丹" in msg
    player = await db.get_player_by_id("u1")
    assert player.sect_elixir_get == 1
    assert player.get_pills_inventory().get("炼气丹") == 1

    # 当日重复领取被拒
    success, msg = await mgr.claim_elixir("u1")
    assert not success
    assert "今日已" in msg

    # 日重置后可再次领取（升级到 2 级后领当前档丹药）
    await db.ext.reset_sect_elixir_get()
    sect = await db.ext.get_sect_by_id(sect.sect_id)
    sect.elixir_room_level = 2
    await db.ext.update_sect(sect)
    success, msg = await mgr.claim_elixir("u1")
    assert success, msg
    player = await db.get_player_by_id("u1")
    assert player.get_pills_inventory().get("聚灵丹") == 1
    await db.close()


# ===== 4.4 建筑升级 =====


@pytest.mark.asyncio
async def test_upgrade_building_consumes_materials():
    """Upgrading the fairyland consumes configured materials (system sect: any member)."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    sect = await _join_qingyun(db, mgr, "u1")

    sect.sect_materials = 1000
    await db.ext.update_sect(sect)

    success, msg = await mgr.upgrade_building("u1", "洞天")
    assert success, msg
    sect = await db.ext.get_sect_by_id(sect.sect_id)
    assert sect.sect_fairyland == 1
    assert sect.sect_materials == 800  # 1000 - 升级消耗 200

    # 资材不足拒绝
    sect.sect_materials = 100
    await db.ext.update_sect(sect)
    success, msg = await mgr.upgrade_building("u1", "洞天")
    assert not success
    assert "资材不足" in msg
    await db.close()


@pytest.mark.asyncio
async def test_upgrade_building_player_sect_requires_elder_permission():
    """Player-built sects require elder-and-above permission to upgrade."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await _make_player(db, "owner", level_index=5, gold=20000)
    success, _ = await mgr.create_sect("owner", "太一宗")
    assert success
    sect = await db.ext.get_sect_by_name("太一宗")
    sect.sect_materials = 10000
    await db.ext.update_sect(sect)

    await _make_player(db, "outer", level_index=2)
    await mgr.join_sect("outer", "太一宗")  # 外门弟子

    # 外门弟子（玩家宗门）无权升级
    success, msg = await mgr.upgrade_building("outer", "丹房")
    assert not success
    assert "宗主和长老" in msg

    # 宗主可升级（玩家宗门读全局默认 buildings）
    success, msg = await mgr.upgrade_building("owner", "丹房")
    assert success, msg
    sect = await db.ext.get_sect_by_id(sect.sect_id)
    assert sect.elixir_room_level == 1
    assert sect.sect_materials == 9800
    await db.close()


# ===== 4.4 建设任务池 =====


@pytest.mark.asyncio
async def test_perform_sect_task_settles_by_task_config():
    """Construction tasks settle cost/reward and use the task cooldown."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    sect = await _join_qingyun(db, mgr, "u1", gold=1000)

    success, msg = await mgr.perform_sect_task("u1")
    assert success, msg
    assert "输财助宗" in msg

    player = await db.get_player_by_id("u1")
    assert player.gold == 500
    assert player.sect_contribution == 40
    assert player.sect_task == 1  # increment_sect_task_count 已接线

    sect = await db.ext.get_sect_by_id(sect.sect_id)
    assert sect.sect_used_stone == 500
    assert sect.sect_scale == 100 + 500 * 10  # scale_ratio=10

    # 冷却中再次执行被拒
    success, msg = await mgr.perform_sect_task("u1")
    assert not success
    assert "冷却中" in msg
    await db.close()


@pytest.mark.asyncio
async def test_perform_sect_task_materials_task_grants_sect_materials():
    """donate_materials tasks add materials to the sect, costing the player nothing."""
    config = FakeConfigManager(
        construction_tasks=[
            {
                "id": "build_001",
                "name": "修缮山门",
                "type": "donate_materials",
                "cost": {"materials": 50},
                "reward": {"contribution": 30},
                "cooldown": 3600,
            }
        ]
    )
    db = await _make_db(config)
    mgr = SectManager(db, config)
    await mgr.ensure_system_sects()
    sect = await _join_qingyun(db, mgr, "u1")

    success, msg = await mgr.perform_sect_task("u1")
    assert success, msg
    player = await db.get_player_by_id("u1")
    assert player.gold == 0  # 资材任务不消耗玩家货币
    assert player.sect_contribution == 30
    sect = await db.ext.get_sect_by_id(sect.sect_id)
    assert sect.sect_materials == 100 + 50
    await db.close()


@pytest.mark.asyncio
async def test_perform_sect_task_insufficient_stones_rejected():
    """Stone-donation tasks are rejected when the player cannot afford them."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _join_qingyun(db, mgr, "u1", gold=100)

    success, msg = await mgr.perform_sect_task("u1")
    assert not success
    assert "灵石不足" in msg
    await db.close()


# ===== 4.3 镇派功法 =====


@pytest.mark.asyncio
async def test_ensure_system_sects_seeds_mainbuff_from_faction():
    """Seeding initializes the mainbuff slot from the faction config."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    sect = await db.ext.get_sect_by_faction_id("qingyun")
    assert sect.get_mainbuff_list() == ["qy_001"]
    await db.close()


@pytest.mark.asyncio
async def test_manage_sect_buff_player_sect_owner_only():
    """Only the owner of a player-built sect can enshrine a valid skill."""
    db = await _make_db()
    config = FakeConfigManager()
    mgr = SectManager(db, config)
    await mgr.ensure_system_sects()

    # 默认宗门不可更改
    await _join_qingyun(db, mgr, "u1")
    success, msg = await mgr.manage_sect_buff("u1", "qy_001")
    assert not success
    assert "不可更改" in msg

    # 玩家宗门：非宗主拒绝
    await _make_player(db, "owner", level_index=5, gold=20000)
    await mgr.create_sect("owner", "太一宗")
    await _make_player(db, "member", level_index=2)
    await mgr.join_sect("member", "太一宗")
    success, msg = await mgr.manage_sect_buff("member", "qy_001")
    assert not success
    assert "宗主" in msg

    # 不存在的功法拒绝
    success, msg = await mgr.manage_sect_buff("owner", "不存在的功法")
    assert not success
    assert "未找到功法" in msg

    # 宗主按 ID 或名称镶嵌成功
    success, msg = await mgr.manage_sect_buff("owner", "青云剑诀")
    assert success, msg
    sect = await db.ext.get_sect_by_name("太一宗")
    assert sect.get_mainbuff_list() == ["qy_001"]
    await db.close()


@pytest.mark.asyncio
async def test_sect_mainbuff_trigger_injected_into_battle_loadout():
    """Sect mainbuff trigger skills enter the member's battle trigger pool."""
    db = await _make_db()
    config = FakeConfigManager()
    mgr = SectManager(db, config)
    await mgr.ensure_system_sects()
    await _join_qingyun(db, mgr, "u1")

    skill_mgr = SkillManager(config, db)
    player = await db.get_player_by_id("u1")
    loadout = await skill_mgr.get_battle_loadout(player)
    names = [t.get("name") for t in loadout["trigger_skills"]]
    assert "青云一剑" in names
    trigger = next(t for t in loadout["trigger_skills"] if t.get("name") == "青云一剑")
    assert trigger.get("trigger_timing") == "on_attack"
    assert trigger.get("star_level") == 1

    # 无宗门玩家不注入
    await _make_player(db, "u2")
    player2 = await db.get_player_by_id("u2")
    loadout2 = await skill_mgr.get_battle_loadout(player2)
    assert loadout2["trigger_skills"] == []
    await db.close()


# ===== 6.1 职阶晋升 =====


@pytest.mark.asyncio
async def test_promote_position_dual_gates():
    """Promotion requires both contribution and level gates of the target rank."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _join_qingyun(db, mgr, "u1", level_index=2)

    player = await db.get_player_by_id("u1")
    assert player.sect_position == 4

    # 贡献不足（4→3 需 2000 贡献 + 境界4）
    player.sect_contribution = 500
    await db.update_player(player)
    success, msg = await mgr.promote_position("u1")
    assert not success
    assert "贡献不足" in msg
    assert "境界不足" in msg

    # 双门槛达成 → 晋升内门弟子
    player = await db.get_player_by_id("u1")
    player.sect_contribution = 2000
    player.level_index = 4
    await db.update_player(player)
    success, msg = await mgr.promote_position("u1")
    assert success, msg
    assert "内门弟子" in msg
    assert "每日签到俸禄" in msg
    player = await db.get_player_by_id("u1")
    assert player.sect_position == 3
    await db.close()


@pytest.mark.asyncio
async def test_promote_position_no_owner_channel():
    """Position 0 (宗主) has promotion=null, so elders cannot self-promote to it."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    sect = await _join_qingyun(db, mgr, "u1", level_index=2)
    await db.ext.update_player_sect_info("u1", sect.sect_id, 1)

    player = await db.get_player_by_id("u1")
    player.sect_contribution = 999999
    player.level_index = 30
    await db.update_player(player)

    success, msg = await mgr.promote_position("u1")
    assert not success
    assert "不设晋升通道" in msg
    player = await db.get_player_by_id("u1")
    assert player.sect_position == 1
    await db.close()


# ===== 6.2 福利 =====


@pytest.mark.asyncio
async def test_get_position_benefits_reads_config():
    """Benefits lookup returns configured salary/discount/unlocks with defaults."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    benefits = mgr.get_position_benefits(3)
    assert benefits["daily_stones"] == 100
    assert benefits["shop_discount"] == 0.95
    assert benefits["unlocks"] == ["heart_qy_001"]
    assert mgr.get_position_benefits(99)["shop_discount"] == 1.0
    await db.close()


@pytest.mark.asyncio
async def test_sect_shop_discount():
    """Shop discount applies to sect members by position; non-members pay full."""
    config = FakeConfigManager()
    shop_mgr = ShopManager({}, config)

    member = Player(user_id="u1", sect_id=1, sect_position=2)
    assert shop_mgr.get_sect_shop_discount(member) == 0.9

    outer = Player(user_id="u2", sect_id=1, sect_position=4)
    assert shop_mgr.get_sect_shop_discount(outer) == 1.0

    lone = Player(user_id="u3")
    assert shop_mgr.get_sect_shop_discount(lone) == 1.0


@pytest.mark.asyncio
async def test_treasury_view_and_claim():
    """Treasury lists faction items; claims enforce position/unlocks and limits."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    sect = await _join_qingyun(db, mgr, "u1", level_index=2)

    # 外门弟子（4）：心法/宝物均不可领取
    success, msg = await mgr.claim_treasure("u1", "青云心典")
    assert not success
    assert "职阶不足" in msg

    # 内门弟子（3）：unlocks 含 heart_qy_001 → 可领心法
    await db.ext.update_player_sect_info("u1", sect.sect_id, 3)
    success, msg = await mgr.claim_treasure("u1", "青云心典")
    assert success, msg
    player = await db.get_player_by_id("u1")
    assert player.get_storage_ring_items().get("青云心典") == 1
    assert "heart_qy_001" in player.get_sect_treasure_claims()

    # 已习得（持有）不可重复领取
    success, msg = await mgr.claim_treasure("u1", "青云心典")
    assert not success
    assert "已习得" in msg

    # 宝物 min_position=2，内门弟子不可领
    success, msg = await mgr.claim_treasure("u1", "青云镇山剑")
    assert not success

    # 亲传弟子（2）可领宝物；每人限领一次
    await db.ext.update_player_sect_info("u1", sect.sect_id, 2)
    success, msg = await mgr.claim_treasure("u1", "wpn_qy_001")
    assert success, msg
    assert "归还宗门" in msg
    player = await db.get_player_by_id("u1")
    assert player.get_storage_ring_items().get("青云镇山剑") == 1

    success, msg = await mgr.claim_treasure("u1", "青云镇山剑")
    assert not success
    assert "限领一次" in msg

    # 宝库查看包含条目与领取提示
    success, msg = await mgr.get_treasury_info("u1")
    assert success, msg
    assert "青云镇山剑" in msg and "青云心典" in msg
    await db.close()


@pytest.mark.asyncio
async def test_leave_sect_reclaims_equipped_treasure():
    """Treasures equipped in the weapon slot are unequipped and reclaimed on leave."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _join_qingyun(db, mgr, "u1", level_index=2)

    player = await db.get_player_by_id("u1")
    player.weapon = "青云镇山剑"  # 已装备的本宗宝物
    player.set_storage_ring_items({"铁剑": 1})
    await db.update_player(player)

    success, msg = await mgr.leave_sect("u1")
    assert success, msg
    assert "青云镇山剑" in msg

    player = await db.get_player_by_id("u1")
    assert player.weapon == ""
    assert player.get_storage_ring_items() == {"铁剑": 1}
    await db.close()

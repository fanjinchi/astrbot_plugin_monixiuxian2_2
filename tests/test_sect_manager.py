"""Tests for sect system: system sect seeding, join/leave flow, treasure reclaim."""

import pytest

from tests.helpers import load_module, load_package_module

_migration_mod = load_module("migration_sect_test", "data/migration.py")
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

_ring_mod = load_package_module(
    "core/storage_ring_manager.py",
    "astrbot_plugin_monixiuxian2_2.core.storage_ring_manager",
)
StorageRingManager = _ring_mod.StorageRingManager


class FakeConfigManager:
    """Minimal ConfigManager stub for sect tests."""

    def __init__(self, scale_ratio: int = 10):
        self.sect_config = {
            "create_cost": 10000,
            "create_level_required": 3,
            "positions": {
                "0": {"name": "宗主", "permission": 10},
                "1": {"name": "长老", "permission": 8},
                "2": {"name": "亲传弟子", "permission": 5},
                "3": {"name": "内门弟子", "permission": 2},
                "4": {"name": "外门弟子", "permission": 1},
            },
            "scale_ratio": scale_ratio,
        }
        self.sect_factions = {
            "factions": [
                {
                    "id": "qingyun",
                    "name": "青云门",
                    "join_level_range": [0, 5],
                },
                {
                    "id": "huanxi",
                    "name": "合欢宗",
                    "join_level_range": [2, 6],
                },
            ]
        }
        self.weapons_data = {
            "青云镇山剑": {"id": "wpn_qy_001", "sect_id": "qingyun", "treasure": True},
            "铁剑": {"id": "wpn_common_001"},
        }
        self.items_data = {"灵草": {"type": "材料"}}
        self.heart_methods_data = {
            "青云心典": {"id": "heart_qy_001", "sect_id": "qingyun", "sect_bound": True}
        }
        self.skills_data = {"青云剑诀": {"sect_bound": True}}

    def get_level_name(self, level_index: int, cultivation_type: str = "灵修") -> str:
        return f"境界{level_index}"


async def _make_db() -> DataBase:
    db = DataBase(":memory:")
    await db.connect()
    await MigrationManager(db.conn, FakeConfigManager()).migrate()
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


# ===== 3.1 默认宗门播种 =====


@pytest.mark.asyncio
async def test_ensure_system_sects_seeds_and_is_idempotent():
    """Seeding creates configured system sects once; re-runs do not duplicate."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())

    await mgr.ensure_system_sects()
    sects = await db.ext.get_all_sects()
    assert len(sects) == 2
    by_name = {s.sect_name: s for s in sects}
    qy = by_name["青云门"]
    assert qy.is_system == 1
    assert qy.faction_id == "qingyun"
    assert qy.sect_owner == ""
    assert qy.sect_scale == 100
    assert qy.sect_materials == 100

    # 再次播种不产生重复记录
    await mgr.ensure_system_sects()
    assert len(await db.ext.get_all_sects()) == 2
    await db.close()


@pytest.mark.asyncio
async def test_ensure_system_sects_syncs_name_without_touching_operational_data():
    """Re-seeding syncs text fields only; operational data is preserved."""
    db = await _make_db()
    config = FakeConfigManager()
    mgr = SectManager(db, config)

    await mgr.ensure_system_sects()
    sect = await db.ext.get_sect_by_faction_id("qingyun")
    sect.sect_scale = 500
    sect.sect_materials = 888
    await db.ext.update_sect(sect)

    # 配置改名后重新播种：名称同步，建设度/资材不覆盖
    config.sect_factions["factions"][0]["name"] = "青云宗"
    await mgr.ensure_system_sects()

    sect = await db.ext.get_sect_by_faction_id("qingyun")
    assert sect.sect_name == "青云宗"
    assert sect.sect_scale == 500
    assert sect.sect_materials == 888
    assert len(await db.ext.get_all_sects()) == 2
    await db.close()


@pytest.mark.asyncio
async def test_create_sect_rejects_system_sect_name():
    """Player-created sects must not reuse a default sect name."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()

    await _make_player(db, "u1", level_index=5, gold=20000)
    success, msg = await mgr.create_sect("u1", "青云门")
    assert not success
    assert "青云门" in msg

    # 普通名称不受影响
    success, msg = await mgr.create_sect("u1", "太一宗")
    assert success, msg
    await db.close()


# ===== 3.2 加入宗门分流 =====


@pytest.mark.asyncio
async def test_join_system_sect_within_level_range():
    """Players inside join_level_range can join a default sect."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()

    await _make_player(db, "u1", level_index=3)
    success, msg = await mgr.join_sect("u1", "青云门")
    assert success, msg
    assert "拜入" in msg

    player = await db.get_player_by_id("u1")
    sect = await db.ext.get_sect_by_faction_id("qingyun")
    assert player.sect_id == sect.sect_id
    assert player.sect_position == 4  # 最低职阶（外门弟子）
    await db.close()


@pytest.mark.asyncio
async def test_join_system_sect_out_of_level_range_rejected():
    """Players outside join_level_range are rejected with a clear message."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()

    await _make_player(db, "u1", level_index=6)
    success, msg = await mgr.join_sect("u1", "青云门")
    assert not success
    assert "不再招收此境界" in msg

    # 境界低于区间下限同样拒绝
    await _make_player(db, "u2", level_index=1)
    success, msg = await mgr.join_sect("u2", "合欢宗")
    assert not success
    assert "不再招收此境界" in msg
    await db.close()


@pytest.mark.asyncio
async def test_join_player_sect_has_no_level_restriction():
    """Player-created sects keep the existing free-join semantics."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()

    await _make_player(db, "owner", level_index=5, gold=20000)
    success, _ = await mgr.create_sect("owner", "太一宗")
    assert success

    await _make_player(db, "u1", level_index=99)
    success, msg = await mgr.join_sect("u1", "太一宗")
    assert success, msg
    assert "加入了宗门" in msg
    await db.close()


# ===== 3.3 离宗回收钩子 =====


@pytest.mark.asyncio
async def test_leave_sect_reclaims_treasure_and_keeps_personal_items():
    """Leaving a sect reclaims treasures; personal items and bound skills stay."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()

    await _make_player(db, "u1", level_index=2)
    success, _ = await mgr.join_sect("u1", "青云门")
    assert success

    # 持有宗门之宝与个人物品
    player = await db.get_player_by_id("u1")
    player.set_storage_ring_items({"青云镇山剑": 1, "铁剑": 2})
    player.sect_contribution = 100
    await db.update_player(player)

    # 已习得宗门绑定功法
    await db.ext.learn_or_star_up(
        "u1", "qy_001", "test", origin_sect_id="qingyun", sect_bound=True
    )
    # 进行中的师承任务链进度
    player.set_sect_master_progress(
        {"chain_id": "chain_qy_01", "stage_index": 0, "progress": 1}
    )
    await db.update_player(player)

    success, msg = await mgr.leave_sect("u1")
    assert success, msg
    assert "青云镇山剑" in msg
    assert "归还宗门" in msg

    player = await db.get_player_by_id("u1")
    assert player.sect_id == 0
    assert player.sect_contribution == 0
    # 师承任务链进度随离宗清除（bd-c1y：改投他派后不得仍显示原宗门任务链）
    assert player.get_sect_master_progress() == {}
    items = player.get_storage_ring_items()
    assert "青云镇山剑" not in items  # 宝物被回收
    assert items.get("铁剑") == 2  # 个人物品不受影响

    # sect_bound 功法离宗保留可用（不回收不封印）
    assert await db.ext.is_skill_learned("u1", "qy_001")
    skills = await db.ext.get_learned_skills("u1")
    assert skills[0]["sect_bound"] is True
    await db.close()


@pytest.mark.asyncio
async def test_kick_member_reclaims_treasure():
    """Kicking a member also reclaims their sect treasures."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    sect = await db.ext.get_sect_by_faction_id("qingyun")

    await _make_player(db, "leader", level_index=2)
    await _make_player(db, "member", level_index=2)
    await mgr.join_sect("leader", "青云门")
    await mgr.join_sect("member", "青云门")
    # 直接设定职位：leader 为宗主档
    await db.ext.update_player_sect_info("leader", sect.sect_id, 0)

    member = await db.get_player_by_id("member")
    member.set_storage_ring_items({"青云镇山剑": 1})
    member.sect_contribution = 50
    member.set_sect_master_progress(
        {"chain_id": "chain_qy_01", "stage_index": 1, "progress": 2}
    )
    await db.update_player(member)

    success, msg = await mgr.kick_member("leader", "member")
    assert success, msg
    assert "归还宗门" in msg

    member = await db.get_player_by_id("member")
    assert member.sect_id == 0
    assert member.sect_contribution == 0
    assert member.get_storage_ring_items() == {}
    assert member.get_sect_master_progress() == {}  # 被逐同样清除师承进度
    await db.close()


@pytest.mark.asyncio
async def test_kick_permission_rules_follow_config():
    """Kick permission derives from configured permission levels."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await _make_player(db, "owner", level_index=5, gold=20000)
    await mgr.create_sect("owner", "太一宗")
    sect = await db.ext.get_sect_by_name("太一宗")

    for uid in ["elder", "inner", "outer", "core"]:
        await _make_player(db, uid)
        await mgr.join_sect(uid, "太一宗")
    await db.ext.update_player_sect_info("elder", sect.sect_id, 1)
    await db.ext.update_player_sect_info("core", sect.sect_id, 2)
    await db.ext.update_player_sect_info("inner", sect.sect_id, 3)

    # 长老（permission 8）不能踢内门弟子（permission 2，非最低档）
    success, msg = await mgr.kick_member("elder", "inner")
    assert not success
    assert "长老只能踢出外门弟子" in msg

    # 长老可踢外门弟子（最低权限档）
    success, msg = await mgr.kick_member("elder", "outer")
    assert success, msg

    # 亲传弟子（permission 5，低于次高档）无踢人资格
    success, msg = await mgr.kick_member("core", "inner")
    assert not success
    assert "只有宗主和长老" in msg

    # 长老踢宗主：沿用旧版检查顺序，命中长老限制（旧实现同样如此）
    success, msg = await mgr.kick_member("elder", "owner")
    assert not success
    assert "长老只能踢出外门弟子" in msg

    # 最高权限档（宗主）踢长老：允许
    success, msg = await mgr.kick_member("owner", "elder")
    assert success, msg
    await db.close()


@pytest.mark.asyncio
async def test_position_names_come_from_config():
    """Position names and the entry position derive from sect_config.json."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    assert mgr.get_position_name(0) == "宗主"
    assert mgr.get_position_name(4) == "外门弟子"
    assert mgr.get_position_name(99) == "未知"
    assert mgr.get_entry_position() == 4
    await db.close()


# ===== 3.3 储物戒赠予拦截 =====


def test_is_sect_bound_item():
    """Sect-marked items (treasure/sect_bound/sect_id) are detected."""
    ring_mgr = StorageRingManager(None, FakeConfigManager())
    assert ring_mgr.is_sect_bound_item("青云镇山剑")  # treasure
    assert ring_mgr.is_sect_bound_item("青云心典")  # sect_bound 心法
    assert ring_mgr.is_sect_bound_item("青云剑诀")  # sect_bound 功法
    assert not ring_mgr.is_sect_bound_item("铁剑")
    assert not ring_mgr.is_sect_bound_item("灵草")
    assert not ring_mgr.is_sect_bound_item("不存在的物品")


# ===== 3.4 scale_ratio 接线 =====


@pytest.mark.asyncio
async def test_donate_uses_configured_scale_ratio():
    """Donation converts stones to sect scale via configured scale_ratio."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager(scale_ratio=20))
    await mgr.ensure_system_sects()

    await _make_player(db, "u1", level_index=2, gold=1000)
    await mgr.join_sect("u1", "青云门")

    success, msg = await mgr.donate_to_sect("u1", 100)
    assert success, msg

    sect = await db.ext.get_sect_by_faction_id("qingyun")
    assert sect.sect_used_stone == 100
    assert sect.sect_scale == 100 + 100 * 20  # 初始100 + 捐献×scale_ratio
    assert "2000" in msg
    await db.close()


# ===== 3.3 弃道重修回收（第三路径，handler 级） =====


def _patch_synthetic_packages():
    """Expose sibling attrs on synthetic packages so handler relative imports resolve."""
    import sys

    core_pkg = sys.modules.get("astrbot_plugin_monixiuxian2_2.core")
    if core_pkg is not None:
        core_pkg.StorageRingManager = StorageRingManager
        # PlayerHandler 以 __new__ 使用，占位即可（__init__ 不会执行）
        for name in ("CultivationManager", "PillManager", "SkillManager"):
            if not hasattr(core_pkg, name):
                setattr(core_pkg, name, type(name, (), {}))
    data_pkg = sys.modules.get("astrbot_plugin_monixiuxian2_2.data")
    if data_pkg is not None:
        data_pkg.DataBase = DataBase


@pytest.mark.asyncio
async def test_rebirth_reclaims_sect_treasures():
    """Rebirth (弃道重修) reclaims sect treasures before deleting the character."""
    from unittest.mock import MagicMock

    _patch_synthetic_packages()
    _ph_mod = load_package_module(
        "handlers/player_handler.py",
        "astrbot_plugin_monixiuxian2_2.handlers.player_handler",
    )
    PlayerHandler = _ph_mod.PlayerHandler

    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()

    await _make_player(db, "u1", level_index=2)
    success, _ = await mgr.join_sect("u1", "青云门")
    assert success
    player = await db.get_player_by_id("u1")
    player.set_storage_ring_items({"青云镇山剑": 1})
    await db.update_player(player)

    handler = PlayerHandler.__new__(PlayerHandler)
    handler.db = db
    handler.sect_mgr = mgr

    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.get_message_str.return_value = "弃道重修 确认"
    event.plain_result.side_effect = lambda text: text

    outputs = [item async for item in handler.handle_rebirth(event, "确认")]

    assert any("青云镇山剑" in str(o) and "已归还宗门" in str(o) for o in outputs)
    # 角色数据已删除
    assert await db.get_player_by_id("u1") is None
    await db.close()


# ===== 3.3 赠予拦截（handler 级） =====


class _FakePlain:
    """Stand-in for astrbot Plain (conftest stubs astrbot.api.all as MagicMock)."""

    def __init__(self, text: str):
        self.text = text


class _FakeAt:
    """Stand-in for astrbot At so the handler's isinstance checks work."""


def _load_storage_ring_handler():
    """Load StorageRingHandler and rebind At/Plain to test doubles."""
    _patch_synthetic_packages()
    mod = load_package_module(
        "handlers/storage_ring_handler.py",
        "astrbot_plugin_monixiuxian2_2.handlers.storage_ring_handler",
    )
    mod.At = _FakeAt
    mod.Plain = _FakePlain
    return mod.StorageRingHandler


def _make_gift_event(text: str):
    from unittest.mock import MagicMock

    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.get_message_str.return_value = text
    event.message_obj.message = [_FakePlain(text)]
    event.plain_result.side_effect = lambda t: t
    return event


@pytest.mark.asyncio
async def test_gift_rejects_sect_bound_item():
    """Gifting a sect-bound item is rejected before any ring mutation."""
    StorageRingHandler = _load_storage_ring_handler()

    db = await _make_db()
    await _make_player(db, "u1", level_index=2)
    player = await db.get_player_by_id("u1")
    player.set_storage_ring_items({"青云镇山剑": 1})
    await db.update_player(player)

    handler = StorageRingHandler.__new__(StorageRingHandler)
    handler.db = db
    handler.storage_ring_manager = StorageRingManager(None, FakeConfigManager())

    event = _make_gift_event("赠予 123456789 青云镇山剑 1")
    outputs = [item async for item in handler.handle_gift_item(event, "")]

    assert any("乃宗门之物，不可外传" in str(o) for o in outputs)
    # 物品未被取出
    player = await db.get_player_by_id("u1")
    assert player.get_storage_ring_items().get("青云镇山剑") == 1
    await db.close()


@pytest.mark.asyncio
async def test_gift_normal_item_not_blocked_by_sect_check():
    """Normal items pass the sect-bound check (fails later on empty ring instead)."""
    StorageRingHandler = _load_storage_ring_handler()

    db = await _make_db()
    await _make_player(db, "u1", level_index=2)

    handler = StorageRingHandler.__new__(StorageRingHandler)
    handler.db = db
    handler.storage_ring_manager = StorageRingManager(None, FakeConfigManager())

    event = _make_gift_event("赠予 123456789 铁剑 1")
    outputs = [item async for item in handler.handle_gift_item(event, "")]

    assert any("储物戒中没有【铁剑】" in str(o) for o in outputs)
    assert not any("乃宗门之物" in str(o) for o in outputs)
    await db.close()


# ===== 8.3 宗门传承：领取（守护挑战）与离宗回收 =====

_impart_mod = load_package_module(
    "managers/impart_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.impart_manager",
)
ImpartManager = _impart_mod.ImpartManager

_SECT_LEGACY_TIERS = [
    {
        "tier": 1,
        "impart_value_required": 20,
        "rewards": [{"type": "heart_method", "id": "传承心法·吐纳"}],
    },
]


class LegacySectConfig(FakeConfigManager):
    """FakeConfigManager with a sect legacy entry + impart type config."""

    def __init__(self):
        super().__init__()
        self.sect_factions["factions"][0]["legacies"] = [
            {
                "name": "青云门传承",
                "legacy_type": "sect",
                "min_position": 2,
                "description": "青云门镇派传承",
            }
        ]
        self.impart_config = {
            "cultivation_points_every_minutes": 15,
            "types": {
                "common": {
                    "name": "通用传承",
                    "tiers": [dict(t) for t in _SECT_LEGACY_TIERS],
                },
                "sect": {
                    "name": "宗门传承",
                    "tiers": [dict(t) for t in _SECT_LEGACY_TIERS],
                },
            },
        }
        self.heart_methods_data["传承心法·吐纳"] = {
            "id": "heart_impart_001",
            "name": "传承心法·吐纳",
            "passive_bonus": {},
            "skill_pool": [],
            "route": "通用",
        }
        self.level_data = [{"level": i, "level_name": f"L{i}"} for i in range(10)]
        self.body_level_data = self.level_data

    def get_max_level(self, cultivation_type="灵修"):
        return len(self.level_data) - 1


class _StubPveCombat:
    """Stub PVECombatManager returning a fixed guardian-challenge outcome."""

    def __init__(self, won: bool):
        self.won = won
        self.calls = 0

    async def challenge_legacy_guardian(self, player):
        self.calls += 1
        return self.won, ("战胜守护者" if self.won else "败于守护者")


def _make_legacy_mgr(db, config, won=True):
    """SectManager wired with a real ImpartManager and a stub guardian fight."""
    mgr = SectManager(db, config)
    impart = ImpartManager(db, config)
    mgr.impart_mgr = impart
    mgr.pve_combat_mgr = _StubPveCombat(won)
    return mgr, impart


async def _join_as_inner(db, mgr, user_id):
    """Join 青云门 then promote to 亲传弟子 (position 2) to pass the legacy gate."""
    await mgr.join_sect(user_id, "青云门")
    sect = await db.ext.get_sect_by_faction_id("qingyun")
    await db.ext.update_player_sect_info(user_id, sect.sect_id, 2)


@pytest.mark.asyncio
async def test_sect_legacy_claim_success_occupies_quota():
    """Winning the guardian fight creates a sect instance and consumes the quota."""
    db = await _make_db()
    config = LegacySectConfig()
    mgr, _ = _make_legacy_mgr(db, config, won=True)
    await mgr.ensure_system_sects()

    await _make_player(db, "u1", level_index=2)
    await _join_as_inner(db, mgr, "u1")

    success, msg = await mgr.claim_treasure("u1", "青云门传承")
    assert success, msg
    assert "战胜" in msg and "宗门传承" in msg

    # 实例已创建，type=sect 且绑定本宗
    instances = await db.ext.list_legacy_instances_by_owner("u1")
    assert len(instances) == 1
    assert instances[0].legacy_type == "sect"
    sect = await db.ext.get_sect_by_faction_id("qingyun")
    assert instances[0].sect_id == sect.sect_id

    # 名额已占：再次领取被拒绝
    success, msg = await mgr.claim_treasure("u1", "青云门传承")
    assert not success and ("限领一次" in msg or "无需重复领取" in msg)
    await db.close()


@pytest.mark.asyncio
async def test_sect_legacy_claim_failure_keeps_quota():
    """Losing the guardian fight does not consume the claim quota (retryable)."""
    db = await _make_db()
    config = LegacySectConfig()
    mgr, _ = _make_legacy_mgr(db, config, won=False)
    await mgr.ensure_system_sects()

    await _make_player(db, "u1", level_index=2)
    await _join_as_inner(db, mgr, "u1")

    success, msg = await mgr.claim_treasure("u1", "青云门传承")
    assert not success
    assert "不占用领取名额" in msg
    # 守护战仅触发一次（失败即结算，不重复挑战）
    assert mgr.pve_combat_mgr.calls == 1
    # 未创建实例、未占名额
    assert await db.ext.list_legacy_instances_by_owner("u1") == []
    player = await db.get_player_by_id("u1")
    assert "青云门传承" not in player.get_sect_treasure_claims()

    # 可重试：换成必胜守护者后领取成功
    mgr.pve_combat_mgr = _StubPveCombat(True)
    success, msg = await mgr.claim_treasure("u1", "青云门传承")
    assert success, msg
    assert mgr.pve_combat_mgr.calls == 1
    assert len(await db.ext.list_legacy_instances_by_owner("u1")) == 1
    await db.close()


@pytest.mark.asyncio
async def test_sect_legacy_transaction_rejects_after_leaving_sect():
    """退宗窗口：守护战斗期间玩家已退宗/转会，事务内归属复核必须拒绝
    （战前快照守卫对战中退宗无能为力，靠 fresh_player 重查兜底）。"""
    db = await _make_db()
    config = LegacySectConfig()
    mgr, _ = _make_legacy_mgr(db, config, won=True)
    await mgr.ensure_system_sects()

    await _make_player(db, "u1", level_index=2)
    await _join_as_inner(db, mgr, "u1")
    sect = await db.ext.get_sect_by_faction_id("qingyun")
    player = await db.get_player_by_id("u1")
    entry = {
        "kind": "legacy",
        "id": "青云门传承",
        "name": "青云门传承",
        "min_position": 2,
    }

    # 模拟战斗中退宗：DB 中 sect_id 已清空，内存 player（战前快照）仍是旧宗门
    await db.ext.update_player_sect_info("u1", 0, 0)
    success, msg = await mgr._claim_sect_legacy(player, sect, entry)
    assert not success
    assert "你当前已不在该宗门" in msg
    # 未创建实例、未占名额
    assert await db.ext.list_legacy_instances_by_owner("u1") == []
    await db.close()


@pytest.mark.asyncio
async def test_sect_legacy_transaction_blocks_duplicate_sect_instance():
    """并发双开不同 entry：战前预检基于旧快照，事务内必须重查已持有的
    sect 实例并拒绝，防止绕过「已持有本宗传承不可重复领取」。"""
    db = await _make_db()
    config = LegacySectConfig()
    mgr, _ = _make_legacy_mgr(db, config, won=True)
    await mgr.ensure_system_sects()

    await _make_player(db, "u1", level_index=2)
    await _join_as_inner(db, mgr, "u1")
    # 先正常领取一条（战前预检通过后完成）
    success, msg = await mgr.claim_treasure("u1", "青云门传承")
    assert success, msg

    sect = await db.ext.get_sect_by_faction_id("qingyun")
    player = await db.get_player_by_id("u1")
    # 直接调事务内函数模拟并发第二开（绕过战前预检：另一 entry id）
    entry = {
        "kind": "legacy",
        "id": "青云门传承-第二门",
        "name": "青云门传承-第二门",
        "min_position": 2,
    }
    success, msg = await mgr._claim_sect_legacy(player, sect, entry)
    assert not success
    assert "已持有本宗传承" in msg
    # 仍只有一条实例，未重复创建
    assert len(await db.ext.list_legacy_instances_by_owner("u1")) == 1
    await db.close()


@pytest.mark.asyncio
async def test_leave_sect_reclaims_sect_legacy():
    """Leaving the sect removes the player's sect-bound legacy instances."""
    db = await _make_db()
    config = LegacySectConfig()
    mgr, _ = _make_legacy_mgr(db, config, won=True)
    await mgr.ensure_system_sects()

    await _make_player(db, "u1", level_index=2)
    await _join_as_inner(db, mgr, "u1")
    success, _ = await mgr.claim_treasure("u1", "青云门传承")
    assert success
    assert len(await db.ext.list_legacy_instances_by_owner("u1")) == 1

    success, msg = await mgr.leave_sect("u1")
    assert success, msg
    # 离宗后宗门传承实例被回收
    assert await db.ext.list_legacy_instances_by_owner("u1") == []
    await db.close()


# ===== 8.3 legacy_chance=0 不触发 =====


@pytest.mark.asyncio
async def test_adventure_zero_legacy_chance_never_triggers():
    """legacy_chance=0 → the adventure settlement never rolls a legacy."""
    _adv_mod = load_package_module(
        "managers/adventure_manager.py",
        "astrbot_plugin_monixiuxian2_2.managers.adventure_manager",
    )

    class _ProbeImpart:
        called = False

        async def create_legacy(self, *a, **k):
            _ProbeImpart.called = True

    adv = _adv_mod.AdventureManager.__new__(_adv_mod.AdventureManager)
    adv.impart_mgr = _ProbeImpart()
    adv.legacy_chance = 0.0
    adv.legacy_type = "adventure"

    # 直接调机缘判定：chance=0 时 random()>=0 恒真，返回空串且不创建实例
    player = Player(user_id="u1", user_name="t", spiritual_root="天灵根")
    msg = await adv._maybe_trigger_legacy(player)
    assert msg == ""
    assert not _ProbeImpart.called

"""Tests for managers/impart_manager.py (legacy instances, single-activation, PK snatch)."""

import pytest

from tests.helpers import load_module, load_package_module

# Load modules under a synthetic package so relative imports resolve.
load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models")
load_package_module(
    "models_extended.py", "astrbot_plugin_monixiuxian2_2.models_extended"
)
_data_mod = load_package_module(
    "data/data_manager.py",
    "astrbot_plugin_monixiuxian2_2.data.data_manager",
)
DataBase = _data_mod.DataBase
DatabaseExtended = load_package_module(
    "data/database_extended.py",
    "astrbot_plugin_monixiuxian2_2.data.database_extended",
).DatabaseExtended
Player = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models").Player
load_package_module("config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager")
_impart_mod = load_package_module(
    "managers/impart_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.impart_manager",
)
ImpartManager = _impart_mod.ImpartManager
IMPART_PK_COOLDOWN_SECONDS = _impart_mod.IMPART_PK_COOLDOWN_SECONDS
IMPART_SNATCH_PROTECTION_SECONDS = _impart_mod.IMPART_SNATCH_PROTECTION_SECONDS

_migration_mod = load_module("migration_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager
LATEST_DB_VERSION = _migration_mod.LATEST_DB_VERSION

_TIERS = [
    {
        "tier": 1,
        "impart_value_required": 20,
        "rewards": [{"type": "heart_method", "id": "传承心法·吐纳"}],
    },
    {
        "tier": 2,
        "impart_value_required": 40,
        "rewards": [{"type": "heart_method", "id": "传承心法·归元"}],
    },
    {
        "tier": 3,
        "impart_value_required": 60,
        "rewards": [{"type": "technique", "id": "impart_skill_001"}],
    },
    {
        "tier": 4,
        "impart_value_required": 80,
        "rewards": [{"type": "technique", "id": "impart_skill_002"}],
    },
    {
        "tier": 5,
        "impart_value_required": 100,
        "rewards": [{"type": "level_up", "amount": 1}],
    },
]


class DummyConfigManager:
    """Minimal config manager stub for impart tests (types 分表)."""

    def __init__(self):
        self.game_config = {
            "skill_system": {
                "max_star": 3,
                "star_compensation_base": 1000,
                "star_compensation_ratio": 0.5,
            }
        }
        self.level_data = [{"level": i, "level_name": f"Level{i}"} for i in range(10)]
        self.body_level_data = self.level_data
        self.heart_methods_data = {
            "传承心法·吐纳": {
                "id": "heart_impart_001",
                "name": "传承心法·吐纳",
                "passive_bonus": {"hp_percent": 0.05},
                "skill_pool": [],
                "route": "通用",
            },
            "传承心法·归元": {
                "id": "heart_impart_002",
                "name": "传承心法·归元",
                "passive_bonus": {"damage_percent": 0.05},
                "skill_pool": [],
                "route": "通用",
            },
        }
        self.skills_data = {
            "传承功法·护体": {
                "id": "impart_skill_001",
                "name": "传承功法·护体",
                "trigger_skill": {
                    "name": "传承护体",
                    "trigger_condition": "defend",
                    "trigger_rate": 0.15,
                    "effect_type": "damage_reduction",
                    "effect_value": 0.3,
                },
                "ultimate": None,
                "route_multiplier": {"灵修": 1.0, "体修": 1.0},
                "learn_coefficient": 1.0,
            },
            "传承功法·破敌": {
                "id": "impart_skill_002",
                "name": "传承功法·破敌",
                "trigger_skill": {
                    "name": "传承破敌",
                    "trigger_condition": "attack",
                    "trigger_rate": 0.15,
                    "effect_type": "damage_bonus",
                    "effect_value": 1.3,
                },
                "ultimate": None,
                "route_multiplier": {"灵修": 1.0, "体修": 1.0},
                "learn_coefficient": 1.0,
            },
        }
        self.impart_config = {
            "cultivation_points_every_minutes": 15,
            "guardian": {"enemy_group": "legacy_guardian"},
            "types": {
                "common": {"name": "通用传承", "tiers": [dict(t) for t in _TIERS]},
                "sect": {"name": "宗门传承", "tiers": [dict(t) for t in _TIERS]},
                "adventure": {"name": "历练传承", "tiers": [dict(t) for t in _TIERS]},
                "rift": {"name": "秘境传承", "tiers": [dict(t) for t in _TIERS]},
            },
        }

    def get_max_level(self, cultivation_type="灵修"):
        """Return highest valid level index for the dummy route."""
        return len(self.level_data) - 1


async def _setup_db():
    """Create a migrated in-memory database and attach DatabaseExtended."""
    db = DataBase(":memory:")
    await db.connect()
    await MigrationManager(db.conn, DummyConfigManager()).migrate()
    db.ext = DatabaseExtended(db.conn)
    return db


async def _create_player(db, user_id="u1"):
    """Create a basic player for reward tests."""
    player = Player(user_id=user_id, user_name="Tester", spiritual_root="天灵根")
    await db.create_player(player)
    return player


# ===== 实例创建 / 多条持有 / 激活制 =====


@pytest.mark.asyncio
async def test_create_and_activate_single_active():
    """Multiple instances can be held; only one is active at a time."""
    db = await _setup_db()
    try:
        await _create_player(db)
        mgr = ImpartManager(db, DummyConfigManager())

        inst1 = await mgr.create_legacy("u1", "common")
        inst2 = await mgr.create_legacy("u1", "adventure")
        assert inst1 and inst2 and inst1.id != inst2.id

        instances = await mgr.list_owner_legacies("u1")
        assert len(instances) == 2
        # 最新创建（activate=True）成为激活实例
        active = await mgr.get_active_legacy("u1")
        assert active is not None and active.id == inst2.id

        # 手动激活第一条，另一条自动去激
        ok, msg = await mgr.activate_legacy("u1", inst1.id)
        assert ok
        active = await mgr.get_active_legacy("u1")
        assert active.id == inst1.id
        assert (await db.ext.get_legacy_instance_by_id(inst2.id)).is_active == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_activate_rejects_foreign_or_missing_instance():
    """activate_legacy fails for instances not owned by the player."""
    db = await _setup_db()
    try:
        await _create_player(db, "u1")
        await _create_player(db, "u2")
        mgr = ImpartManager(db, DummyConfigManager())
        other = await mgr.create_legacy("u2", "common")

        ok, msg = await mgr.activate_legacy("u1", other.id)
        assert not ok and "未找到" in msg
        ok, msg = await mgr.activate_legacy("u1", 99999)
        assert not ok
    finally:
        await db.close()


# ===== 修炼累积粒度 =====


@pytest.mark.asyncio
async def test_cultivation_accumulation_active_only_and_granularity():
    """Only the active instance accumulates; sub-15min deltas are dropped by caller."""
    db = await _setup_db()
    try:
        player = await _create_player(db)
        mgr = ImpartManager(db, DummyConfigManager())
        inst_a = await mgr.create_legacy("u1", "common")  # active
        inst_b = await mgr.create_legacy("u1", "adventure")  # becomes active
        await mgr.activate_legacy("u1", inst_a.id)  # re-activate common

        # 出关结算：45 分钟 → 3 点；只加给激活的 common
        msg = await mgr.add_active_impart_value(player, 45 // 15)
        assert msg is not None and "+3" in msg
        assert (await db.ext.get_legacy_instance_by_id(inst_a.id)).impart_value == 3
        assert (await db.ext.get_legacy_instance_by_id(inst_b.id)).impart_value == 0

        # 不足 15 分钟 → delta=0 → 无累积
        msg = await mgr.add_active_impart_value(player, 14 // 15)
        assert msg is None
        assert (await db.ext.get_legacy_instance_by_id(inst_a.id)).impart_value == 3

        # 无激活实例 → None
        await db.ext.clear_active_legacy_instance("u1", inst_a.id)
        assert await mgr.add_active_impart_value(player, 5) is None
    finally:
        await db.close()


# ===== tier 自动发放 / 奖励 id 存在性 =====


@pytest.mark.asyncio
async def test_tier_rewards_auto_grant_and_ids_resolve():
    """Crossing thresholds auto-grants rewards whose ids exist in config."""
    db = await _setup_db()
    try:
        player = await _create_player(db)
        mgr = ImpartManager(db, DummyConfigManager())
        await mgr.create_legacy("u1", "common")  # active

        # 一次加到 60，跨过 1/2/3 阶
        msg = await mgr.add_active_impart_value(player, 60)
        assert msg is not None and "解锁奖励" in msg

        updated = await db.get_player_by_id("u1")
        items = updated.get_storage_ring_items()
        assert items.get("传承心法·吐纳") == 1
        assert items.get("传承心法·归元") == 1
        skills = await db.ext.get_learned_skills("u1")
        assert [s["skill_id"] for s in skills] == ["impart_skill_001"]
        assert skills[0]["source"] == "impart"

        # 奖励 id 存在性校验：dummy 配置里的 id 都能在 heart_methods/skills 中找到
        assert mgr._find_heart_method("传承心法·吐纳") is not None
        assert mgr._find_heart_method("传承心法·归元") is not None
        assert mgr._find_skill_by_id("impart_skill_001") is not None
        assert mgr._find_skill_by_id("impart_skill_002") is not None
        assert mgr._find_skill_by_id("nonexistent_skill") is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reward_not_repeated_for_claimed_tier():
    """A claimed tier is not granted again on further accumulation."""
    db = await _setup_db()
    try:
        player = await _create_player(db)
        mgr = ImpartManager(db, DummyConfigManager())
        await mgr.create_legacy("u1", "common")
        await mgr.add_active_impart_value(player, 20)
        await mgr.add_active_impart_value(player, 20)
        await mgr.add_active_impart_value(player, 20)

        updated = await db.get_player_by_id("u1")
        assert updated.get_storage_ring_items().get("传承心法·吐纳") == 1
        assert updated.get_storage_ring_items().get("传承心法·归元") == 1
        skills = await db.ext.get_learned_skills("u1")
        assert len(skills) == 1 and skills[0]["skill_id"] == "impart_skill_001"
    finally:
        await db.close()


# ===== PK 夺取 transfer 清零 =====


@pytest.mark.asyncio
async def test_transfer_legacy_resets_and_reassigns():
    """Snatch transfer moves ownership, resets value/claimed, clears activation."""
    db = await _setup_db()
    try:
        await _create_player(db, "defender")
        await _create_player(db, "attacker")
        mgr = ImpartManager(db, DummyConfigManager())

        inst = await mgr.create_legacy("defender", "adventure")  # active
        inst.impart_value = 60
        inst.set_claimed_tiers([1, 2, 3])
        await db.ext.update_legacy_instance(inst)

        moved = await mgr.transfer_legacy(inst.id, "attacker")
        assert moved is not None
        assert moved.owner_id == "attacker"
        assert moved.impart_value == 0
        assert moved.get_claimed_tiers() == []
        assert moved.is_active == 0
        # 原主人不再持有，新主人激活态不受影响（需手动激活）
        assert await mgr.get_active_legacy("defender") is None
        assert await mgr.get_active_legacy("attacker") is None
        assert len(await mgr.list_owner_legacies("defender")) == 0
        assert len(await mgr.list_owner_legacies("attacker")) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_select_snatch_target_skips_sect_and_filters_type():
    """Snatch target excludes sect legacies; optional type filter applies."""
    db = await _setup_db()
    try:
        await _create_player(db, "defender")
        mgr = ImpartManager(db, DummyConfigManager())
        sect = await mgr.create_legacy("defender", "sect", sect_id=1, activate=False)
        adv = await mgr.create_legacy("defender", "adventure", activate=False)
        common = await mgr.create_legacy("defender", "common", activate=False)

        # 默认取最新的非 sect 实例（common 最新）
        target = await mgr.select_snatch_target("defender")
        assert target is not None and target.id == common.id
        # 类型过滤
        target = await mgr.select_snatch_target("defender", "adventure")
        assert target is not None and target.id == adv.id
        # 只剩 sect 时无可夺目标
        await db.ext.delete_legacy_instance(common.id)
        await db.ext.delete_legacy_instance(adv.id)
        assert await mgr.select_snatch_target("defender") is None
        assert sect.legacy_type == "sect"
    finally:
        await db.close()


# ===== 冷却边界 / 被夺保护 =====


@pytest.mark.asyncio
async def test_challenge_cooldown_boundary_and_per_target():
    """5-day cooldown blocks re-challenge of same target; other targets unaffected."""
    db = await _setup_db()
    try:
        mgr = ImpartManager(db, DummyConfigManager())
        now = 1_000_000_000

        await db.ext.upsert_impart_pk_cooldown("atk", "def", now)
        import time as _t

        real = _t.time
        try:
            # 冻结时间到冷却期内（第 5 天边界内）
            _t.time = lambda: now + 100
            ok, remaining = await mgr.can_challenge("atk", "def")
            assert not ok and remaining > 0
            # 5×86400 后放行
            _t.time = lambda: now + IMPART_PK_COOLDOWN_SECONDS
            ok, remaining = await mgr.can_challenge("atk", "def")
            assert ok and remaining == 0
            # 不同对手不受限
            _t.time = lambda: now + 100
            ok, _ = await mgr.can_challenge("atk", "other")
            assert ok
        finally:
            _t.time = real
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_snatch_protection_window():
    """3-day protection counts down to zero after the window."""
    db = await _setup_db()
    try:
        mgr = ImpartManager(db, DummyConfigManager())
        now = 2_000_000_000
        await db.ext.upsert_impart_snatch_protection("def", now)

        import time as _t

        real = _t.time
        try:
            _t.time = lambda: now + 60
            remaining = await mgr.get_snatch_protection_remaining("def")
            assert remaining == IMPART_SNATCH_PROTECTION_SECONDS - 60
            _t.time = lambda: now + IMPART_SNATCH_PROTECTION_SECONDS
            assert await mgr.get_snatch_protection_remaining("def") == 0
        finally:
            _t.time = real
    finally:
        await db.close()


# ===== 排行（跨实例求和） =====


@pytest.mark.asyncio
async def test_ranking_sums_across_instances():
    """Ranking aggregates impart_value over all of a player's instances."""
    db = await _setup_db()
    try:
        await _create_player(db, "u1")
        await _create_player(db, "u2")
        mgr = ImpartManager(db, DummyConfigManager())

        a = await mgr.create_legacy("u1", "common", activate=False)
        b = await mgr.create_legacy("u1", "rift", activate=False)
        a.impart_value = 30
        b.impart_value = 25
        await db.ext.update_legacy_instance(a)
        await db.ext.update_legacy_instance(b)
        c = await mgr.create_legacy("u2", "common", activate=False)
        c.impart_value = 40
        await db.ext.update_legacy_instance(c)

        ranking = await mgr.get_ranking(10)
        totals = {r["user_id"]: r["impart_value"] for r in ranking}
        assert totals["u1"] == 55  # 30 + 25 across two instances
        assert totals["u2"] == 40
    finally:
        await db.close()


# ===== 战力断言：传承值不参与战斗属性 =====


@pytest.mark.asyncio
async def test_impart_value_does_not_affect_fighter_stats():
    """build_fighter_from_player output is identical regardless of impart value."""
    import sys

    _combat_name = "astrbot_plugin_monixiuxian2_2.managers.combat_manager"
    _combat_mod = sys.modules.get(_combat_name) or load_package_module(
        "managers/combat_manager.py",
        _combat_name,
    )
    CombatEngine = _combat_mod.CombatEngine

    db = await _setup_db()
    try:
        player = await _create_player(db)
        mgr = ImpartManager(db, DummyConfigManager())
        engine = CombatEngine(config_manager=DummyConfigManager())

        fighter_no = await engine.build_fighter_from_player(player)
        attrs_no = (
            fighter_no.hp,
            fighter_no.damage,
            fighter_no.agility,
            fighter_no.speed,
            fighter_no.armor_value,
        )

        inst = await mgr.create_legacy("u1", "common")
        inst.impart_value = 100  # 满级传承值
        await db.ext.update_legacy_instance(inst)
        player = await db.get_player_by_id("u1")

        fighter_yes = await engine.build_fighter_from_player(player)
        attrs_yes = (
            fighter_yes.hp,
            fighter_yes.damage,
            fighter_yes.agility,
            fighter_yes.speed,
            fighter_yes.armor_value,
        )

        assert attrs_no == attrs_yes
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_latest_db_version_bumped():
    """Ensure the migration version was bumped for the legacy-instance schema."""
    assert LATEST_DB_VERSION == 32

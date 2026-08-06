"""Tests for managers/impart_manager.py (impart value tiers and rewards)."""

import aiosqlite
import pytest

from tests.helpers import load_module, load_package_module

# Load modules under a synthetic package so relative imports resolve.
load_package_module(
    "models.py",
    "astrbot_plugin_monixiuxian2_2.models",
)
load_package_module(
    "models_extended.py",
    "astrbot_plugin_monixiuxian2_2.models_extended",
)
load_package_module(
    "data/database_extended.py",
    "astrbot_plugin_monixiuxian2_2.data.database_extended",
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
Player = load_package_module(
    "models.py",
    "astrbot_plugin_monixiuxian2_2.models",
).Player
load_package_module(
    "config_manager.py",
    "astrbot_plugin_monixiuxian2_2.config_manager",
)
_impart_mod = load_package_module(
    "managers/impart_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.impart_manager",
)
ImpartManager = _impart_mod.ImpartManager

_migration_mod = load_module("migration_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager
LATEST_DB_VERSION = _migration_mod.LATEST_DB_VERSION


class DummyConfigManager:
    """Minimal config manager stub for impart tests."""

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
            "tiers": [
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
        }

    def get_max_level(self, cultivation_type="灵修"):
        """Return highest valid level index for the dummy route."""
        return len(self.level_data) - 1


class TestHelpers:
    """Shared fixtures for impart manager tests."""

    @staticmethod
    async def setup_db():
        """Create a migrated in-memory database and attach DatabaseExtended."""
        db = DataBase(":memory:")
        await db.connect()
        await MigrationManager(db.conn, DummyConfigManager()).migrate()
        db.ext = DatabaseExtended(db.conn)
        return db

    @staticmethod
    async def create_player(db, user_id="u1"):
        """Create a basic player for reward tests."""
        player = Player(user_id=user_id, user_name="Tester", spiritual_root="天灵根")
        await db.create_player(player)
        return player


@pytest.mark.asyncio
async def test_tier_calculation_and_panel():
    """Tier calculation matches the configured thresholds and panel is Chinese."""
    db = await TestHelpers.setup_db()
    try:
        await TestHelpers.create_player(db)
        mgr = ImpartManager(db, DummyConfigManager())

        # Start: 0 value, tier 0.
        success, panel, info = await mgr.get_impart_info("u1")
        assert not success  # no impart info yet

        await db.ext.create_impart_info("u1")
        success, panel, info = await mgr.get_impart_info("u1")
        assert success
        assert "第0阶" in panel
        assert "传承值：0" in panel
        assert "下一阶：第1阶" in panel

        # Just below tier 1 threshold.
        ok, msg = await mgr.add_impart_value("u1", 19)
        assert ok
        success, panel, info = await mgr.get_impart_info("u1")
        assert "第0阶" in panel
        assert "传承值：19" in panel

        # Hit tier 1 and auto-grant the heart-method reward.
        ok, msg = await mgr.add_impart_value("u1", 1)
        assert ok
        success, panel, info = await mgr.get_impart_info("u1")
        assert "第1阶" in panel
        assert "传承值：20" in panel
        assert "已领取等阶：1" in panel

        # Jump to tier 3.
        ok, msg = await mgr.add_impart_value("u1", 40)
        assert ok
        success, panel, info = await mgr.get_impart_info("u1")
        assert "第3阶" in panel
        assert "传承值：60" in panel
        assert "已领取等阶：1, 2, 3" in panel
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_heart_method_reward_to_storage():
    """Tier 1 heart-method reward is added to the player's storage ring."""
    db = await TestHelpers.setup_db()
    try:
        player = await TestHelpers.create_player(db)
        mgr = ImpartManager(db, DummyConfigManager())

        await db.ext.create_impart_info("u1")
        ok, msg = await mgr.add_impart_value("u1", 20)
        assert ok

        # Reload player from DB to check storage ring.
        updated = await db.get_player_by_id("u1")
        items = updated.get_storage_ring_items()
        assert "传承心法·吐纳" in items
        assert items["传承心法·吐纳"] == 1

        # No skills should have been learned.
        skills = await db.ext.get_learned_skills("u1")
        assert skills == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_technique_reward_writes_player_skills():
    """Tier 3 technique reward is learned directly with source='impart'."""
    db = await TestHelpers.setup_db()
    try:
        player = await TestHelpers.create_player(db)
        mgr = ImpartManager(db, DummyConfigManager())

        await db.ext.create_impart_info("u1")
        ok, msg = await mgr.add_impart_value("u1", 60)
        assert ok

        # Heart-method rewards from tiers 1 and 2 should also be in storage.
        updated = await db.get_player_by_id("u1")
        items = updated.get_storage_ring_items()
        assert items.get("传承心法·吐纳") == 1
        assert items.get("传承心法·归元") == 1

        # Tier 3 technique should be learned.
        skills = await db.ext.get_learned_skills("u1")
        assert len(skills) == 1
        assert skills[0]["skill_id"] == "impart_skill_001"
        assert skills[0]["source"] == "impart"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_level_up_reward_caps():
    """Tier 5 level-up reward raises level_index and respects the cap."""
    db = await TestHelpers.setup_db()
    try:
        player = await TestHelpers.create_player(db)
        # Set level one below the configured maximum.
        player.level_index = 8
        await db.update_player(player)

        mgr = ImpartManager(db, DummyConfigManager())
        await db.ext.create_impart_info("u1")
        ok, msg = await mgr.add_impart_value("u1", 100)
        assert ok

        updated = await db.get_player_by_id("u1")
        assert updated.level_index == 9
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_level_up_reward_already_capped():
    """Tier 5 level-up reward is a no-op when the player is already at max level."""
    db = await TestHelpers.setup_db()
    try:
        player = await TestHelpers.create_player(db)
        player.level_index = 9
        await db.update_player(player)

        mgr = ImpartManager(db, DummyConfigManager())
        await db.ext.create_impart_info("u1")
        ok, msg = await mgr.add_impart_value("u1", 100)
        assert ok
        assert "已达境界上限" in msg

        updated = await db.get_player_by_id("u1")
        assert updated.level_index == 9
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_repeat_reward_prevention():
    """Claimed tier rewards are not granted again when impart value increases."""
    db = await TestHelpers.setup_db()
    try:
        player = await TestHelpers.create_player(db)
        mgr = ImpartManager(db, DummyConfigManager())

        await db.ext.create_impart_info("u1")
        await mgr.add_impart_value("u1", 20)
        await mgr.add_impart_value("u1", 20)
        await mgr.add_impart_value("u1", 20)

        updated = await db.get_player_by_id("u1")
        items = updated.get_storage_ring_items()
        # Tier 1 heart-method was claimed only once.
        assert items.get("传承心法·吐纳") == 1
        # Tier 2 heart-method was claimed only once.
        assert items.get("传承心法·归元") == 1

        skills = await db.ext.get_learned_skills("u1")
        # Tier 3 technique was claimed only once.
        assert len(skills) == 1
        assert skills[0]["skill_id"] == "impart_skill_001"

        info = await db.ext.get_impart_info("u1")
        assert sorted(info.get_claimed_tiers()) == [1, 2, 3]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_technique_star_up_on_repeat_claim():
    """Claiming a technique tier again only stars up the existing learned skill."""
    db = await TestHelpers.setup_db()
    try:
        player = await TestHelpers.create_player(db)
        mgr = ImpartManager(db, DummyConfigManager())

        await db.ext.create_impart_info("u1")
        # Reach tier 3 once.
        await mgr.add_impart_value("u1", 60)
        # Manually reset claimed tiers so tier 3 is granted again.
        info = await db.ext.get_impart_info("u1")
        info.set_claimed_tiers([1, 2])
        await db.ext.update_impart_info(info)

        # Re-grant tier 3 by adding a tiny value (no new tier threshold).
        ok, msg = await mgr.add_impart_value("u1", 1)
        assert ok

        skills = await db.ext.get_learned_skills("u1")
        assert len(skills) == 1
        assert skills[0]["skill_id"] == "impart_skill_001"
        assert skills[0]["star_level"] == 2
        assert "升星至2星" in msg
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_technique_max_star_compensation():
    """Max-star technique reward grants exp compensation, not a fake star-up."""
    db = await TestHelpers.setup_db()
    try:
        player = await TestHelpers.create_player(db)
        mgr = ImpartManager(db, DummyConfigManager())

        await db.ext.create_impart_info("u1")
        # Reach tier 3 and star the technique up to max (3).
        await mgr.add_impart_value("u1", 60)
        await db.ext.learn_or_star_up("u1", "impart_skill_001", "impart")
        await db.ext.learn_or_star_up("u1", "impart_skill_001", "impart")
        before = (await db.get_player_by_id("u1")).experience

        # Re-grant tier 3 while already at max star.
        info = await db.ext.get_impart_info("u1")
        info.set_claimed_tiers([1, 2])
        await db.ext.update_impart_info(info)
        ok, msg = await mgr.add_impart_value("u1", 1)
        assert ok

        skills = await db.ext.get_learned_skills("u1")
        assert skills[0]["skill_id"] == "impart_skill_001"
        assert skills[0]["star_level"] == 3  # unchanged at cap
        after = (await db.get_player_by_id("u1")).experience
        assert after - before == 500  # base 1000 x ratio 0.5
        assert "圆满" in msg and "修为" in msg
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_info_auto_grants_pending_rewards():
    """Opening the impart panel grants pending rewards and reflects them."""
    db = await TestHelpers.setup_db()
    try:
        player = await TestHelpers.create_player(db)
        await db.ext.create_impart_info("u1")

        # Manually bump impart value without using the manager (so rewards are pending).
        info = await db.ext.get_impart_info("u1")
        info.impart_value = 30
        await db.ext.update_impart_info(info)

        mgr = ImpartManager(db, DummyConfigManager())
        success, panel, _ = await mgr.get_impart_info("u1")
        assert success
        assert "🎁 自动发放奖励" in panel
        assert "传承心法·吐纳" in panel
        assert "第1阶" in panel

        updated = await db.get_player_by_id("u1")
        assert updated.get_storage_ring_items().get("传承心法·吐纳") == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_impart_info_not_found():
    """get_impart_info returns an error when the user has no impart record."""
    db = await TestHelpers.setup_db()
    try:
        mgr = ImpartManager(db, DummyConfigManager())
        success, msg, info = await mgr.get_impart_info("noone")
        assert not success
        assert info is None
        assert "未开启传承系统" in msg
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_latest_db_version_bumped():
    """Ensure the migration version was bumped for this rework."""
    assert LATEST_DB_VERSION == 27

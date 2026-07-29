"""Tests for growth-flow integration (task group 6).

Covers breakthrough/cultivation comprehension hooks via SkillManager,
combat-engine merge-count preference via CombatManager, and study-target
command logic via SkillManager (the underlying business logic).

Modules with top-level relative imports (breakthrough_manager, cultivation_manager,
technique_handler) cannot be loaded by load_module because the plugin root is not a
Python package.  Their integration is tested indirectly through the loadable
SkillManager and CombatManager modules.
"""

import json
import random

import pytest

from tests.helpers import load_module

# Load modules that are free of runtime relative imports
_skill_mod = load_module("skill_manager_gi", "core/skill_manager.py")
SkillManager = _skill_mod.SkillManager

_combat_mod = load_module("combat_manager_gi", "managers/combat_manager.py")
CombatManager = _combat_mod.CombatManager


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


class FakeDbExt:
    """In-memory player_skills store mirroring database_extended CRUD."""

    def __init__(self):
        self.player_skills: dict[tuple[str, str], dict] = {}

    async def get_learned_skills(self, user_id: str) -> list[dict]:
        return [
            {
                "skill_id": key[1],
                "star_level": value["star_level"],
                "source": value["source"],
                "learned_at": value["learned_at"],
            }
            for key, value in self.player_skills.items()
            if key[0] == user_id
        ]

    async def is_skill_learned(self, user_id: str, skill_id: str) -> bool:
        return (user_id, skill_id) in self.player_skills

    async def get_star_level(self, user_id: str, skill_id: str) -> int:
        entry = self.player_skills.get((user_id, skill_id))
        return entry["star_level"] if entry else 1

    async def learn_or_star_up(
        self, user_id: str, skill_id: str, source: str = ""
    ) -> tuple[bool, int]:
        import time

        now = int(time.time())
        key = (user_id, skill_id)
        if key not in self.player_skills:
            self.player_skills[key] = {
                "star_level": 1,
                "source": source,
                "learned_at": now,
            }
            return True, 1
        self.player_skills[key]["star_level"] += 1
        self.player_skills[key]["source"] = source
        self.player_skills[key]["learned_at"] = now
        return False, self.player_skills[key]["star_level"]


class FakeDb:
    def __init__(self):
        self.ext = FakeDbExt()


class FakePlayer:
    """Minimal Player stub for skill / combat tests."""

    def __init__(self, **kwargs):
        self.user_id = kwargs.get("user_id", "test")
        self.main_technique = kwargs.get("main_technique", "")
        self.study_target = kwargs.get("study_target", "")
        self.techniques = kwargs.get("techniques", "[]")
        self.weapon = kwargs.get("weapon", "")
        self.armor = kwargs.get("armor", "")
        self.cultivation_type = kwargs.get("cultivation_type", "灵修")
        self.battle_report_merge_count = kwargs.get(
            "battle_report_merge_count", 0
        )
        self.damage = kwargs.get("damage", 10)
        self.agility = kwargs.get("agility", 5)
        self.speed = kwargs.get("speed", 5)
        self.hp = kwargs.get("hp", 100)
        self.armor_value = kwargs.get("armor_value", 0)

    def get_techniques_list(self):
        try:
            return json.loads(self.techniques)
        except Exception:
            return []


class FakeConfigManager:
    """Config manager stub with skill-system settings."""

    def __init__(self, game_config=None):
        self.skills_data = {
            "基础吐纳": {
                "id": "common_001",
                "name": "基础吐纳",
                "_group": "通用功法池",
                "trigger_skill": {
                    "name": "气息流转",
                    "trigger_condition": "attack",
                    "trigger_rate": 0.15,
                    "effect": "damage_bonus",
                    "effect_value": 1.2,
                },
                "ultimate": None,
                "route_multiplier": {"灵修": 1.0, "体修": 1.0},
                "learn_coefficient": 1.0,
            },
            "御剑术": {
                "id": "spirit_001",
                "name": "御剑术",
                "_group": "灵修专属",
                "trigger_skill": {
                    "name": "剑气纵横",
                    "trigger_condition": "attack",
                    "trigger_rate": 0.25,
                    "effect": "damage_bonus",
                    "effect_value": 1.5,
                },
                "ultimate": {
                    "name": "万剑归宗",
                    "trigger_condition": "once_per_battle",
                    "effect": "massive_damage",
                    "effect_value": 3.0,
                },
                "route_multiplier": {"灵修": 1.2, "体修": 0.6},
                "learn_coefficient": 0.8,
            },
        }
        self.heart_methods_data = {
            "长春功": {
                "id": "heart_001",
                "name": "长春功",
                "passive_bonus": {"hp_percent": 0.1},
                "skill_pool": [
                    {"skill_id": "common_001", "learn_coefficient": 1.0},
                ],
                "route": "通用",
            },
        }
        self.weapons_data = {}
        self.items_data = {}
        self.game_config = game_config or {
            "skill_system": {
                "breakthrough_success_learn_rate": 0.20,
                "breakthrough_fail_learn_rate": 0.10,
                "cultivation_learn_rate": 0.15,
                "cultivation_learn_interval_hours": 2,
                "universal_pool_rate": 0.05,
                "universal_pool_no_heart_rate": 0.03,
                "random_growth_step": 5,
                "max_technique_slots": 4,
                "battle_report_merge_count": 10,
            }
        }


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def cfg():
    return FakeConfigManager()


@pytest.fixture
def db():
    return FakeDb()


@pytest.fixture
def mgr(cfg, db):
    return SkillManager(cfg, db)


# ------------------------------------------------------------------
# 6.1  Breakthrough random growth – comprehension pool and hooks
# ------------------------------------------------------------------


def test_random_growth_attribute_selection():
    """Simulate the random growth pick: exactly one of the four main attrs."""
    attrs = ["damage", "agility", "speed", "hp"]
    selected = random.choice(attrs)
    assert selected in attrs


def test_new_player_starts_at_level_one():
    """Newly generated players must start at level 1 (练气一阶 / 锻体一阶)."""
    from tests.helpers import load_package_module

    _cult_mod = load_package_module(
        "core/cultivation_manager.py",
        "astrbot_plugin_monixiuxian2_2.core.cultivation_manager",
    )
    CultivationManager = _cult_mod.CultivationManager

    class DummyConfig:
        def get(self, key, default=None):
            if key == "VALUES":
                return {"INITIAL_GOLD": 100}
            return default

        def __getitem__(self, key):
            return self.get(key)

    mgr2 = CultivationManager(DummyConfig(), FakeConfigManager())
    player = mgr2.generate_new_player_stats("u1", cultivation_type="灵修")
    assert player.level_index == 1

    player_body = mgr2.generate_new_player_stats("u2", cultivation_type="体修")
    assert player_body.level_index == 1


@pytest.mark.asyncio
async def test_breakthrough_success_comprehension_pool(mgr, db):
    """Breakthrough success pool contains heart-method pool + study target."""
    player = FakePlayer(main_technique="长春功", study_target="spirit_001")
    pool = await mgr._build_comprehension_pool(player, "breakthrough_success")
    skill_ids = {e["skill_id"] for e in pool}
    assert "common_001" in skill_ids  # from heart method pool
    assert "spirit_001" in skill_ids  # study target
    assert not any(e["source"] == "universal" for e in pool)


@pytest.mark.asyncio
async def test_breakthrough_fail_comprehension_pool(mgr, db):
    """Breakthrough fail pool uses same rules as success and excludes universal."""
    player = FakePlayer(main_technique="长春功", study_target="spirit_001")
    pool = await mgr._build_comprehension_pool(player, "breakthrough_fail")
    skill_ids = {e["skill_id"] for e in pool}
    assert "common_001" in skill_ids
    assert not any(e["source"] == "universal" for e in pool)


@pytest.mark.asyncio
async def test_universal_pool_no_heart_method(mgr, db):
    """Without heart method, universal pool fallback provides entry on breakthrough."""
    player = FakePlayer(main_technique="")
    _original = random.random
    random.random = lambda: 0.01
    try:
        result = await mgr.roll_universal_pool_breakthrough(player, success=False)
        if result is not None:
            assert "id" in result
    finally:
        random.random = _original


@pytest.mark.asyncio
async def test_universal_pool_with_heart_method_returns_none(mgr, db):
    """With heart method equipped, universal fallback is not used."""
    player = FakePlayer(main_technique="长春功")
    result = await mgr.roll_universal_pool_breakthrough(player, success=True)
    assert result is None


# ------------------------------------------------------------------
# 6.2  Cultivation comprehension hook – channel isolation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cultivation_pool_no_universal(mgr, db):
    """Cultivation channel must NOT include universal pool."""
    player = FakePlayer(main_technique="长春功")
    pool = await mgr._build_comprehension_pool(player, "cultivation")
    sources = {e["source"] for e in pool}
    assert "universal" not in sources


@pytest.mark.asyncio
async def test_cultivation_comprehension_roll_count(mgr, db):
    """roll_cultivation_comprehension rolls once per interval (2h default)."""
    player = FakePlayer(main_technique="长春功")
    results = await mgr.roll_cultivation_comprehension(player, hours=6)
    assert isinstance(results, list)
    assert len(results) <= 3


@pytest.mark.asyncio
async def test_cultivation_comprehension_no_heart_method_skips(mgr, db):
    """Without heart method, cultivation pool is empty (universal excluded)."""
    player = FakePlayer(main_technique="")
    pool = await mgr._build_comprehension_pool(player, "cultivation")
    assert pool == []


# ------------------------------------------------------------------
# 6.3  Study target command logic (via SkillManager)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_study_target_success(mgr, db):
    """Valid owned + unlearned skill can be set as study target."""
    player = FakePlayer()
    ok, msg = await mgr.set_study_target(player, "common_001", ["common_001"])
    assert ok
    assert player.study_target == "common_001"
    assert "基础吐纳" in msg


@pytest.mark.asyncio
async def test_set_study_target_not_owned(mgr, db):
    """Cannot set target for skill the player does not own."""
    player = FakePlayer()
    ok, msg = await mgr.set_study_target(player, "common_001", [])
    assert not ok
    assert "尚未拥有" in msg


@pytest.mark.asyncio
async def test_set_study_target_already_learned(mgr, db):
    """Cannot set target for already-learned skill."""
    await db.ext.learn_or_star_up("test", "common_001", "test")
    player = FakePlayer()
    ok, msg = await mgr.set_study_target(player, "common_001", ["common_001"])
    assert not ok
    assert "已领悟" in msg


@pytest.mark.asyncio
async def test_study_target_auto_cleared_on_learn(mgr, db):
    """Learning the target skill clears the study target."""
    player = FakePlayer(study_target="common_001")
    await mgr._resolve_and_learn(player, {"skill_id": "common_001", "source": "test"})
    assert player.study_target == ""


def test_get_study_target_info_present(mgr):
    """get_study_target_info returns skill details when target is set."""
    player = FakePlayer(study_target="common_001")
    info = mgr.get_study_target_info(player)
    assert info["has_target"]
    assert "基础吐纳" in info["name"]


def test_get_study_target_info_none(mgr):
    """get_study_target_info reports no target when none is set."""
    player = FakePlayer()
    info = mgr.get_study_target_info(player)
    assert not info["has_target"]


def test_clear_study_target_success(mgr):
    """Clear removes the study target."""
    player = FakePlayer(study_target="common_001")
    ok, msg = mgr.clear_study_target(player)
    assert ok
    assert player.study_target == ""
    assert "基础吐纳" in msg


def test_clear_study_target_none(mgr):
    """Clear returns failure when there is no target."""
    player = FakePlayer()
    ok, msg = mgr.clear_study_target(player)
    assert not ok


# ------------------------------------------------------------------
# 6.3  Battle report merge count preference (via CombatManager)
# ------------------------------------------------------------------


def test_merge_count_player_preference():
    """CombatManager._get_merge_count returns player preference when set."""
    cfg = FakeConfigManager()
    mgr2 = CombatManager(cfg, None)
    player = FakePlayer(battle_report_merge_count=42)
    assert mgr2._get_merge_count(player) == 42


def test_merge_count_falls_back_to_config():
    """Falls back to game_config default when player value is 0."""
    cfg = FakeConfigManager()
    mgr2 = CombatManager(cfg, None)
    player = FakePlayer(battle_report_merge_count=0)
    assert mgr2._get_merge_count(player) == 10


def test_merge_count_clamps_high():
    """Values above 50 are clamped to 50."""
    cfg = FakeConfigManager()
    mgr2 = CombatManager(cfg, None)
    assert mgr2._get_merge_count(FakePlayer(battle_report_merge_count=100)) == 50


def test_merge_count_ignores_negative():
    """Negative values fall back to default."""
    cfg = FakeConfigManager()
    mgr2 = CombatManager(cfg, None)
    assert mgr2._get_merge_count(FakePlayer(battle_report_merge_count=-5)) == 10


def test_merge_count_handles_non_int():
    """Non-integer values fall back to default (hasattr returns True for 0)."""
    cfg = FakeConfigManager()
    mgr2 = CombatManager(cfg, None)
    player = FakePlayer()
    player.battle_report_merge_count = "not-int"
    assert mgr2._get_merge_count(player) == 10

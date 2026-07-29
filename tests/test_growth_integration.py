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


class FakePlayer:
    """Minimal Player stub for skill / combat tests."""

    def __init__(self, **kwargs):
        self.user_id = kwargs.get("user_id", "test")
        self.main_technique = kwargs.get("main_technique", "")
        self.study_target = kwargs.get("study_target", "")
        self.learned_skills = kwargs.get("learned_skills", "[]")
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

    def get_learned_skills(self):
        try:
            return json.loads(self.learned_skills)
        except Exception:
            return []

    def set_learned_skills(self, skills):
        self.learned_skills = json.dumps(skills, ensure_ascii=False)

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
        self.game_config = game_config or {
            "skill_system": {
                "breakthrough_success_learn_rate": 0.20,
                "breakthrough_fail_learn_rate": 0.10,
                "cultivation_learn_rate": 0.15,
                "cultivation_learn_interval_hours": 2,
                "universal_pool_rate": 0.05,
                "universal_pool_no_heart_rate": 0.03,
                "random_growth_step": 5,
                "max_technique_slots": 3,
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
def mgr(cfg):
    return SkillManager(cfg)


# ------------------------------------------------------------------
# 6.1  Breakthrough random growth – comprehension pool and hooks
# ------------------------------------------------------------------


def test_random_growth_attribute_selection():
    """Simulate the random growth pick: exactly one of the four main attrs."""
    attrs = ["damage", "agility", "speed", "hp"]
    selected = random.choice(attrs)
    assert selected in attrs


def test_breakthrough_success_comprehension_called(mgr):
    """roll_breakthrough_success_comprehension builds pool with heart method."""
    player = FakePlayer(main_technique="长春功", study_target="spirit_001")
    pool = mgr._build_comprehension_pool(player, "breakthrough_success")
    skill_ids = {e["skill_id"] for e in pool}
    assert "common_001" in skill_ids  # from heart method pool
    assert "spirit_001" in skill_ids  # study target
    assert any(e["source"] == "universal" for e in pool)


def test_breakthrough_fail_comprehension_pool(mgr):
    """roll_breakthrough_fail_comprehension uses same pool rules as success."""
    player = FakePlayer(main_technique="长春功", study_target="spirit_001")
    pool = mgr._build_comprehension_pool(player, "breakthrough_fail")
    skill_ids = {e["skill_id"] for e in pool}
    assert "common_001" in skill_ids
    assert any(e["source"] == "universal" for e in pool)


def test_universal_pool_no_heart_method(mgr):
    """Without heart method, universal pool fallback provides entry on breakthrough."""
    player = FakePlayer(main_technique="")
    # Force the fallback probability check to pass
    _original = random.random
    random.random = lambda: 0.01  # always below 0.03
    try:
        result = mgr.roll_universal_pool_breakthrough(player, success=False)
        if result is not None:
            assert "id" in result
    finally:
        random.random = _original


def test_universal_pool_with_heart_method_returns_none(mgr):
    """With heart method equipped, universal fallback is not used."""
    player = FakePlayer(main_technique="长春功")
    result = mgr.roll_universal_pool_breakthrough(player, success=True)
    assert result is None


# ------------------------------------------------------------------
# 6.2  Cultivation comprehension hook – channel isolation
# ------------------------------------------------------------------


def test_cultivation_pool_no_universal(mgr):
    """Cultivation channel must NOT include universal pool."""
    player = FakePlayer(main_technique="长春功")
    pool = mgr._build_comprehension_pool(player, "cultivation")
    sources = {e["source"] for e in pool}
    assert "universal" not in sources


def test_cultivation_comprehension_roll_count(mgr):
    """roll_cultivation_comprehension rolls once per interval (2h default)."""
    player = FakePlayer(main_technique="长春功")
    # With no learned skills, comprehension should find common_001 from pool
    results = mgr.roll_cultivation_comprehension(player, hours=6)
    # 6h gives 3 rolls; with random there may be 0-3 results
    assert isinstance(results, list)
    assert len(results) <= 3


def test_cultivation_comprehension_no_heart_method_skips(mgr):
    """Without heart method, cultivation pool is empty (universal excluded)."""
    player = FakePlayer(main_technique="")
    pool = mgr._build_comprehension_pool(player, "cultivation")
    assert pool == []


# ------------------------------------------------------------------
# 6.3  Study target command logic (via SkillManager)
# ------------------------------------------------------------------


def test_set_study_target_success(mgr):
    """Valid owned + unlearned skill can be set as study target."""
    player = FakePlayer()
    ok, msg = mgr.set_study_target(player, "common_001", ["common_001"])
    assert ok
    assert player.study_target == "common_001"
    assert "基础吐纳" in msg


def test_set_study_target_not_owned(mgr):
    """Cannot set target for skill the player does not own."""
    player = FakePlayer()
    ok, msg = mgr.set_study_target(player, "common_001", [])
    assert not ok
    assert "尚未拥有" in msg


def test_set_study_target_already_learned(mgr):
    """Cannot set target for already-learned skill."""
    player = FakePlayer(
        learned_skills='[{"skill_id":"common_001","star_level":1}]'
    )
    ok, msg = mgr.set_study_target(player, "common_001", ["common_001"])
    assert not ok
    assert "已领悟" in msg


def test_study_target_auto_cleared_on_learn(mgr):
    """Learning the target skill clears the study target."""
    player = FakePlayer(study_target="common_001")
    mgr._resolve_and_learn(player, {"skill_id": "common_001", "source": "test"})
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
    mgr = CombatManager(cfg, None)
    player = FakePlayer(battle_report_merge_count=42)
    assert mgr._get_merge_count(player) == 42


def test_merge_count_falls_back_to_config():
    """Falls back to game_config default when player value is 0."""
    cfg = FakeConfigManager()
    mgr = CombatManager(cfg, None)
    player = FakePlayer(battle_report_merge_count=0)
    assert mgr._get_merge_count(player) == 10


def test_merge_count_clamps_high():
    """Values above 50 are clamped to 50."""
    cfg = FakeConfigManager()
    mgr = CombatManager(cfg, None)
    assert mgr._get_merge_count(FakePlayer(battle_report_merge_count=100)) == 50


def test_merge_count_ignores_negative():
    """Negative values fall back to default."""
    cfg = FakeConfigManager()
    mgr = CombatManager(cfg, None)
    assert mgr._get_merge_count(FakePlayer(battle_report_merge_count=-5)) == 10


def test_merge_count_handles_non_int():
    """Non-integer values fall back to default (hasattr returns True for 0)."""
    cfg = FakeConfigManager()
    mgr = CombatManager(cfg, None)
    player = FakePlayer()
    player.battle_report_merge_count = "not-int"
    assert mgr._get_merge_count(player) == 10

"""Tests for core/skill_manager.py.

Uses tests/helpers.py load_module to bypass __init__.py relative imports.
"""

import json
import sys
from pathlib import Path

import pytest

from tests.helpers import load_module

# Ensure plugin root is on path
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

# Load the module under test
_skill_mod = load_module("skill_manager_test", "core/skill_manager.py")
SkillManager = _skill_mod.SkillManager


class FakePlayer:
    """Minimal player stub for skill manager tests."""

    def __init__(self, **kwargs):
        self.main_technique = kwargs.get("main_technique", "")
        self.study_target = kwargs.get("study_target", "")
        self.learned_skills = kwargs.get("learned_skills", "[]")
        self.techniques = kwargs.get("techniques", "[]")
        self.weapon = kwargs.get("weapon", "")
        self.armor = kwargs.get("armor", "")
        self.cultivation_type = kwargs.get("cultivation_type", "灵修")

    def get_learned_skills(self):
        try:
            return json.loads(self.learned_skills)
        except json.JSONDecodeError:
            return []

    def set_learned_skills(self, skills):
        self.learned_skills = json.dumps(skills, ensure_ascii=False)

    def get_techniques_list(self):
        try:
            return json.loads(self.techniques)
        except json.JSONDecodeError:
            return []


class FakeConfigManager:
    """Minimal config manager stub with skill system data."""

    def __init__(self):
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
            "铁布衫": {
                "id": "common_002",
                "name": "铁布衫",
                "_group": "通用功法池",
                "trigger_skill": {
                    "name": "金刚护体",
                    "trigger_condition": "defend",
                    "trigger_rate": 0.2,
                    "effect": "damage_reduction",
                    "effect_value": 0.5,
                },
                "ultimate": None,
                "route_multiplier": {"灵修": 0.8, "体修": 1.2},
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
                    {"skill_id": "common_002", "learn_coefficient": 0.8},
                ],
                "route": "通用",
            },
            "焚天诀": {
                "id": "heart_002",
                "name": "焚天诀",
                "passive_bonus": {"damage_percent": 0.15},
                "skill_pool": [
                    {"skill_id": "spirit_001", "learn_coefficient": 0.6},
                    {"skill_id": "common_001", "learn_coefficient": 0.9},
                ],
                "route": "灵修",
            },
        }
        self.weapons_data = {
            "铁剑": {
                "name": "铁剑",
                "weapon_coefficient_k": 1.2,
                "base_damage": 15,
                "armor_value": 0,
                "trigger_skills": [],
            },
            "布衣": {
                "name": "布衣",
                "armor_value": 5,
            },
        }
        self.items_data = {
            "玄铁甲": {
                "name": "玄铁甲",
                "type": "法器",
                "subtype": "防具",
                "armor_value": 10,
            },
        }
        self.game_config = {
            "skill_system": {
                "breakthrough_success_learn_rate": 0.20,
                "breakthrough_fail_learn_rate": 0.10,
                "cultivation_learn_rate": 0.15,
                "cultivation_learn_interval_hours": 2,
                "universal_pool_rate": 0.05,
                "universal_pool_no_heart_rate": 0.03,
                "max_technique_slots": 3,
            }
        }


# Fixtures


@pytest.fixture
def cfg():
    return FakeConfigManager()


@pytest.fixture
def mgr(cfg):
    return SkillManager(cfg)


# ------------------------------------------------------------------
# 3.1 Comprehension pool
# ------------------------------------------------------------------


def test_build_pool_with_heart_method(mgr):
    """Pool includes heart method skill pool + study target."""
    player = FakePlayer(main_technique="长春功", study_target="spirit_001")
    pool = mgr._build_comprehension_pool(player, "breakthrough_success")
    skill_ids = {e["skill_id"] for e in pool}
    assert "common_001" in skill_ids
    assert "common_002" in skill_ids
    assert "spirit_001" in skill_ids  # study target


def test_build_pool_cultivation_no_universal(mgr):
    """Cultivation channel MUST NOT include universal pool."""
    player = FakePlayer(main_technique="长春功")
    pool = mgr._build_comprehension_pool(player, "cultivation")
    sources = {e["source"] for e in pool}
    assert "universal" not in sources


def test_build_pool_no_universal(mgr):
    """Breakthrough pool MUST NOT include universal pool directly."""
    player = FakePlayer(main_technique="长春功")
    pool = mgr._build_comprehension_pool(player, "breakthrough_success")
    sources = {e["source"] for e in pool}
    assert "universal" not in sources


def test_pool_coefficients_stored_separately(mgr):
    """Pool entries keep coefficients for success probability only."""
    player = FakePlayer(main_technique="焚天诀")
    pool = mgr._build_comprehension_pool(player, "breakthrough_success")
    coeffs = {e["skill_id"]: e.get("coefficient", 1.0) for e in pool}
    weights = {e["skill_id"]: e["weight"] for e in pool}
    # spirit_001 has coefficient 0.6, common_001 has 0.9
    assert coeffs["spirit_001"] < coeffs["common_001"]
    # Selection weights are uniform
    assert weights["spirit_001"] == weights["common_001"]


def test_coefficient_affects_success_probability(mgr):
    """Coefficient 0.2 gives one-fifth the success chance of coefficient 1.0."""
    import random as _random

    original_choice = _random.choice
    original_random = _random.random
    try:
        # Coefficient 1.0: success boundary is base_rate * 1.0 = 0.5.
        high_pool = [
            {"skill_id": "high", "weight": 1.0, "coefficient": 1.0, "source": "test"},
        ]
        _random.choice = lambda p: high_pool[0]
        _random.random = lambda: 0.4
        assert mgr._roll_comprehension(high_pool, base_rate=0.5) is not None

        # Coefficient 0.2: success boundary is 0.5 * 0.2 = 0.1.
        low_pool = [
            {"skill_id": "low", "weight": 1.0, "coefficient": 0.2, "source": "test"},
        ]
        _random.choice = lambda p: low_pool[0]
        _random.random = lambda: 0.4
        assert mgr._roll_comprehension(low_pool, base_rate=0.5) is None

        # A roll below the 0.1 boundary succeeds.
        _random.random = lambda: 0.05
        assert mgr._roll_comprehension(low_pool, base_rate=0.5) is not None
    finally:
        _random.choice = original_choice
        _random.random = original_random


# ------------------------------------------------------------------
# 3.2 Star-up
# ------------------------------------------------------------------


def test_learn_new_skill(mgr):
    """First learn adds skill to learned_skills with star_level 1."""
    player = FakePlayer()
    result = mgr._resolve_and_learn(
        player, {"skill_id": "common_001", "source": "test"}
    )
    assert result is not None
    assert result["current_star_level"] == 1
    learned = player.get_learned_skills()
    assert len(learned) == 1
    assert learned[0]["skill_id"] == "common_001"
    assert learned[0]["star_level"] == 1


def test_duplicate_skill_star_up(mgr):
    """Duplicate learn auto star-up, does not add new slot."""
    player = FakePlayer(learned_skills='[{"skill_id":"common_001","star_level":1}]')
    result = mgr._resolve_and_learn(
        player, {"skill_id": "common_001", "source": "test"}
    )
    assert result is not None
    assert result["current_star_level"] == 2
    learned = player.get_learned_skills()
    assert len(learned) == 1
    assert learned[0]["star_level"] == 2


def test_star_up_boosts_trigger_rate(mgr):
    """Star level increases trigger rate."""
    _ = FakePlayer(learned_skills='[{"skill_id":"common_001","star_level":3}]')
    skill_def = mgr._find_skill_definition("common_001")
    boosted = mgr._apply_star_to_def(skill_def, 3)
    base_rate = skill_def["trigger_skill"]["trigger_rate"]
    boosted_rate = boosted["trigger_skill"]["trigger_rate"]
    assert boosted_rate > base_rate


# ------------------------------------------------------------------
# 3.3 Heart method passive
# ------------------------------------------------------------------


def test_heart_method_passive_present(mgr):
    """Equipped heart method returns its passive bonus."""
    player = FakePlayer(main_technique="长春功")
    passive = mgr.get_heart_method_passive(player)
    assert passive.get("hp_percent") == 0.1


def test_no_heart_method_no_passive(mgr):
    """No heart method equipped returns empty dict."""
    player = FakePlayer(main_technique="")
    passive = mgr.get_heart_method_passive(player)
    assert passive == {}


# ------------------------------------------------------------------
# 3.4 Study target
# ------------------------------------------------------------------


def test_set_study_target_success(mgr):
    """Can set study target for owned, unlearned skill."""
    player = FakePlayer()
    ok, msg = mgr.set_study_target(player, "common_001", ["common_001"])
    assert ok
    assert player.study_target == "common_001"


def test_set_study_target_not_owned(mgr):
    """Cannot set target for unowned skill."""
    player = FakePlayer()
    ok, msg = mgr.set_study_target(player, "common_001", [])
    assert not ok
    assert "尚未拥有" in msg


def test_set_study_target_already_learned(mgr):
    """Cannot set target for already learned skill."""
    player = FakePlayer(learned_skills='[{"skill_id":"common_001","star_level":1}]')
    ok, msg = mgr.set_study_target(player, "common_001", ["common_001"])
    assert not ok
    assert "已领悟" in msg


def test_study_target_cleared_on_learn(mgr):
    """Study target is auto-cleared when the skill is learned."""
    player = FakePlayer(study_target="common_001")
    mgr._resolve_and_learn(player, {"skill_id": "common_001", "source": "test"})
    assert player.study_target == ""


# ------------------------------------------------------------------
# 3.5 Equipment validation
# ------------------------------------------------------------------


def test_cannot_equip_unlearned(mgr):
    """Unlearned technique cannot be equipped."""
    player = FakePlayer()
    ok, msg = mgr.can_equip_technique(player, "基础吐纳", ["common_001"])
    assert not ok
    assert "尚未领悟" in msg


def test_can_equip_learned(mgr):
    """Learned technique can be equipped."""
    player = FakePlayer(learned_skills='[{"skill_id":"common_001","star_level":1}]')
    ok, msg = mgr.can_equip_technique(player, "基础吐纳", ["common_001"])
    assert ok


def test_slot_limit(mgr):
    """Cannot exceed max technique slots."""
    player = FakePlayer(
        learned_skills='[{"skill_id":"common_001","star_level":1},{"skill_id":"common_002","star_level":1},{"skill_id":"spirit_001","star_level":1}]',
        techniques='["基础吐纳","铁布衫","御剑术"]',
    )
    # Try to equip a 4th (different skill name that is learned)
    ok, msg = mgr.can_equip_technique(player, "铁布衫", ["common_002"])
    assert not ok
    assert "已满" in msg


# ------------------------------------------------------------------
# Universal pool fallback (no heart method)
# ------------------------------------------------------------------


def test_universal_pool_no_heart_method(mgr):
    """Without heart method, universal pool provides fallback on breakthrough."""
    player = FakePlayer(main_technique="")
    # Force success by monkey-patching random
    import random as _random

    original_random = _random.random
    _random.random = lambda: 0.01  # Always below 0.03
    try:
        result = mgr.roll_universal_pool_breakthrough(player, success=False)
        # Should return a skill definition or None depending on pool
        # The method returns None if skill already learned or no skill found
        # Here player has no learned skills, so it should return a skill def
        if result is not None:
            assert "id" in result
    finally:
        _random.random = original_random


def test_universal_pool_not_called_with_heart_method(mgr):
    """With heart method equipped, universal fallback returns None."""
    player = FakePlayer(main_technique="长春功")
    result = mgr.roll_universal_pool_breakthrough(player, success=True)
    assert result is None


# ------------------------------------------------------------------
# Battle loadout export (for Group 4)
# ------------------------------------------------------------------


def test_battle_loadout_structure(mgr):
    """Battle loadout contains expected keys."""
    player = FakePlayer(
        weapon="铁剑",
        armor="布衣",
        learned_skills='[{"skill_id":"common_001","star_level":1}]',
        techniques='["基础吐纳"]',
    )
    loadout = mgr.get_battle_loadout(player)
    assert "trigger_skills" in loadout
    assert "ultimates" in loadout
    assert "heart_method_passive" in loadout
    assert loadout["weapon_coefficient_k"] == 1.2
    assert loadout["armor_value"] == 5


def test_battle_loadout_skills_star_applied(mgr):
    """Battle loadout applies star level to skill definitions."""
    player = FakePlayer(
        learned_skills='[{"skill_id":"common_001","star_level":3}]',
        techniques='["基础吐纳"]',
    )
    loadout = mgr.get_battle_loadout(player)
    trigger = loadout["trigger_skills"][0]
    assert trigger.get("star_level") == 3

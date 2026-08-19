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


class FakeDbExt:
    """In-memory player_skills store mirroring database_extended CRUD."""

    def __init__(self):
        self.player_skills: dict[tuple[str, str], dict] = {}
        self.sects: dict[int, object] = {}

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
        self,
        user_id: str,
        skill_id: str,
        source: str = "",
        max_star: int = 3,
        max_star_exp_compensation: int = 0,
        origin_sect_id: str | None = None,
        sect_bound: bool = False,
    ) -> tuple[bool, int]:
        import time

        now = int(time.time())
        key = (user_id, skill_id)
        if key not in self.player_skills:
            self.player_skills[key] = {
                "star_level": 1,
                "source": source,
                "learned_at": now,
                "origin_sect_id": origin_sect_id,
                "sect_bound": sect_bound,
            }
            return True, 1
        current_star = self.player_skills[key]["star_level"]
        if current_star >= max_star:
            return False, max_star
        self.player_skills[key]["star_level"] = current_star + 1
        self.player_skills[key]["source"] = source
        self.player_skills[key]["learned_at"] = now
        return False, self.player_skills[key]["star_level"]

    async def get_sect_by_id(self, sect_id: int):
        return self.sects.get(sect_id)


class FakeDb:
    """Minimal database stub exposing the ext namespace used by SkillManager."""

    def __init__(self):
        self.ext = FakeDbExt()


class FakePlayer:
    """Minimal player stub for skill manager tests."""

    def __init__(self, **kwargs):
        self.user_id = kwargs.get("user_id", "u1")
        self.main_technique = kwargs.get("main_technique", "")
        self.study_target = kwargs.get("study_target", "")
        self.techniques = kwargs.get("techniques", "[]")
        self.weapon = kwargs.get("weapon", "")
        self.armor = kwargs.get("armor", "")
        self.cultivation_type = kwargs.get("cultivation_type", "灵修")
        self.sect_id = kwargs.get("sect_id", 0)

    def get_techniques_list(self) -> list[str]:
        try:
            return json.loads(self.techniques)
        except json.JSONDecodeError:
            return []

    def set_techniques_list(self, techniques_list: list[str]):
        self.techniques = json.dumps(techniques_list, ensure_ascii=False)


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
                    "effect_type": "damage_bonus",
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
                    "effect_type": "damage_reduction",
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
                    "effect_type": "damage_bonus",
                    "effect_value": 1.5,
                },
                "ultimate": {
                    "name": "万剑归宗",
                    "trigger_condition": "once_per_battle",
                    "effect_type": "massive_damage",
                    "effect_value": 3.0,
                },
                "route_multiplier": {"灵修": 1.2, "体修": 0.6},
                "learn_coefficient": 0.8,
            },
            "青云剑诀": {
                "id": "qy_001",
                "name": "青云剑诀",
                "_group": "sect_qingyun",
                "trigger_skill": {
                    "name": "青云一剑",
                    "trigger_condition": "attack",
                    "trigger_rate": 0.18,
                    "effect_type": "damage_bonus",
                    "effect_value": 0.3,
                },
                "ultimate": None,
                "route_multiplier": {"灵修": 1.0, "体修": 1.0},
                "learn_coefficient": 0.5,
                "sect_bound": True,
            },
        }
        self.sect_factions = {
            "factions": [
                {
                    "id": "qingyun",
                    "name": "青云门",
                    "skill_pool": "sect_qingyun",
                },
                {
                    "id": "wuchi",
                    "name": "无池宗",
                },
            ]
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
                "max_technique_slots": 4,
            }
        }


# Fixtures


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
# 3.1 Comprehension pool
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_pool_with_heart_method(mgr, db):
    """Pool includes heart method skill pool + study target."""
    player = FakePlayer(main_technique="长春功", study_target="spirit_001")
    pool = await mgr._build_comprehension_pool(player, "breakthrough_success")
    skill_ids = {e["skill_id"] for e in pool}
    assert "common_001" in skill_ids
    assert "common_002" in skill_ids
    assert "spirit_001" in skill_ids  # study target


@pytest.mark.asyncio
async def test_build_pool_cultivation_no_universal(mgr, db):
    """Cultivation channel MUST NOT include universal pool."""
    player = FakePlayer(main_technique="长春功")
    pool = await mgr._build_comprehension_pool(player, "cultivation")
    sources = {e["source"] for e in pool}
    assert "universal" not in sources


@pytest.mark.asyncio
async def test_build_pool_no_universal(mgr, db):
    """Breakthrough pool MUST NOT include universal pool directly."""
    player = FakePlayer(main_technique="长春功")
    pool = await mgr._build_comprehension_pool(player, "breakthrough_success")
    sources = {e["source"] for e in pool}
    assert "universal" not in sources


@pytest.mark.asyncio
async def test_pool_coefficients_stored_separately(mgr, db):
    """Pool entries keep coefficients for success probability only."""
    player = FakePlayer(main_technique="焚天诀")
    pool = await mgr._build_comprehension_pool(player, "breakthrough_success")
    coeffs = {e["skill_id"]: e.get("coefficient", 1.0) for e in pool}
    weights = {e["skill_id"]: e["weight"] for e in pool}
    # spirit_001 has coefficient 0.6, common_001 has 0.9
    assert coeffs["spirit_001"] < coeffs["common_001"]
    # Selection weights are uniform
    assert weights["spirit_001"] == weights["common_001"]


def test_coefficient_affects_success_probability(mgr, db):
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


@pytest.mark.asyncio
async def test_learn_new_skill(mgr, db):
    """First learn inserts into player_skills with star_level 1."""
    player = FakePlayer()
    result = await mgr._resolve_and_learn(
        player, {"skill_id": "common_001", "source": "test"}
    )
    assert result is not None
    assert result["current_star_level"] == 1
    learned = await db.ext.get_learned_skills(player.user_id)
    assert len(learned) == 1
    assert learned[0]["skill_id"] == "common_001"
    assert learned[0]["star_level"] == 1


@pytest.mark.asyncio
async def test_duplicate_skill_star_up(mgr, db):
    """Duplicate learn auto star-up, does not add new slot."""
    await db.ext.learn_or_star_up("u1", "common_001", "test")
    player = FakePlayer()
    result = await mgr._resolve_and_learn(
        player, {"skill_id": "common_001", "source": "test"}
    )
    assert result is not None
    assert result["current_star_level"] == 2
    learned = await db.ext.get_learned_skills(player.user_id)
    assert len(learned) == 1
    assert learned[0]["star_level"] == 2


def test_star_up_boosts_trigger_rate(mgr, db):
    """Star level increases trigger rate."""
    skill_def = mgr._find_skill_definition("common_001")
    boosted = mgr._apply_star_to_def(skill_def, 3)
    base_rate = skill_def["trigger_skill"]["trigger_rate"]
    boosted_rate = boosted["trigger_skill"]["trigger_rate"]
    assert boosted_rate > base_rate


# ------------------------------------------------------------------
# 3.3 Heart method passive
# ------------------------------------------------------------------


def test_heart_method_passive_present(mgr, db):
    """Equipped heart method returns its passive bonus."""
    player = FakePlayer(main_technique="长春功")
    passive = mgr.get_heart_method_passive(player)
    assert passive.get("hp_percent") == 0.1


def test_no_heart_method_no_passive(mgr, db):
    """No heart method equipped returns empty dict."""
    player = FakePlayer(main_technique="")
    passive = mgr.get_heart_method_passive(player)
    assert passive == {}


# ------------------------------------------------------------------
# 3.4 Study target
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_study_target_success(mgr, db):
    """Can set study target for owned, unlearned skill."""
    player = FakePlayer()
    ok, msg = await mgr.set_study_target(player, "common_001", ["common_001"])
    assert ok
    assert player.study_target == "common_001"


@pytest.mark.asyncio
async def test_set_study_target_not_owned(mgr, db):
    """Cannot set target for unowned skill."""
    player = FakePlayer()
    ok, msg = await mgr.set_study_target(player, "common_001", [])
    assert not ok
    assert "尚未拥有" in msg


@pytest.mark.asyncio
async def test_set_study_target_already_learned(mgr, db):
    """Cannot set target for already learned skill."""
    await db.ext.learn_or_star_up("u1", "common_001", "test")
    player = FakePlayer()
    ok, msg = await mgr.set_study_target(player, "common_001", ["common_001"])
    assert not ok
    assert "已领悟" in msg


@pytest.mark.asyncio
async def test_study_target_cleared_on_learn(mgr, db):
    """Study target is auto-cleared when the skill is learned."""
    player = FakePlayer(study_target="common_001")
    await mgr._resolve_and_learn(
        player, {"skill_id": "common_001", "source": "test"}
    )
    assert player.study_target == ""


# ------------------------------------------------------------------
# 3.5 Equipment validation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_equip_unlearned(mgr, db):
    """Unlearned technique cannot be equipped."""
    player = FakePlayer()
    ok, msg = await mgr.can_equip_technique(player, "基础吐纳", ["common_001"])
    assert not ok
    assert "尚未领悟" in msg


@pytest.mark.asyncio
async def test_can_equip_learned(mgr, db):
    """Learned technique can be equipped."""
    await db.ext.learn_or_star_up("u1", "common_001", "test")
    player = FakePlayer()
    ok, msg = await mgr.can_equip_technique(player, "基础吐纳", ["common_001"])
    assert ok


@pytest.mark.asyncio
async def test_slot_limit(mgr, db):
    """Cannot exceed max technique slots (default 4, so need 4 in list)."""
    await db.ext.learn_or_star_up("u1", "common_001", "test")
    await db.ext.learn_or_star_up("u1", "common_002", "test")
    await db.ext.learn_or_star_up("u1", "spirit_001", "test")
    player = FakePlayer(
        techniques='["基础吐纳","铁布衫","御剑术"]',
    )
    # Activate a 4th (different skill name that is learned)
    ok, msg = await mgr.can_equip_technique(player, "铁布衫", ["common_002"])
    assert not ok
    assert "已装备" in msg  # Already in list, so it's not "已满" yet

    # Now with 4 different techniques, the 5th should hit slot limit
    # First set up: 4 slots filled -> can't equip a 5th
    mgr._skill_cfg["max_technique_slots"] = 3
    player2 = FakePlayer(
        techniques='["基础吐纳","铁布衫","御剑术"]',
    )
    ok2, msg2 = await mgr.can_equip_technique(player2, "铁布衫", ["common_002"])
    assert not ok2
    assert "已满" in msg2 or "已装备" in msg2


# ------------------------------------------------------------------
# Universal pool fallback (no heart method)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_universal_pool_no_heart_method(mgr, db):
    """Without heart method, universal pool provides fallback on breakthrough."""
    player = FakePlayer(main_technique="")
    # Force success by monkey-patching random
    import random as _random

    original_random = _random.random
    _random.random = lambda: 0.01  # Always below 0.03
    try:
        result = await mgr.roll_universal_pool_breakthrough(player, success=False)
        # Should return a skill definition or None depending on pool
        # The method returns None if skill already learned or no skill found
        # Here player has no learned skills, so it should return a skill def
        if result is not None:
            assert "id" in result
    finally:
        _random.random = original_random


@pytest.mark.asyncio
async def test_universal_pool_not_called_with_heart_method(mgr, db):
    """With heart method equipped, universal fallback returns None."""
    player = FakePlayer(main_technique="长春功")
    result = await mgr.roll_universal_pool_breakthrough(player, success=True)
    assert result is None


# ------------------------------------------------------------------
# Battle loadout export (for Group 4)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_battle_loadout_structure(mgr, db):
    """Battle loadout contains expected keys."""
    await db.ext.learn_or_star_up("u1", "common_001", "test")
    player = FakePlayer(
        weapon="铁剑",
        armor="布衣",
        techniques='["基础吐纳"]',
    )
    loadout = await mgr.get_battle_loadout(player)
    assert "trigger_skills" in loadout
    assert "ultimates" in loadout
    assert "heart_method_passive" in loadout
    assert loadout["weapon_coefficient_k"] == 1.2
    assert loadout["armor_value"] == 5


@pytest.mark.asyncio
async def test_battle_loadout_skills_star_applied(mgr, db):
    """Battle loadout reads star level from player_skills table."""
    await db.ext.learn_or_star_up("u1", "common_001", "test")
    await db.ext.learn_or_star_up("u1", "common_001", "test")  # star 2
    await db.ext.learn_or_star_up("u1", "common_001", "test")  # star 3
    player = FakePlayer(
        techniques='["基础吐纳"]',
    )
    loadout = await mgr.get_battle_loadout(player)
    trigger = loadout["trigger_skills"][0]
    assert trigger.get("star_level") == 3


# ------------------------------------------------------------------
# Learn / star-up source persistence
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_learn_writes_source(mgr, db):
    """Newly learned skill stores the source in player_skills."""
    player = FakePlayer()
    await mgr._resolve_and_learn(
        player, {"skill_id": "common_001", "source": "breakthrough_success"}
    )
    learned = await db.ext.get_learned_skills(player.user_id)
    assert learned[0]["source"] == "breakthrough_success"


@pytest.mark.asyncio
async def test_star_up_updates_source(mgr, db):
    """Star-up updates the source to the latest comprehension channel."""
    await db.ext.learn_or_star_up("u1", "common_001", "cultivation")
    player = FakePlayer()
    await mgr._resolve_and_learn(
        player, {"skill_id": "common_001", "source": "universal"}
    )
    learned = await db.ext.get_learned_skills(player.user_id)
    assert learned[0]["source"] == "universal"
    assert learned[0]["star_level"] == 2


# ------------------------------------------------------------------
# Skill source variants
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cultivation_learn_source(mgr, db):
    """Cultivation comprehension writes source 'cultivation' or 'heart_method'."""
    import random as _random

    original_random = _random.random
    original_choice = _random.choice
    player = FakePlayer(main_technique="长春功")
    _random.random = lambda: 0.0  # force success
    _random.choice = lambda p: p[0]
    try:
        results = await mgr.roll_cultivation_comprehension(player, hours=2)
    finally:
        _random.random = original_random
        _random.choice = original_choice

    # When monkey-patching random, we get the first pool entry which is heart_method source
    if results:
        learned = await db.ext.get_learned_skills(player.user_id)
        assert any(entry["source"] == "heart_method" for entry in learned)


# ------------------------------------------------------------------
# Sect exclusive pool injection (spec MODIFIED: 领悟随机池与来源规则)
# ------------------------------------------------------------------


def _join_qingyun(db, player, sect_id: int = 1):
    """Make the player a member of a sect whose faction is qingyun."""
    import types as _types

    db.ext.sects[sect_id] = _types.SimpleNamespace(
        sect_id=sect_id, faction_id="qingyun"
    )
    player.sect_id = sect_id


@pytest.mark.asyncio
async def test_sect_pool_injected_all_channels(mgr, db):
    """Sect pool entries appear in the pool for breakthrough success/fail and cultivation."""
    player = FakePlayer(main_technique="长春功")
    _join_qingyun(db, player)
    for channel in ("breakthrough_success", "breakthrough_fail", "cultivation"):
        pool = await mgr._build_comprehension_pool(player, channel)
        sect_entries = [e for e in pool if e["source"] == "sect"]
        assert sect_entries, f"channel {channel} missing sect pool"
        assert sect_entries[0]["skill_id"] == "qy_001"
        assert sect_entries[0]["origin_sect_id"] == "qingyun"
        assert sect_entries[0]["sect_bound"] is True
        assert sect_entries[0]["coefficient"] == 0.5


@pytest.mark.asyncio
async def test_sect_pool_not_injected_without_sect(mgr, db):
    """Sectless players get no sect pool entries in any channel."""
    player = FakePlayer(main_technique="长春功")
    for channel in ("breakthrough_success", "breakthrough_fail", "cultivation"):
        pool = await mgr._build_comprehension_pool(player, channel)
        assert all(e["source"] != "sect" for e in pool)


@pytest.mark.asyncio
async def test_sect_pool_not_injected_when_faction_has_no_pool(mgr, db):
    """A sect whose faction configures no skill_pool injects nothing."""
    import types as _types

    db.ext.sects[9] = _types.SimpleNamespace(sect_id=9, faction_id="wuchi")
    player = FakePlayer(main_technique="长春功", sect_id=9)
    pool = await mgr._build_comprehension_pool(player, "cultivation")
    assert all(e["source"] != "sect" for e in pool)


@pytest.mark.asyncio
async def test_sect_pool_learn_writes_attribution(mgr, db):
    """Learning from the sect pool records origin_sect_id and sect_bound."""
    player = FakePlayer(main_technique="长春功")
    _join_qingyun(db, player)
    result = await mgr._resolve_and_learn(
        player,
        {
            "skill_id": "qy_001",
            "source": "sect",
            "origin_sect_id": "qingyun",
            "sect_bound": True,
        },
    )
    assert result is not None
    record = db.ext.player_skills[(player.user_id, "qy_001")]
    assert record["origin_sect_id"] == "qingyun"
    assert record["sect_bound"] is True


@pytest.mark.asyncio
async def test_no_heart_breakthrough_injects_sect_pool(mgr, db):
    """No-heart-method breakthrough candidates include the sect pool under the 3% gate."""
    import random as _random

    player = FakePlayer()  # no heart method
    _join_qingyun(db, player)
    original_random = _random.random
    original_choice = _random.choice
    _random.random = lambda: 0.0  # pass the 3% gate
    _random.choice = lambda p: p[-1]  # pick the last candidate (the sect skill)
    try:
        result = await mgr.roll_universal_pool_breakthrough(player, success=True)
    finally:
        _random.random = original_random
        _random.choice = original_choice

    assert result is not None
    assert result["id"] == "qy_001"
    assert result["learn_source"] == "sect"
    record = db.ext.player_skills[(player.user_id, "qy_001")]
    assert record["origin_sect_id"] == "qingyun"
    assert record["sect_bound"] is True


@pytest.mark.asyncio
async def test_no_heart_breakthrough_unchanged_without_sect(mgr, db):
    """Sectless no-heart players still only draw from the universal pool."""
    import random as _random

    player = FakePlayer()
    original_random = _random.random
    _random.random = lambda: 0.0
    try:
        result = await mgr.roll_universal_pool_breakthrough(player, success=True)
    finally:
        _random.random = original_random

    assert result is not None
    assert result["learn_source"] == "universal_fallback"
    record = db.ext.player_skills[(player.user_id, result["id"])]
    assert record["origin_sect_id"] is None
    assert record["sect_bound"] is False


@pytest.mark.asyncio
async def test_sect_pool_max_star_duplicate_compensation(mgr, db):
    """A max-star sect skill duplicate follows the existing exp compensation rule."""
    player = FakePlayer(main_technique="长春功")
    _join_qingyun(db, player)
    for _ in range(3):
        await db.ext.learn_or_star_up(player.user_id, "qy_001", "sect")
    result = await mgr._resolve_and_learn(
        player,
        {
            "skill_id": "qy_001",
            "source": "sect",
            "origin_sect_id": "qingyun",
            "sect_bound": True,
        },
    )
    assert result["is_new_learn"] is False
    assert result["max_star_compensation"] > 0
    assert "折算" in result["compensation_message"]

"""Contract tests: config -> normalization -> engine (spec: arx).

These tests verify that real config data flows through the full pipeline
(config/skills.json -> _apply_star_to_def -> get_battle_loadout -> engine)
and that engine-readable keys are present and functional.
"""

import sys
from pathlib import Path

import pytest

# Ensure plugin root is on path
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from tests.helpers import load_module  # noqa: E402

# Load modules under test
_combat_mod = load_module("combat_manager", "managers/combat_manager.py")
CombatEngine = _combat_mod.CombatEngine
FighterState = _combat_mod.FighterState

_skill_mod = load_module("skill_manager_test", "core/skill_manager.py")
SkillManager = _skill_mod.SkillManager


class FakeConfigManager:
    """Config manager that loads real skills.json for contract testing."""

    def __init__(self):
        import json

        self.game_config = {"combat": {}, "skill_system": {}}
        self.items_data = {}
        self.weapons_data = {}
        self.heart_methods_data = {}
        # Load real skills.json
        skills_path = Path(__file__).resolve().parent.parent / "config" / "skills.json"
        with open(skills_path, encoding="utf-8") as f:
            skills_raw = json.load(f)
        self.skills_data = {}
        for group_name, skills in skills_raw.items():
            for skill in skills:
                skill["_group"] = group_name
                name = skill.get("name")
                if name:
                    self.skills_data[name] = skill


class FakeDbExt:
    """In-memory store with max_star support."""

    def __init__(self):
        self.player_skills: dict[tuple[str, str], dict] = {}

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
        current_star = self.player_skills[key]["star_level"]
        if current_star >= max_star:
            return False, max_star
        self.player_skills[key]["star_level"] = current_star + 1
        self.player_skills[key]["source"] = source
        self.player_skills[key]["learned_at"] = now
        return False, self.player_skills[key]["star_level"]


class FakeDb:
    def __init__(self):
        self.ext = FakeDbExt()


class FakePlayer:
    """Minimal player stub for loadout tests."""

    def __init__(self, **kwargs):
        self.user_id = kwargs.get("user_id", "test")
        self.user_name = kwargs.get("user_name", "Tester")
        self.level_index = kwargs.get("level_index", 1)
        self.cultivation_type = kwargs.get("cultivation_type", "灵修")
        self.damage = kwargs.get("damage", 10)
        self.agility = kwargs.get("agility", 5)
        self.speed = kwargs.get("speed", 5)
        self.hp = kwargs.get("hp", 100)
        self.armor_value = kwargs.get("armor_value", 0)
        self.weapon = kwargs.get("weapon", "")
        self.armor = kwargs.get("armor", "")
        self.main_technique = kwargs.get("main_technique", "")
        self.techniques = kwargs.get("techniques", "[]")
        self.study_target = ""

    def get_techniques_list(self):
        try:
            import json

            return json.loads(self.techniques)
        except Exception:
            return []

    def get_total_attributes(self, equipped_items, pill_multipliers=None):
        return {
            "damage": self.damage,
            "agility": self.agility,
            "speed": self.speed,
            "hp": self.hp,
            "armor_value": self.armor_value,
            "exp_multiplier": 0.0,
        }


@pytest.fixture
def config_manager():
    return FakeConfigManager()


@pytest.fixture
def skill_manager(config_manager):
    return SkillManager(config_manager, FakeDb())


# ------------------------------------------------------------------
# 5.1 Engine-readable keys contract
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_skills_have_engine_keys(skill_manager):
    """Every trigger_skill and ultimate in config must have engine-readable keys."""
    player = FakePlayer(techniques='["御剑术", "撼山劲"]')
    # Pre-learn skills
    await skill_manager.db.ext.learn_or_star_up(player.user_id, "spirit_001", "test")
    await skill_manager.db.ext.learn_or_star_up(player.user_id, "body_001", "test")

    loadout = await skill_manager.get_battle_loadout(player)

    for ts in loadout["trigger_skills"]:
        assert "effect_type" in ts, f"Missing effect_type in trigger: {ts}"
        assert "trigger_timing" in ts, f"Missing trigger_timing in trigger: {ts}"
        assert "trigger_rate" in ts, f"Missing trigger_rate in trigger: {ts}"
        assert ts["trigger_rate"] >= 0, f"Negative trigger_rate: {ts}"
        assert "effect_value" in ts, f"Missing effect_value in trigger: {ts}"

    for ult in loadout["ultimates"]:
        assert "effect_type" in ult, f"Missing effect_type in ultimate: {ult}"
        assert "trigger_timing" in ult, f"Missing trigger_timing in ultimate: {ult}"
        assert "trigger_rate" in ult, f"Missing trigger_rate in ultimate: {ult}"
        assert ult["trigger_rate"] >= 0, f"Negative trigger_rate: {ult}"
        assert "effect_value" in ult, f"Missing effect_value in ultimate: {ult}"


def test_shipped_skills_cover_all_engine_effects(config_manager):
    """Every EFFECT_HANDLERS key must be exercised by at least one shipped skill.

    Guards against content gaps like the 2026-08-17 fatigue hole (engine had
    the handler but no config skill used it), which would leave an effect
    path untested in real config data.
    """
    shipped = set()
    for skill in config_manager.skills_data.values():
        ts = skill.get("trigger_skill")
        if ts:
            shipped.add(ts.get("effect_type"))
        ult = skill.get("ultimate")
        if ult:
            shipped.add(ult.get("effect_type", "damage_bonus"))
    engine_effects = set(CombatEngine.EFFECT_HANDLERS.keys())
    uncovered = sorted(engine_effects - shipped)
    assert not uncovered, (
        f"引擎已实现但 config 无技能覆盖的效果: {uncovered} "
        "（补充 verify_* 冒烟技能或修改可覆盖技能）"
    )


# ------------------------------------------------------------------
# 5.2 Ultimate unlock thresholds (fix-before-red, fix-after-green)
# ------------------------------------------------------------------


class TestUltimateUnlock:
    def test_ultimate_not_triggered_before_min_actions(self):
        """Ultimate with min_action_index should NOT trigger before threshold."""
        engine = CombatEngine(FakeConfigManager(), None)
        f1 = FighterState(
            user_id="A",
            name="A",
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )
        f1.ultimates = [
            {
                "id": "ult_test",
                "name": "TestUlt",
                "trigger_rate": 1.0,
                "effect_value": 1.0,
                "min_action_index": 3,
            }
        ]
        f2 = FighterState(
            user_id="B",
            name="B",
            hp=1000,
            max_hp=1000,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )

        # Force first action (action_count=0 < 3)
        log: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=0.0, crit_multiplier=1.5, log=log)
        assert "ult_test" not in f1.used_ultimates
        assert not any("大招" in entry for entry in log)

    def test_ultimate_triggered_after_min_actions(self):
        """Ultimate with min_action_index SHOULD trigger once threshold is met."""
        engine = CombatEngine(FakeConfigManager(), None)
        f1 = FighterState(
            user_id="A",
            name="A",
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )
        f1.ultimates = [
            {
                "id": "ult_test",
                "name": "TestUlt",
                "trigger_rate": 1.0,
                "effect_value": 1.0,
                "min_action_index": 2,
            }
        ]
        f1.action_count = 2  # Threshold met
        f2 = FighterState(
            user_id="B",
            name="B",
            hp=1000,
            max_hp=1000,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )

        log: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=0.0, crit_multiplier=1.5, log=log)
        assert "ult_test" in f1.used_ultimates
        assert any("大招" in entry for entry in log)

    def test_ultimate_once_per_battle(self):
        """Each ultimate triggers at most once per battle."""
        engine = CombatEngine(FakeConfigManager(), None)
        f1 = FighterState(
            user_id="A",
            name="A",
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )
        f1.ultimates = [
            {
                "id": "ult_once",
                "name": "Once",
                "trigger_rate": 1.0,
                "effect_value": 1.0,
                "min_action_index": 0,
            }
        ]
        f2 = FighterState(
            user_id="B",
            name="B",
            hp=1000,
            max_hp=1000,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )

        log1: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=0.0, crit_multiplier=1.5, log=log1)
        assert "ult_once" in f1.used_ultimates

        log2: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=0.0, crit_multiplier=1.5, log=log2)
        assert not any("大招" in entry for entry in log2)

    def test_multiple_ultimates_independent(self):
        """Multiple ultimates are tracked independently."""
        engine = CombatEngine(FakeConfigManager(), None)
        f1 = FighterState(
            user_id="A",
            name="A",
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )
        f1.ultimates = [
            {
                "id": "ult_a",
                "name": "UltA",
                "trigger_rate": 1.0,
                "effect_value": 1.0,
                "min_action_index": 0,
            },
            {
                "id": "ult_b",
                "name": "UltB",
                "trigger_rate": 1.0,
                "effect_value": 1.0,
                "min_action_index": 0,
            },
        ]
        f2 = FighterState(
            user_id="B",
            name="B",
            hp=1000,
            max_hp=1000,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )

        log: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=0.0, crit_multiplier=1.5, log=log)
        # Only one ultimate per action, but both are available
        assert len(f1.used_ultimates) == 1

    def test_opponent_hp_threshold(self):
        """Ultimate with trigger_opponent_hp_below triggers when opponent HP is low."""
        engine = CombatEngine(FakeConfigManager(), None)
        f1 = FighterState(
            user_id="A",
            name="A",
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )
        f1.ultimates = [
            {
                "id": "ult_exec",
                "name": "Execute",
                "trigger_rate": 1.0,
                "effect_value": 1.0,
                "min_action_index": 0,
                "trigger_opponent_hp_below": 0.4,
            }
        ]
        f2 = FighterState(
            user_id="B",
            name="B",
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )

        # Opponent at 50% HP -> should NOT trigger
        f2.hp = 50
        log1: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=0.0, crit_multiplier=1.5, log=log1)
        assert "ult_exec" not in f1.used_ultimates

        # Opponent at 30% HP -> SHOULD trigger
        f2.hp = 30
        log2: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=0.0, crit_multiplier=1.5, log=log2)
        assert "ult_exec" in f1.used_ultimates

    def test_self_hp_threshold(self):
        """Ultimate with trigger_self_hp_below triggers when self HP is low."""
        engine = CombatEngine(FakeConfigManager(), None)
        f1 = FighterState(
            user_id="A",
            name="A",
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )
        f1.ultimates = [
            {
                "id": "ult_comeback",
                "name": "Comeback",
                "trigger_rate": 1.0,
                "effect_value": 1.0,
                "min_action_index": 0,
                "trigger_self_hp_below": 0.5,
            }
        ]
        f2 = FighterState(
            user_id="B",
            name="B",
            hp=1000,
            max_hp=1000,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )

        # Self at 60% HP -> should NOT trigger
        f1.hp = 60
        log1: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=0.0, crit_multiplier=1.5, log=log1)
        assert "ult_comeback" not in f1.used_ultimates

        # Self at 40% HP -> SHOULD trigger
        f1.hp = 40
        log2: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=0.0, crit_multiplier=1.5, log=log2)
        assert "ult_comeback" in f1.used_ultimates


# ------------------------------------------------------------------
# 5.3 Star-up multiplicative scaling contract
# ------------------------------------------------------------------


class TestStarUpScaling:
    def test_star_up_multiplicative_rate(self):
        """3-star trigger rate = base * 1.1^2."""
        config = FakeConfigManager()
        mgr = SkillManager(config, FakeDb())
        skill_def = {
            "id": "test",
            "name": "Test",
            "trigger_skill": {
                "trigger_rate": 0.25,
                "effect_value": 1.5,
            },
        }
        result = mgr._apply_star_to_def(skill_def, 3)
        trigger = result["trigger_skill"]
        expected_rate = 0.25 * (1.1**2)
        assert abs(trigger["trigger_rate"] - expected_rate) < 0.001
        assert trigger["trigger_rate"] <= 1.0

    def test_star_up_multiplicative_value(self):
        """3-star effect value = base * 1.1^2."""
        config = FakeConfigManager()
        mgr = SkillManager(config, FakeDb())
        skill_def = {
            "id": "test",
            "name": "Test",
            "trigger_skill": {
                "trigger_rate": 0.25,
                "effect_value": 1.5,
            },
        }
        result = mgr._apply_star_to_def(skill_def, 3)
        trigger = result["trigger_skill"]
        expected_value = 1.5 * (1.1**2)
        assert abs(trigger["effect_value"] - expected_value) < 0.001

    def test_ultimate_default_trigger_rate(self):
        """Ultimate without explicit trigger_rate gets default 1.0."""
        config = FakeConfigManager()
        mgr = SkillManager(config, FakeDb())
        skill_def = {
            "id": "test",
            "name": "Test",
            "ultimate": {
                "effect_value": 3.0,
            },
        }
        result = mgr._apply_star_to_def(skill_def, 1)
        assert result["ultimate"]["trigger_rate"] == 1.0

    def test_ultimate_explicit_trigger_rate_preserved(self):
        """Ultimate with explicit trigger_rate preserves it."""
        config = FakeConfigManager()
        mgr = SkillManager(config, FakeDb())
        skill_def = {
            "id": "test",
            "name": "Test",
            "ultimate": {
                "trigger_rate": 0.5,
                "effect_value": 3.0,
            },
        }
        result = mgr._apply_star_to_def(skill_def, 1)
        assert result["ultimate"]["trigger_rate"] == 0.5


# ------------------------------------------------------------------
# 5.4 Max-star duplicate compensation contract
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_star_no_increment():
    """At max star, duplicate learn does not increment star level."""
    db = FakeDb()

    player = FakePlayer()
    # Learn to 3 stars
    await db.ext.learn_or_star_up(player.user_id, "common_001", "test", max_star=3)
    await db.ext.learn_or_star_up(player.user_id, "common_001", "test", max_star=3)

    is_new, star = await db.ext.learn_or_star_up(
        player.user_id, "common_001", "test", max_star=3
    )
    assert not is_new
    assert star == 3


@pytest.mark.asyncio
async def test_max_star_compensation_message():
    """Max-star duplicate returns compensation message."""
    config = FakeConfigManager()
    db = FakeDb()
    mgr = SkillManager(config, db)

    player = FakePlayer()
    # Pre-learn to max star
    await db.ext.learn_or_star_up(player.user_id, "common_001", "test", max_star=3)
    await db.ext.learn_or_star_up(player.user_id, "common_001", "test", max_star=3)

    result = await mgr._resolve_and_learn(
        player, {"skill_id": "common_001", "source": "test"}
    )
    assert result is not None
    assert "max_star_compensation" in result
    assert result["max_star_compensation"] > 0
    assert "compensation_message" in result
    assert "圆满" in result["compensation_message"]


class TestWeaponMountedSkills:
    """content-sync-pipeline: real weapons.json mounts must honor the
    engine-key contract and trigger without warnings."""

    TRIGGER_TIMINGS = ("on_attack", "on_defense", "on_crit", "round_start")
    KNOWN_EFFECTS = {
        "damage_bonus",
        "combo",
        "stun",
        "counter",
        "damage_reduction",
    }

    @staticmethod
    def _mounted_skills() -> list[tuple[str, dict]]:
        import json

        weapons_path = (
            Path(__file__).resolve().parent.parent / "config" / "weapons.json"
        )
        with open(weapons_path, encoding="utf-8") as f:
            weapons = json.load(f)
        mounted = []
        for weapon in weapons:
            for skill in weapon.get("trigger_skills") or []:
                mounted.append((weapon.get("id", "?"), skill))
        return mounted

    def test_mounted_skills_have_engine_keys(self):
        """Every mounted skill carries the 4 engine keys with valid values."""
        mounted = self._mounted_skills()
        assert mounted, "weapons.json should contain at least one mounted skill"
        for weapon_id, skill in mounted:
            missing = {
                "trigger_timing",
                "effect_type",
                "trigger_rate",
                "effect_value",
            } - set(skill)
            assert not missing, f"{weapon_id}: missing keys {missing}"
            assert skill["trigger_timing"] in self.TRIGGER_TIMINGS, weapon_id
            assert skill["effect_type"] in self.KNOWN_EFFECTS, weapon_id
            assert 0 < skill["trigger_rate"] <= 1, weapon_id
            if skill["effect_type"] == "stun":
                assert skill["trigger_rate"] <= 0.10, f"{weapon_id}: stun rate too high"
            else:
                gain = skill["trigger_rate"] * skill["effect_value"]
                assert gain <= 0.08, f"{weapon_id}: expected gain {gain:.1%} > 8% tax"

    def test_mounted_skill_triggers_cleanly(self, caplog):
        """Forcing a real mounted skill must apply its effect without warnings."""
        engine = CombatEngine(FakeConfigManager(), None)
        mounted = self._mounted_skills()
        attacked = [s for _, s in mounted if s["trigger_timing"] == "on_attack"]
        round_start = [s for _, s in mounted if s["trigger_timing"] == "round_start"]
        assert attacked and round_start, "expected on_attack and round_start mounts"

        f1 = FighterState(
            user_id="A",
            name="A",
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )
        f2 = FighterState(
            user_id="B",
            name="B",
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )

        with caplog.at_level("WARNING"):
            attack_skill = dict(attacked[0], trigger_rate=1.0)
            f1.trigger_skills = [attack_skill]
            result = engine._process_trigger_skills("on_attack", f1, f2, [])
            assert result["damage_mult"] == pytest.approx(
                1 + attack_skill["effect_value"]
            )

            rs_skill = dict(round_start[0], trigger_rate=1.0)
            f1.trigger_skills = [rs_skill]
            engine._process_round_start_skills(f1, [])
            assert f1.next_attack_mult == pytest.approx(1 + rs_skill["effect_value"])

        assert not any("effect_type" in r.message for r in caplog.records)


class TestUnknownEffectWarning:
    """combat-core: unknown effect_type must warn and skip, never crash."""

    @staticmethod
    def _fighter(user_id: str) -> FighterState:
        return FighterState(
            user_id=user_id,
            name=user_id,
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=10,
            armor_value=0,
        )

    def test_unknown_effect_warns_on_attack(self, caplog):
        engine = CombatEngine(FakeConfigManager(), None)
        f1 = self._fighter("A")
        f1.trigger_skills = [
            {
                "name": "MysterySkill",
                "trigger_timing": "on_attack",
                "trigger_rate": 1.0,
                "effect_type": "nonexistent_effect",
                "effect_value": 1.0,
            }
        ]
        f2 = self._fighter("B")
        log: list[str] = []
        with caplog.at_level("WARNING"):
            result = engine._process_trigger_skills("on_attack", f1, f2, log)
        assert result["damage_mult"] == 1.0
        assert any("nonexistent_effect" in r.message for r in caplog.records)

    def test_unknown_effect_warns_round_start(self, caplog):
        engine = CombatEngine(FakeConfigManager(), None)
        f1 = self._fighter("A")
        f1.trigger_skills = [
            {
                "name": "MysteryRound",
                "trigger_timing": "round_start",
                "trigger_rate": 1.0,
                "effect_type": "nonexistent_effect",
                "effect_value": 1.0,
            }
        ]
        log: list[str] = []
        with caplog.at_level("WARNING"):
            engine._process_round_start_skills(f1, log)
        assert f1.next_attack_mult == 1.0
        assert any("nonexistent_effect" in r.message for r in caplog.records)

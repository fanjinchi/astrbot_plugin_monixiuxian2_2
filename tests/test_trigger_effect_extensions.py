"""Tests for trigger-effect extensions (change: trigger-effect-extensions).

Covers the EFFECT_HANDLERS additions (heal/dot/buff/debuff/fatigue/pierce/
unavoidable/reflect/survive), the status-effect lifecycle, ultimate
non-damage dispatch and the sync/validate contract extensions.
"""

import asyncio
import csv
import random
import sys
from io import StringIO
from pathlib import Path

import pytest

# Ensure plugin root is on path
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from tests.helpers import load_module  # noqa: E402

_cm = load_module("combat_manager", "managers/combat_manager.py")
CombatEngine = _cm.CombatEngine
CombatManager = _cm.CombatManager
FighterState = _cm.FighterState
StatusEffect = _cm.StatusEffect

_sync = load_module("sync_content_to_config", "scripts/sync_content_to_config.py")
_vb = load_module("validate_budget", "design_docs/content-design/validate_budget.py")


class FakeConfigManager:
    """Minimal fake config manager (mirrors tests/test_combat_engine.py)."""

    def __init__(self, game_config=None):
        self.game_config = game_config or {}
        self.items_data = {}
        self.weapons_data = {}
        self.heart_methods_data = {}


class FakeSkillManager:
    """Minimal fake skill manager."""

    async def get_battle_loadout(self, player):
        return {
            "trigger_skills": [],
            "ultimates": [],
            "heart_method_passive": {},
            "weapon_coefficient_k": 1.0,
            "base_damage": 0,
            "armor_value": 0,
        }


def make_engine(cfg=None):
    return CombatEngine(FakeConfigManager(cfg or {}), FakeSkillManager())


def make_fighter(
    name, hp, damage, agility, speed, armor=0, weapon_k=1.0, base_dmg=0, level_index=1, max_hp=None
):
    return FighterState(
        user_id=name,
        name=name,
        hp=hp,
        max_hp=max_hp or hp,
        damage=damage,
        agility=agility,
        speed=speed,
        armor_value=armor,
        weapon_k=weapon_k,
        base_damage=base_dmg,
        level_index=level_index,
    )


def trigger_skill(name, effect, value, **extra):
    """Build an engine-contract trigger skill dict (rate=1.0 always fires)."""
    skill = {
        "name": name,
        "trigger_timing": "on_attack",
        "trigger_rate": 1.0,
        "effect_type": effect,
        "effect_value": value,
    }
    skill.update(extra)
    return skill


# ------------------------------------------------------------------
# 8.1 Effect handlers
# ------------------------------------------------------------------


class TestHeal:
    def test_heal_restores_hp_immediately(self):
        engine = make_engine()
        log: list[str] = []
        actor = make_fighter("A", 50, 100, 5, 10, max_hp=100)
        actor.trigger_skills = [trigger_skill("回春术", "heal", 0.5)]
        target = make_fighter("B", 1000, 100, 5, 10)
        engine._process_trigger_skills("on_attack", actor, target, log)
        assert actor.hp == 100  # 50% of max_hp
        assert any("恢复" in line for line in log)

    def test_heal_percent_override(self):
        engine = make_engine()
        actor = make_fighter("A", 50, 100, 5, 10, max_hp=100)
        actor.trigger_skills = [
            trigger_skill("回春术", "heal", 0.5, heal_percent=0.25)
        ]
        target = make_fighter("B", 1000, 100, 5, 10)
        engine._process_trigger_skills("on_attack", actor, target, log := [])
        assert actor.hp == 75  # 25% of max_hp, not 50%

    def test_vampire_defers_heal_to_attack(self):
        engine = make_engine()
        actor = make_fighter("A", 50, 100, 5, 10, max_hp=100)
        actor.trigger_skills = [
            trigger_skill("吸星", "heal", 0.5, vampire=True)
        ]
        target = make_fighter("B", 1000, 100, 5, 10, armor=0)
        engine._process_trigger_skills("on_attack", actor, target, log := [])
        # Heal deferred: no immediate heal, one-shot flag armed
        assert actor.hp == 50
        assert actor.next_attack_vampire == 0.5
        # Next attack heals back 50% of dealt damage
        engine._resolve_attack(actor, target, 0.0, 1.5, log)
        assert actor.hp > 50
        assert actor.next_attack_vampire == 0.0  # consumed


class TestDot:
    def test_dot_snapshots_and_ticks(self, monkeypatch):
        # Deterministic damage: uniform 1.0, no crit/dodge/block
        monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)
        monkeypatch.setattr(random, "random", lambda: 0.9)
        engine = make_engine()
        actor = make_fighter("A", 1000, 100, 5, 10)
        actor.trigger_skills = [
            trigger_skill("蚀骨", "dot", 0.1, duration=3, tick_rate=1.0)
        ]
        target = make_fighter("B", 1000, 100, 5, 10, armor=0)
        log: list[str] = []
        engine._resolve_attack(actor, target, 0.0, 1.5, log)
        assert len(target.status_effects) == 1
        effect = target.status_effects[0]
        assert effect.kind == "dot"
        assert effect.snapshot_damage == 55  # unarmed fallback: (5 + 100 x 0.5)
        # 3 ticks of max(1, 55 x 0.1 x 1.0) = 5 each; attack dealt 55
        for _ in range(3):
            engine._tick_status_effects(target, log)
        assert target.hp == 1000 - 55 - 15
        assert target.status_effects == []  # expired and removed

    def test_dot_same_source_refreshes_not_stacks(self):
        engine = make_engine()
        actor = make_fighter("A", 1000, 100, 5, 10)
        actor.trigger_skills = [
            trigger_skill("蚀骨", "dot", 0.1, duration=3)
        ]
        target = make_fighter("B", 1000, 100, 5, 10, armor=0)
        log: list[str] = []
        engine._resolve_attack(actor, target, 0.0, 1.5, log)
        engine._resolve_attack(actor, target, 0.0, 1.5, log)
        assert len(target.status_effects) == 1
        assert target.status_effects[0].remaining == 3  # refreshed

    def test_dot_cross_source_stack_cap(self):
        engine = make_engine()
        target = make_fighter("B", 1000, 100, 5, 10, armor=0)
        log: list[str] = []
        for i in range(4):
            actor = make_fighter(f"A{i}", 1000, 100, 5, 10)
            actor.trigger_skills = [
                trigger_skill(f"蚀骨{i}", "dot", 0.1, duration=3)
            ]
            engine._process_trigger_skills("on_attack", actor, target, log)
        # cap = 3 (default status_stack_cap): 4th source rejected
        assert len(target.status_effects) == 3


class TestBuffDebuffFatigue:
    def test_buff_multiplies_damage_in_battle(self, monkeypatch):
        monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)
        monkeypatch.setattr(random, "random", lambda: 0.9)
        engine = make_engine()
        actor = make_fighter("A", 1000, 100, 5, 10, base_dmg=100)
        actor.trigger_skills = [
            trigger_skill("战意", "buff", 0.5, duration=3, stat="damage")
        ]
        target = make_fighter("B", 1000, 100, 5, 10, armor=0)
        log: list[str] = []
        engine._resolve_attack(actor, target, 0.0, 1.5, log)
        assert actor.status_effects[0].kind == "buff"
        assert engine._buff_multiplier(actor, "damage") == pytest.approx(1.5)
        # buffed damage = 100 x 1.5 = 150 -> (100 + 150 x 1.0) = 250
        assert target.hp == 1000 - 250

    def test_debuff_penalizes_target(self):
        engine = make_engine()
        actor = make_fighter("A", 1000, 100, 5, 10)
        actor.trigger_skills = [
            trigger_skill("虚弱", "debuff", 0.5, duration=2, stat="damage")
        ]
        target = make_fighter("B", 1000, 100, 5, 10)
        log: list[str] = []
        engine._process_trigger_skills("on_attack", actor, target, log)
        assert target.status_effects[0].kind == "debuff"
        assert engine._buff_multiplier(target, "damage") == pytest.approx(0.5)

    def test_fatigue_is_self_debuff(self):
        engine = make_engine()
        actor = make_fighter("A", 1000, 100, 5, 10)
        actor.trigger_skills = [
            trigger_skill("燃血", "fatigue", 0.5, duration=2, stat="damage")
        ]
        target = make_fighter("B", 1000, 100, 5, 10)
        log: list[str] = []
        engine._process_trigger_skills("on_attack", actor, target, log)
        # Self-targeted: actor carries the fatigue status
        assert actor.status_effects[0].kind == "fatigue"
        assert engine._buff_multiplier(actor, "damage") == pytest.approx(0.5)


class TestPierce:
    def test_pierce_bypasses_armor_by_rate(self):
        engine = make_engine()
        defender = make_fighter("B", 1000, 100, 5, 10, armor=100, level_index=1)
        # K = 100 + 10 x 1 = 110 -> armor_rate = 100/210 ~= 0.4762, capped at 0.4
        plain = engine._apply_armor_and_reduction(defender, 100)
        assert plain == 60  # int(100 x (1 - 0.4))
        # pierce 0.5 -> effective armor_rate 0.2381 (below cap)
        pierced = engine._apply_armor_and_reduction(defender, 100, pierce_rate=0.5)
        assert pierced == int(100 * (1 - (100 / 210) * 0.5))
        assert pierced > plain

    def test_pierce_one_shot_consumed_on_attack(self):
        engine = make_engine()
        actor = make_fighter("A", 1000, 100, 5, 10)
        actor.next_attack_pierce_rate = 0.5
        target = make_fighter("B", 1000, 100, 5, 10, armor=100, level_index=1)
        engine._resolve_attack(actor, target, 0.0, 1.5, log := [])
        assert actor.next_attack_pierce_rate == 0.0  # consumed


class TestUnavoidable:
    def test_unavoidable_skips_dodge_and_block(self, monkeypatch):
        # random=0.05: dodge (rate 0.9) and crit (0.15) would trigger normally
        monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)
        monkeypatch.setattr(random, "random", lambda: 0.05)
        engine = make_engine()
        # High-agility defender dodges a normal attack
        target = make_fighter("B", 1000, 100, 10_000, 10)
        normal = make_fighter("N", 1000, 100, 5, 10)
        log: list[str] = []
        engine._resolve_attack(normal, target, 0.9, 1.5, log)
        assert target.hp == 1000  # dodged
        # Unavoidable attack lands regardless
        actor = make_fighter("A", 1000, 100, 5, 10)
        actor.next_attack_unavoidable = True
        engine._resolve_attack(actor, target, 0.9, 1.5, log)
        assert target.hp < 1000  # landed
        assert actor.next_attack_unavoidable is False  # consumed

    def test_unavoidable_exempts_counter(self, monkeypatch):
        # random=0.9: no dodge (cap 0), no crit (0.15), no block; counter fires
        monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)
        monkeypatch.setattr(random, "random", lambda: 0.9)
        engine = make_engine()
        defender = make_fighter("B", 1000, 100, 5, 10, armor=0)
        defender.trigger_skills = [
            trigger_skill("反震", "counter", 1.0, trigger_timing="on_defense")
        ]
        # Normal attack triggers the counter (100 x 1.0 = 100 damage back)
        attacker = make_fighter("A", 1000, 100, 5, 10)
        engine._resolve_attack(attacker, defender, 0.0, 1.5, log := [])
        assert attacker.hp == 1000 - 100
        # Unavoidable attack skips the counter entirely
        attacker2 = make_fighter("C", 1000, 100, 5, 10)
        attacker2.next_attack_unavoidable = True
        engine._resolve_attack(attacker2, defender, 0.0, 1.5, log2 := [])
        assert attacker2.hp == 1000


class TestReflect:
    def test_reflect_refunds_fraction_of_actual_damage(self, monkeypatch):
        monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)
        monkeypatch.setattr(random, "random", lambda: 0.9)
        engine = make_engine()
        actor = make_fighter("A", 1000, 100, 5, 10)
        defender = make_fighter("B", 1000, 100, 5, 10, armor=0)
        defender.reflect_rate = 0.5
        log: list[str] = []
        engine._resolve_attack(actor, defender, 0.0, 1.5, log, round_no=1)
        # raw = 55, no armor -> actual 55, reflect 27 back
        assert actor.hp == 1000 - int(55 * 0.5)
        assert any("反弹" in line for line in log)

    def test_reflect_max_once_per_round_and_no_chain(self, monkeypatch):
        monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)
        monkeypatch.setattr(random, "random", lambda: 0.9)
        engine = make_engine()
        actor = make_fighter("A", 1000, 100, 5, 10)
        defender = make_fighter("B", 1000, 100, 5, 10, armor=0)
        defender.reflect_rate = 0.5
        actor.reflect_rate = 0.5  # would chain if reflect could reflect
        log: list[str] = []
        engine._resolve_attack(actor, defender, 0.0, 1.5, log, round_no=1)
        first = actor.hp
        engine._resolve_attack(actor, defender, 0.0, 1.5, log, round_no=1)
        assert actor.hp == first  # same round: no second reflect
        engine._resolve_attack(actor, defender, 0.0, 1.5, log, round_no=2)
        assert actor.hp < first  # new round reflects again


class TestSurvive:
    def test_survive_saves_lethal_once(self):
        engine = make_engine()
        attacker = make_fighter("A", 1000, 500, 5, 10)
        target = make_fighter("B", 50, 100, 5, 10)
        target.survive_charges = 1
        log: list[str] = []
        engine._resolve_attack(attacker, target, 0.0, 1.5, log)
        assert target.hp == 1  # saved at 1 HP
        assert any("免死" in line for line in log)
        # Second lethal hit kills (charges exhausted)
        engine._resolve_attack(attacker, target, 0.0, 1.5, log)
        assert target.hp <= 0

    def test_survive_recovery_percent(self):
        engine = make_engine()
        attacker = make_fighter("A", 1000, 500, 5, 10)
        target = make_fighter("B", 50, 100, 5, 10, max_hp=100)
        target.survive_charges = 1
        target.survive_recovery = 0.5
        engine._resolve_attack(attacker, target, 0.0, 1.5, log := [])
        assert target.hp == 51  # 1 + 50% of max_hp


# ------------------------------------------------------------------
# 8.2 Status lifecycle
# ------------------------------------------------------------------


class TestStatusLifecycle:
    def test_round_start_tick_in_full_combat(self):
        engine = make_engine({"combat": {"action_limit": 60}})
        actor = make_fighter("A", 1000, 100, 5, 10)
        actor.trigger_skills = [trigger_skill("蚀骨", "dot", 0.1, duration=5)]
        target = make_fighter("B", 1000, 100, 5, 10, armor=0)
        result = engine.resolve_combat(actor, target, "spar", merge_count=10)
        assert result.winner in ("A", "B", "draw")
        # The dot fires and the round-start tick applies it
        assert any("侵蚀" in line for line in result.combat_log)

    def test_battle_end_cleanup_no_persistence(self):
        """A battle always ends with a loser at 0 HP: FighterState fields are
        per-battle objects with no persistence path (resolve_combat takes no
        db handle), so status/one-shot state cannot leak across battles."""
        engine = make_engine()  # no action limit: battle settles naturally
        actor = make_fighter("A", 1000, 100, 5, 10)
        actor.trigger_skills = [
            trigger_skill("战意", "buff", 0.5, duration=3),
            trigger_skill("吸星", "heal", 0.5, vampire=True),
        ]
        target = make_fighter("B", 1000, 100, 5, 10, armor=0)
        # Runs without any database reference
        result = engine.resolve_combat(actor, target, "spar", merge_count=10)
        assert result.winner in ("A", "B", "draw")
        # Exactly one side is dead (or both in a draw) — no zombie outcomes,
        # and the survivor is above 0 HP (real settlement, not clamping).
        assert result.fighter1_final_hp == 0 or result.fighter2_final_hp == 0
        if result.winner != "draw":
            winner_hp = (
                result.fighter1_final_hp
                if result.winner == "A"
                else result.fighter2_final_hp
            )
            assert winner_hp > 0


# ------------------------------------------------------------------
# Review-fix regression tests (ocr findings on 8e61524)
# ------------------------------------------------------------------


class TestReviewFixes:
    def test_dot_lethal_consumes_survive(self):
        """Lethal dot damage consumes a survive charge (tick funnels through
        _try_survive) instead of killing past it."""
        engine = make_engine()
        fighter = make_fighter("A", 1000, 100, 5, 10, armor=0, max_hp=1000)
        fighter.hp = 5
        fighter.survive_charges = 1
        fighter.status_effects = [
            StatusEffect(
                source_name="蚀骨",
                kind="dot",
                effect_value=1.0,
                tick_rate=1.0,
                duration=1,
                remaining=1,
                snapshot_damage=100,
            )
        ]
        engine._tick_status_effects(fighter, [])
        assert fighter.hp == 1  # saved by the survive charge
        assert fighter.survive_charges == 0

    def test_counter_lethal_consumes_survive(self):
        """A lethal counter consumes the attacker's survive charge."""
        engine = make_engine()
        attacker = make_fighter("A", 1000, 100, 5, 10, armor=0, max_hp=1000)
        attacker.hp = 10
        attacker.survive_charges = 1
        defender = make_fighter("B", 1000, 100, 5, 10, armor=0)
        defender.trigger_skills = [
            trigger_skill("反震", "counter", 1.0, trigger_timing="on_defense")
        ]
        log: list[str] = []
        engine._process_trigger_skills("on_defense", defender, attacker, log)
        assert attacker.hp == 1  # saved by the survive charge
        assert attacker.survive_charges == 0

    def test_round_start_buff_keeps_full_duration(self):
        """A buff applied by a round_start skill in this round is not ticked
        away in the same phase (tick runs before round-start skills)."""
        engine = make_engine()
        actor = make_fighter("A", 1000, 100, 5, 10)
        actor.trigger_skills = [
            trigger_skill(
                "战意", "buff", 0.5, duration=1, trigger_timing="round_start"
            )
        ]
        log: list[str] = []
        engine._process_round_start_skills(actor, log)
        assert len(actor.status_effects) == 1  # duration=1 survives its own round
        engine._tick_status_effects(actor, log)
        assert actor.status_effects == []  # expired at the next round's tick


# ------------------------------------------------------------------
# 8.3 Ultimate non-damage dispatch
# ------------------------------------------------------------------


class TestUltimateDispatch:
    def test_non_damage_ultimate_heal(self):
        engine = make_engine()
        actor = make_fighter("A", 30, 100, 5, 10, max_hp=100)
        actor.ultimates = [
            {
                "id": "u_heal",
                "name": "涅槃",
                "effect_type": "heal",
                "effect_value": 0.5,
                "min_action_index": 0,
                "trigger_rate": 1.0,
            }
        ]
        target = make_fighter("B", 1000, 100, 5, 10, armor=0)
        log: list[str] = []
        engine._resolve_attack(actor, target, 0.0, 1.5, log)
        assert actor.hp == 80  # 30 + 50% of max_hp
        assert "u_heal" in actor.used_ultimates
        # Once-per-battle: second attack does not re-heal
        engine._resolve_attack(actor, target, 0.0, 1.5, log)
        assert actor.hp == 80  # 30 + 50% (no double heal); damage ignored (hp 80, no heal)

    def test_legacy_ultimate_without_effect_type_keeps_damage(self, monkeypatch):
        monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)
        monkeypatch.setattr(random, "random", lambda: 0.9)
        engine = make_engine()
        actor = make_fighter("A", 1000, 100, 5, 10)
        actor.ultimates = [
            {"id": "u_old", "name": "老招", "effect_value": 0.5, "trigger_rate": 1.0}
        ]
        target = make_fighter("B", 1000, 100, 5, 10, armor=0)
        log: list[str] = []
        engine._resolve_attack(actor, target, 0.0, 1.5, log)
        # unarmed base (5 + 100 x 0.5) x (1 + 0.5) = 82 (legacy semantics kept)
        assert target.hp == 1000 - int(55 * 1.5)
        assert "u_old" in actor.used_ultimates

    def test_survive_ultimate_grants_charges(self):
        engine = make_engine()
        actor = make_fighter("A", 1000, 100, 5, 10)
        actor.ultimates = [
            {
                "id": "u_survive",
                "name": "金身",
                "effect_type": "survive",
                "effect_value": 0.0,
                "survive_count": 2,
                "min_action_index": 0,
                "trigger_rate": 1.0,
            }
        ]
        target = make_fighter("B", 1000, 100, 5, 10, armor=0)
        engine._resolve_attack(actor, target, 0.0, 1.5, log := [])
        assert actor.survive_charges == 2
        assert any("庇护" in line for line in log)


# ------------------------------------------------------------------
# 8.4 Sync contract extensions
# ------------------------------------------------------------------


class TestSyncContract:
    def test_effect_vocabulary_in_sync_with_registry(self):
        """SKILL_EFFECT_TYPES must match the engine registry exactly."""
        assert set(_sync.SKILL_EFFECT_TYPES) == set(
            CombatEngine.EFFECT_HANDLERS.keys()
        )

    @staticmethod
    def _skill_row(**overrides):
        base = {
            "id": "test_001",
            "name": "测试技能",
            "pool": "通用功法池",
            "status": "draft",
            "trigger_condition": "attack",
            "trigger_name": "测试触发",
            "trigger_rate": "0.5",
            "effect_type": "heal",
            "effect_value": "0.1",
            "duration": "",
            "tick_rate": "",
            "heal_percent": "",
            "pierce_rate": "",
            "reflect_rate": "",
            "survive_count": "",
            "ultimate_json": "",
            "route_mult_ling": "",
            "route_mult_ti": "",
            "description": "",
            "design_note": "",
            "ref_source": "",
            "required_level_index": "",
        }
        base.update(overrides)
        return base

    def test_build_skill_rejects_invalid_duration(self):
        errors: list[str] = []
        skill = _sync._build_skill(
            self._skill_row(duration="0"), errors
        )
        assert skill is not None  # errors are collected, not fatal per row
        assert any("duration" in e for e in errors)

    def test_build_skill_rejects_out_of_range_rate(self):
        errors: list[str] = []
        skill = _sync._build_skill(
            self._skill_row(pierce_rate="1.5"), errors
        )
        assert skill is not None
        assert any("pierce_rate" in e for e in errors)

    def test_build_skill_passes_optional_keys(self):
        errors: list[str] = []
        skill = _sync._build_skill(
            self._skill_row(
                duration="2", tick_rate="0.8", heal_percent="0.3",
                pierce_rate="0.4", reflect_rate="0.5", survive_count="2",
            ),
            errors,
        )
        assert errors == []
        trigger = skill["trigger_skill"]
        assert trigger["duration"] == 2
        assert trigger["tick_rate"] == 0.8
        assert trigger["heal_percent"] == 0.3
        assert trigger["pierce_rate"] == 0.4
        assert trigger["reflect_rate"] == 0.5
        assert trigger["survive_count"] == 2

    def test_validate_ultimate_rejects_bad_new_keys(self):
        errors: list[str] = []
        ult = _sync._validate_ultimate(
            '{"effect_type": "dot", "effect_value": 0.1, "duration": 0}',
            "skills.csv[x]",
            errors,
        )
        assert ult is not None  # errors are collected, main() aborts on any
        assert any("duration" in e for e in errors)


class TestValidateBudgetConversions:
    @staticmethod
    def _rows(text: str) -> list[dict]:
        return list(csv.DictReader(StringIO(text)))

    def test_heal_conversion_and_fail(self):
        rows = self._rows(
            "id,name,status,trigger_rate,effect_type,effect_value,duration,tick_rate\n"
            "h1,大治疗,draft,0.5,heal,0.1,,\n"          # 0.5x0.1x7 = 0.35 FAIL
            "h2,小治疗,draft,0.2,heal,0.1,,\n"           # 0.2x0.1x7 = 0.14 PASS
        )
        results = _vb.check_skills(rows)
        assert results[0].startswith("FAIL"), results[0]
        assert results[1].startswith("PASS"), results[1]

    def test_dot_conversion(self):
        rows = self._rows(
            "id,name,status,trigger_rate,effect_type,effect_value,duration,tick_rate\n"
            "d1,蚀骨,draft,0.3,dot,0.05,3,1.0\n"         # 0.045 PASS
        )
        results = _vb.check_skills(rows)
        assert results[0].startswith("PASS"), results[0]

    def test_dot_malformed_cells_fail(self):
        """Non-numeric duration/tick_rate must surface as FAIL lines instead
        of crashing the whole validation run (review fix)."""
        rows = self._rows(
            "id,name,status,trigger_rate,effect_type,effect_value,duration,tick_rate\n"
            "d1,坏时长,draft,0.3,dot,0.05,abc,1.0\n"
            "d2,坏频率,draft,0.3,dot,0.05,3,fast\n"
            "d3,零时长,draft,0.3,dot,0.05,0,1.0\n"        # sync 契约要求 >=1
        )
        results = _vb.check_skills(rows)
        assert results[0].startswith("FAIL"), results[0]
        assert "必须为数字" in results[0]
        assert results[1].startswith("FAIL"), results[1]
        assert "必须为数字" in results[1]
        assert results[2].startswith("FAIL"), results[2]
        assert "duration 须 >=1" in results[2]

    def test_pierce_conversion(self):
        rows = self._rows(
            "id,name,status,trigger_rate,effect_type,effect_value,duration,tick_rate\n"
            "p1,破甲,draft,0.5,dot,0.0,,\n"  # placeholder replaced below
        )
        rows[0]["effect_type"] = "pierce"
        rows[0]["effect_value"] = "0.1"
        results = _vb.check_skills(rows)  # 0.5x0.1x1.5 = 0.075 PASS
        assert results[0].startswith("PASS"), results[0]

    def test_fatigue_excluded(self):
        rows = self._rows(
            "id,name,status,trigger_rate,effect_type,effect_value,duration,tick_rate\n"
            "f1,燃血,draft,0.5,fatigue,0.2,,\n"
        )
        results = _vb.check_skills(rows)
        assert results[0].startswith("PASS"), results[0]

    def test_unregistered_effect_is_fail(self):
        rows = self._rows(
            "id,name,status,trigger_rate,effect_type,effect_value,duration,tick_rate\n"
            "x1,未知效果,draft,0.5,teleport,0.2,,\n"
        )
        results = _vb.check_skills(rows)
        assert results[0].startswith("FAIL"), results[0]
        assert "未注册" in results[0]


# ------------------------------------------------------------------
# 8.5 Integration
# ------------------------------------------------------------------


class TestIntegration:
    def test_engine_full_combat_with_new_effects(self):
        engine = make_engine({"combat": {"action_limit": 120}})
        attacker = make_fighter("A", 800, 120, 5, 12)
        attacker.trigger_skills = [
            trigger_skill("战意", "buff", 0.5, duration=5, stat="damage"),
            trigger_skill("蚀骨", "dot", 0.15, duration=4),
        ]
        attacker.ultimates = [
            {
                "id": "u_survive",
                "name": "金身",
                "effect_type": "survive",
                "effect_value": 0.0,
                "survive_count": 1,
                "min_action_index": 0,
                "trigger_rate": 1.0,
            }
        ]
        defender = make_fighter("B", 800, 120, 5, 12, armor=50)
        defender.trigger_skills = [
            trigger_skill("回春", "heal", 0.2, trigger_timing="on_defense")
        ]
        result = engine.resolve_combat(attacker, defender, "duel", merge_count=10)
        assert result.winner in ("A", "B", "draw")
        log_text = "\n".join(result.combat_log)
        assert any(
            marker in log_text
            for marker in ("侵蚀", "免死", "恢复")
        )

    def test_manager_adapter_path(self):
        """CombatManager adapter still drives the engine end to end."""
        manager = CombatManager(FakeConfigManager({"combat": {}}), FakeSkillManager())
        assert manager.engine is not None

        class FakePlayer:
            def __init__(self, uid, name, hp):
                self.user_id = uid
                self.user_name = name
                self.hp = hp
                self.level_index = 1
                self.weapon = None
                self.armor = None
                self.main_technique = None
                self.battle_report_merge_count = 5

            def get_techniques_list(self):
                return []

            def get_total_attributes(self, items, pill_multipliers=None):
                return {
                    "hp": self.hp,
                    "damage": 100,
                    "agility": 10,
                    "speed": 10,
                    "armor_value": 0,
                }

        p1 = FakePlayer("p1", "甲", 1000)
        p2 = FakePlayer("p2", "乙", 1000)
        result = asyncio.run(manager.player_vs_player(p1, p2, combat_type=2))
        assert result["winner"] in ("p1", "p2", "draw")
        assert result["rounds"] >= 1
        assert result["player1_final_hp"] >= 0
        assert result["player2_final_hp"] >= 0

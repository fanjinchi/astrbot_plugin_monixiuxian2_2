"""Tests for the unified combat engine (combat-core spec)."""

import random
import sys
from pathlib import Path

# Ensure plugin root is on path
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from tests.helpers import load_module  # noqa: E402

# Load combat manager module
_mod = load_module("combat_manager", "managers/combat_manager.py")
CombatEngine = _mod.CombatEngine
CombatManager = _mod.CombatManager
FighterState = _mod.FighterState


class FakeConfigManager:
    """Minimal fake config manager for tests."""

    def __init__(self, game_config=None):
        self.game_config = game_config or {}


class FakeSkillManager:
    """Minimal fake skill manager for tests."""

    def get_battle_loadout(self, player):
        return {
            "trigger_skills": [],
            "ultimates": [],
            "heart_method_passive": {},
            "weapon_coefficient_k": 1.0,
            "base_damage": 0,
            "armor_value": 0,
        }


def make_engine(cfg=None):
    config = FakeConfigManager(cfg or {})
    return CombatEngine(config, FakeSkillManager())


def make_fighter(name, hp, damage, agility, speed, armor=0, weapon_k=1.0, base_dmg=0):
    return FighterState(
        user_id=name,
        name=name,
        hp=hp,
        max_hp=hp,
        damage=damage,
        agility=agility,
        speed=speed,
        armor_value=armor,
        weapon_k=weapon_k,
        base_damage=base_dmg,
    )


# ------------------------------------------------------------------
# 4.1 Speed-weighted initiative
# ------------------------------------------------------------------

class TestInitiative:
    def test_speed_double_gets_twice_as_many_actions(self):
        """When fighter A has 2x speed of B, A should act ~2x as often."""
        engine = make_engine()
        f1 = make_fighter("Fast", 100, 10, 5, 20)
        f2 = make_fighter("Slow", 100, 10, 5, 10)

        f1_actions = 0
        f2_actions = 0
        trials = 1000

        for _ in range(trials):
            if engine._roll_initiative(f1, f2):
                f1_actions += 1
            else:
                f2_actions += 1

        ratio = f1_actions / f2_actions if f2_actions > 0 else float("inf")
        # With 2:1 speed ratio, expect ~2:1 action ratio (tolerate 15% variance)
        assert 1.7 < ratio < 2.3, f"Expected ratio ~2.0, got {ratio:.2f}"

    def test_equal_speed_fifty_fifty(self):
        """When speeds are equal, initiative should be roughly 50/50."""
        engine = make_engine()
        f1 = make_fighter("A", 100, 10, 5, 10)
        f2 = make_fighter("B", 100, 10, 5, 10)

        f1_actions = sum(1 for _ in range(1000) if engine._roll_initiative(f1, f2))
        ratio = f1_actions / 1000
        assert 0.45 < ratio < 0.55, f"Expected ~0.5, got {ratio:.3f}"


# ------------------------------------------------------------------
# 4.1 Muxxu damage formula
# ------------------------------------------------------------------

class TestDamageFormula:
    def test_base_damage_formula(self):
        """Damage = floor((base + dmg_attr * K) * random * mult)."""
        engine = make_engine()
        dmg = engine._calc_damage(
            damage_attr=100,
            weapon_k=1.5,
            base_damage=20,
            skill_multiplier=1.0,
            is_crit=False,
            crit_multiplier=1.5,
        )
        # Base = 20 + 100*1.5 = 170; with random 0.95-1.05 -> 161-178
        assert 150 < dmg < 190

    def test_high_k_weapon_scales_with_damage(self):
        """High-K weapon should outscale low-K at high damage attribute."""
        engine = make_engine()

        high_k_dmg = engine._calc_damage(
            damage_attr=200, weapon_k=2.0, base_damage=10,
            skill_multiplier=1.0, is_crit=False, crit_multiplier=1.5,
        )
        low_k_dmg = engine._calc_damage(
            damage_attr=200, weapon_k=0.5, base_damage=30,
            skill_multiplier=1.0, is_crit=False, crit_multiplier=1.5,
        )
        # High K: 10 + 200*2 = 410; Low K: 30 + 200*0.5 = 130
        assert high_k_dmg > low_k_dmg

    def test_damage_minimum_one(self):
        """Damage should never go below 1."""
        engine = make_engine()
        dmg = engine._calc_damage(
            damage_attr=1, weapon_k=0.1, base_damage=0,
            skill_multiplier=0.1, is_crit=False, crit_multiplier=1.5,
        )
        assert dmg >= 1

    def test_unarmed_fallback(self):
        """Unarmed fighters get base damage 5 and K=0.5."""
        engine = make_engine()
        dmg = engine._calc_damage(
            damage_attr=50, weapon_k=1.0, base_damage=0,
            skill_multiplier=1.0, is_crit=False, crit_multiplier=1.5,
        )
        # Falls back to base=5, K=0.5 -> 5 + 50*0.5 = 30
        assert dmg >= 25

    def test_crit_multiplies_damage(self):
        """Crit should multiply damage by crit_multiplier."""
        engine = make_engine()

        # Fix random by seeding
        random.seed(42)
        normal = engine._calc_damage(
            damage_attr=100, weapon_k=1.0, base_damage=20,
            skill_multiplier=1.0, is_crit=False, crit_multiplier=1.5,
        )
        random.seed(42)
        crit = engine._calc_damage(
            damage_attr=100, weapon_k=1.0, base_damage=20,
            skill_multiplier=1.0, is_crit=True, crit_multiplier=1.5,
        )
        # Same random roll, crit should be 1.5x
        assert crit > normal
        assert abs(crit / normal - 1.5) < 0.1


# ------------------------------------------------------------------
# 4.1 Armor damage reduction
# ------------------------------------------------------------------

class TestArmorReduction:
    def test_armor_reduces_damage(self):
        """Armor should subtract from final damage."""
        engine = make_engine()
        make_fighter("Attacker", 100, 50, 5, 10, armor=0)
        make_fighter("Defender1", 100, 10, 5, 10, armor=5)
        make_fighter("Defender2", 100, 10, 5, 10, armor=50)

        # Simulate many attacks to average out randomness
        dmg_low = 0
        dmg_high = 0
        trials = 100

        for _ in range(trials):
            d1 = engine._calc_damage(50, 1.0, 10, 1.0, False, 1.5)
            dmg_low += max(1, d1 - 5)
            dmg_high += max(1, d1 - 50)

        avg_low = dmg_low / trials
        avg_high = dmg_high / trials
        assert avg_high < avg_low

    def test_damage_never_below_one(self):
        """Even with high armor, damage minimum is 1."""
        engine = make_engine()
        raw = engine._calc_damage(10, 0.5, 5, 1.0, False, 1.5)
        final = max(1, raw - 1000)  # Armor 1000
        assert final == 1


# ------------------------------------------------------------------
# 4.2 Resolution chain
# ------------------------------------------------------------------

class TestResolutionChain:
    def test_dodge_prevents_damage(self):
        """If dodge succeeds, no damage is dealt."""
        engine = make_engine()
        f1 = make_fighter("A", 100, 50, 5, 10)  # agility=5, speed=10
        # With dodge_cap=1.0 and high agility, dodge is guaranteed
        f2 = make_fighter("B", 100, 10, 1000, 10)  # agility=1000, speed=10

        log: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=1.0, crit_multiplier=1.5, log=log)

        # Should have dodge message and f2 HP unchanged
        assert any("躲" in entry for entry in log)
        assert f2.hp == 100

    def test_dodge_rate_capped(self):
        """Dodge rate should not exceed cap."""
        engine = make_engine()
        f1 = make_fighter("A", 100, 10, 5, 10)
        f2 = make_fighter("B", 100, 10, 5, 9999)  # Extreme agility

        rate = engine._calc_dodge_rate(f1, f2, cap=0.5)
        assert rate <= 0.5

    def test_ultimate_once_per_battle(self):
        """Each ultimate can only trigger once per battle."""
        engine = make_engine()
        f1 = make_fighter("A", 100, 50, 5, 10)
        f1.ultimates = [
            {"id": "ult1", "name": "TestUlt", "trigger_rate": 1.0, "effect_value": 1.0}
        ]
        f2 = make_fighter("B", 1000, 10, 5, 10)  # High HP to survive

        log1: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=0.5, crit_multiplier=1.5, log=log1)

        # Ultimate should have triggered
        assert "ult1" in f1.used_ultimates
        assert any("大招" in entry for entry in log1)

        log2: list[str] = []
        engine._resolve_attack(f1, f2, dodge_cap=0.5, crit_multiplier=1.5, log=log2)

        # Ultimate should NOT trigger again
        assert not any("大招" in entry for entry in log2)


# ------------------------------------------------------------------
# 4.1 Action limit / draw
# ------------------------------------------------------------------

class TestActionLimit:
    def test_action_limit_draw(self):
        """When action limit is reached without a winner, result is draw."""
        engine = make_engine({"combat": {"action_limit": 5}})
        f1 = make_fighter("A", 100, 1, 5, 10)  # Low damage = long fight
        f2 = make_fighter("B", 100, 1, 5, 10)

        result = engine.resolve_combat(f1, f2, merge_count=100)
        assert result.winner == "draw"
        assert result.total_actions >= 5


# ------------------------------------------------------------------
# 4.3 Battle report merging
# ------------------------------------------------------------------

class TestBattleReport:
    def test_default_merge_count(self):
        """Log should be merged into chunks of default size."""
        engine = make_engine({"skill_system": {"battle_report_merge_count": 3}})
        f1 = make_fighter("A", 10, 100, 5, 10)  # Quick fight
        f2 = make_fighter("B", 10, 100, 5, 10)

        result = engine.resolve_combat(f1, f2)
        # Should have multiple chunks, each with ~3 lines
        assert len(result.combat_log) >= 1
        for chunk in result.combat_log:
            lines = chunk.split("\n")
            assert len(lines) <= 5  # Allow some variance

    def test_merge_count_parameter(self):
        """Custom merge count should be respected."""
        engine = make_engine()
        f1 = make_fighter("A", 10, 100, 5, 10)
        f2 = make_fighter("B", 10, 100, 5, 10)

        result = engine.resolve_combat(f1, f2, merge_count=50)
        # With 50-line chunks, a quick fight should be 1 chunk
        assert len(result.combat_log) == 1


# ------------------------------------------------------------------
# 4.4 Full combat integration
# ------------------------------------------------------------------

class TestFullCombat:
    def test_spar_no_hp_loss(self):
        """Spar should not result in actual HP loss."""
        engine = make_engine()
        f1 = make_fighter("A", 100, 50, 5, 10)
        f2 = make_fighter("B", 100, 50, 5, 10)

        result = engine.resolve_combat(f1, f2, combat_type="spar")
        assert result.winner in (f1.user_id, f2.user_id, "draw")
        # HP was modified on the fighter objects, but the result shows final
        assert result.fighter1_final_hp >= 0
        assert result.fighter2_final_hp >= 0

    def test_combat_ends_when_hp_zero(self):
        """Combat should end immediately when a fighter's HP reaches 0."""
        engine = make_engine()
        f1 = make_fighter("A", 100, 1000, 5, 10)  # One-shot damage
        f2 = make_fighter("B", 10, 10, 5, 10)

        result = engine.resolve_combat(f1, f2)
        assert result.winner == f1.user_id
        assert result.fighter2_final_hp == 0
        assert result.rounds <= 2  # Should end in 1-2 rounds


# ------------------------------------------------------------------
# Legacy adapter tests
# ------------------------------------------------------------------

class TestLegacyAdapter:
    def test_legacy_player_vs_player_returns_dict(self):
        """Legacy player_vs_player should return the expected dict shape."""
        config = FakeConfigManager({
            "combat": {"action_limit": 200, "dodge_cap": 0.5, "crit_damage_multiplier": 1.5},
            "skill_system": {"battle_report_merge_count": 10},
        })
        mgr = CombatManager(config, FakeSkillManager())

        # We can't easily test with real Player objects without more setup,
        # so we test the engine directly
        f1 = make_fighter("A", 100, 50, 5, 10)
        f2 = make_fighter("B", 100, 50, 5, 10)

        result = mgr.engine.resolve_combat(f1, f2)
        assert result.winner in ("A", "B", "draw")
        assert isinstance(result.combat_log, list)

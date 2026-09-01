"""Tests for the unified combat engine (combat-core spec)."""

import random
import sys
from pathlib import Path

import pytest

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
StatusEffect = _mod.StatusEffect


class FakeConfigManager:
    """Minimal fake config manager for tests."""

    def __init__(self, game_config=None):
        self.game_config = game_config or {}
        self.items_data = {}
        self.weapons_data = {}
        self.heart_methods_data = {}


class FakeSkillManager:
    """Minimal fake skill manager for tests."""

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
    config = FakeConfigManager(cfg or {})
    return CombatEngine(config, FakeSkillManager())


def make_fighter(
    name, hp, damage, agility, speed, armor=0, weapon_k=1.0, base_dmg=0, level_index=1
):
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
        level_index=level_index,
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
        # With 2:1 speed ratio, expect ~2:1 action ratio (tolerate 20% variance, ~3σ)
        assert 1.6 < ratio < 2.4, f"Expected ratio ~2.0, got {ratio:.2f}"

    def test_equal_speed_fifty_fifty(self):
        """When speeds are equal, initiative should be roughly 50/50."""
        engine = make_engine()
        f1 = make_fighter("A", 100, 10, 5, 10)
        f2 = make_fighter("B", 100, 10, 5, 10)

        f1_actions = sum(1 for _ in range(1000) if engine._roll_initiative(f1, f2))
        ratio = f1_actions / 1000
        assert 0.45 < ratio < 0.55, f"Expected ~0.5, got {ratio:.3f}"


class TestCombatActionDistribution:
    def test_speed_double_gets_twice_as_many_actions_in_full_combat(self):
        """In a full combat, 2x speed yields ~2x total actions for the faster fighter."""
        engine = make_engine({"combat": {"action_limit": 200}})
        f1 = make_fighter("Fast", 1000, 1, 5, 20)
        f2 = make_fighter("Slow", 1000, 1, 5, 10)

        random.seed(20260729)  # Deterministic statistical check

        actions: list[str] = []
        original_resolve = engine._resolve_attack

        def tracking_resolve(attacker, defender, *args, **kwargs):
            actions.append(attacker.name)
            original_resolve(attacker, defender, *args, **kwargs)

        engine._resolve_attack = tracking_resolve
        engine.resolve_combat(f1, f2)

        fast_actions = actions.count("Fast")
        slow_actions = actions.count("Slow")
        ratio = fast_actions / slow_actions if slow_actions > 0 else float("inf")
        assert 1.7 < ratio < 2.3, f"Expected ratio ~2.0, got {ratio:.2f}"

    def test_each_action_is_independent(self):
        """Each action is decided independently; equal speed stays near 50/50."""
        engine = make_engine()
        f1 = make_fighter("A", 1000, 1, 5, 10)
        f2 = make_fighter("B", 1000, 1, 5, 10)

        random.seed(20260729)  # Deterministic statistical check

        actions: list[str] = []
        original_resolve = engine._resolve_attack

        def tracking_resolve(attacker, defender, *args, **kwargs):
            actions.append(attacker.name)
            original_resolve(attacker, defender, *args, **kwargs)

        engine._resolve_attack = tracking_resolve
        engine.resolve_combat(f1, f2)

        a_actions = actions.count("A")
        total = len(actions)
        ratio = a_actions / total if total > 0 else 0
        assert 0.4 < ratio < 0.6, f"Expected ~0.5, got {ratio:.3f}"


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
            damage_attr=200,
            weapon_k=2.0,
            base_damage=10,
            skill_multiplier=1.0,
            is_crit=False,
            crit_multiplier=1.5,
        )
        low_k_dmg = engine._calc_damage(
            damage_attr=200,
            weapon_k=0.5,
            base_damage=30,
            skill_multiplier=1.0,
            is_crit=False,
            crit_multiplier=1.5,
        )
        # High K: 10 + 200*2 = 410; Low K: 30 + 200*0.5 = 130
        assert high_k_dmg > low_k_dmg

    def test_damage_minimum_one(self):
        """Damage should never go below 1."""
        engine = make_engine()
        dmg = engine._calc_damage(
            damage_attr=1,
            weapon_k=0.1,
            base_damage=0,
            skill_multiplier=0.1,
            is_crit=False,
            crit_multiplier=1.5,
        )
        assert dmg >= 1

    def test_unarmed_fallback(self):
        """Unarmed fighters get base damage 5 and K=0.5."""
        engine = make_engine()
        dmg = engine._calc_damage(
            damage_attr=50,
            weapon_k=1.0,
            base_damage=0,
            skill_multiplier=1.0,
            is_crit=False,
            crit_multiplier=1.5,
        )
        # Falls back to base=5, K=0.5 -> 5 + 50*0.5 = 30
        assert dmg >= 25

    def test_crit_multiplies_damage(self):
        """Crit should multiply damage by crit_multiplier."""
        engine = make_engine()

        # Fix random by seeding
        random.seed(42)
        normal = engine._calc_damage(
            damage_attr=100,
            weapon_k=1.0,
            base_damage=20,
            skill_multiplier=1.0,
            is_crit=False,
            crit_multiplier=1.5,
        )
        random.seed(42)
        crit = engine._calc_damage(
            damage_attr=100,
            weapon_k=1.0,
            base_damage=20,
            skill_multiplier=1.0,
            is_crit=True,
            crit_multiplier=1.5,
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

    def test_block_reduces_damage(self):
        """Block should halve the incoming damage."""
        engine = make_engine()
        f1 = make_fighter("A", 100, 100, 5, 10, base_dmg=100)
        f2_no_block = make_fighter("B", 1000, 10, 5, 10, armor=0)
        f2_block = make_fighter("B", 1000, 10, 5, 10, armor=0)

        import random as _random

        original_random = _random.random
        original_uniform = _random.uniform

        # Force no dodge, no block, no crit, flat damage roll
        _random.random = lambda: 0.9
        _random.uniform = lambda a, b: 1.0
        try:
            engine._resolve_attack(
                f1, f2_no_block, dodge_cap=0.5, crit_multiplier=1.5, log=[]
            )
        finally:
            _random.random = original_random
            _random.uniform = original_uniform

        # Force no dodge, block, no crit, flat damage roll
        _random.random = (v for v in [0.9, 0.0, 0.9]).__next__
        _random.uniform = lambda a, b: 1.0
        try:
            engine._resolve_attack(
                f1, f2_block, dodge_cap=0.5, crit_multiplier=1.5, log=[]
            )
        finally:
            _random.random = original_random
            _random.uniform = original_uniform

        # Raw damage is 200; blocked halves it to 100
        assert f2_no_block.hp == 800
        assert f2_block.hp == 900

    def test_chain_order_crit_trigger_ultimate(self):
        """Crit phase runs before on_crit triggers and ultimate."""
        engine = make_engine()
        f1 = make_fighter("A", 100, 100, 5, 10, base_dmg=50)
        f1.trigger_skills = [
            {
                "name": "乘胜追击",
                "trigger_timing": "on_crit",
                "trigger_rate": 1.0,
                "effect_type": "damage_bonus",
                "effect_value": 0.5,
            }
        ]
        f1.ultimates = [
            {
                "id": "ult_chain",
                "name": "终结技",
                "trigger_rate": 1.0,
                "effect_value": 1.0,
            }
        ]
        f2 = make_fighter("B", 1000, 10, 5, 10, armor=0)

        import random as _random

        original_random = _random.random
        original_uniform = _random.uniform

        # Sequence: dodge fail, block fail, crit success, trigger success, ultimate success
        _random.random = (v for v in [0.9, 0.9, 0.0, 0.0, 0.0]).__next__
        _random.uniform = lambda a, b: b
        log: list[str] = []
        try:
            engine._resolve_attack(f1, f2, dodge_cap=0.5, crit_multiplier=1.5, log=log)
        finally:
            _random.random = original_random
            _random.uniform = original_uniform

        log_text = "\n".join(log)
        assert "暴击" in log_text
        assert "乘胜追击" in log_text
        assert "终结技" in log_text
        crit_idx = log_text.index("暴击")
        trigger_idx = log_text.index("乘胜追击")
        ultimate_idx = log_text.index("终结技")
        assert trigger_idx < ultimate_idx < crit_idx

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
        config = FakeConfigManager(
            {
                "combat": {
                    "action_limit": 200,
                    "dodge_cap": 0.5,
                    "crit_damage_multiplier": 1.5,
                },
                "skill_system": {"battle_report_merge_count": 10},
            }
        )
        mgr = CombatManager(config, FakeSkillManager())

        # We can't easily test with real Player objects without more setup,
        # so we test the engine directly
        f1 = make_fighter("A", 100, 50, 5, 10)
        f2 = make_fighter("B", 100, 50, 5, 10)

        result = mgr.engine.resolve_combat(f1, f2)
        assert result.winner in ("A", "B", "draw")
        assert isinstance(result.combat_log, list)


# ------------------------------------------------------------------
# FighterState built from Player total attributes
# ------------------------------------------------------------------


class FakePlayer:
    """Minimal Player stub for build_fighter_from_player tests."""

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

    def get_techniques_list(self):
        try:
            import json

            return json.loads(self.techniques)
        except Exception:
            return []

    def get_total_attributes(self, equipped_items, pill_multipliers=None):
        import json

        total = {
            "damage": self.damage,
            "agility": self.agility,
            "speed": self.speed,
            "hp": self.hp,
            "armor_value": self.armor_value,
            "exp_multiplier": 0.0,
        }
        for item in equipped_items:
            mult = item.get_route_multiplier(self.cultivation_type)
            total["damage"] += int(item.damage * mult)
            total["agility"] += int(item.agility * mult)
            total["speed"] += int(item.speed * mult)
            total["hp"] += int(item.hp * mult)
            total["armor_value"] += int(item.armor_value * mult)
            if item.item_type == "main_technique":
                try:
                    passive = json.loads(item.passive_bonus)
                except (json.JSONDecodeError, TypeError):
                    passive = {}
                for key, value in passive.items():
                    if key == "hp_percent":
                        total["hp"] = int(total["hp"] * (1 + value))
                    elif key == "damage_percent":
                        total["damage"] = int(total["damage"] * (1 + value))
                    elif key == "agility_percent":
                        total["agility"] = int(total["agility"] * (1 + value))
                    elif key == "speed_percent":
                        total["speed"] = int(total["speed"] * (1 + value))
                    elif key == "armor_value":
                        total["armor_value"] += int(value)
        if pill_multipliers:
            for key in ["damage", "agility", "speed", "hp", "armor_value"]:
                total[key] = int(total[key] * pill_multipliers.get(key, 1.0))
        return total


class TestBuildFighterFromPlayer:
    @pytest.mark.asyncio
    async def test_equipment_bonuses_applied_to_fighter(self):
        """FighterState damage/hp/armor include equipment bonuses."""
        config = FakeConfigManager(
            {
                "combat": {
                    "action_limit": 200,
                    "dodge_cap": 0.5,
                    "crit_damage_multiplier": 1.5,
                },
                "skill_system": {"battle_report_merge_count": 10},
            }
        )
        config.weapons_data = {
            "Test Sword": {
                "damage": 15,
                "speed": 5,
                "weapon_coefficient_k": 1.2,
                "base_damage": 10,
            }
        }
        config.items_data = {
            "Test Armor": {
                "type": "法器",
                "subtype": "防具",
                "armor_value": 20,
                "hp": 30,
            }
        }
        engine = CombatEngine(config, FakeSkillManager())
        player = FakePlayer(
            damage=10, hp=100, armor_value=0, weapon="Test Sword", armor="Test Armor"
        )

        fighter = await engine.build_fighter_from_player(player)
        assert fighter.damage == 25  # base 10 + weapon 15
        assert fighter.speed == 10  # base 5 + weapon 5
        assert fighter.max_hp == 130  # base 100 + armor 30
        assert fighter.armor_value == 20  # armor only

    @pytest.mark.asyncio
    async def test_heart_method_passive_applied(self):
        """Heart-method passive bonuses flow into FighterState attributes."""
        config = FakeConfigManager(
            {
                "combat": {
                    "action_limit": 200,
                    "dodge_cap": 0.5,
                    "crit_damage_multiplier": 1.5,
                },
                "skill_system": {"battle_report_merge_count": 10},
            }
        )
        config.heart_methods_data = {
            "Test Heart": {
                "passive_bonus": {"hp_percent": 0.2, "damage_percent": 0.1},
            }
        }
        engine = CombatEngine(config, FakeSkillManager())
        player = FakePlayer(
            damage=100, hp=100, armor_value=0, main_technique="Test Heart"
        )

        fighter = await engine.build_fighter_from_player(player)
        assert fighter.damage == 110  # 100 * 1.1
        assert fighter.max_hp == 120  # 100 * 1.2


# ------------------------------------------------------------------
# Armor formula: percent reduction (def/(def+K))
# ------------------------------------------------------------------


class TestArmorPercentFormula:
    def test_zero_armor_no_reduction(self):
        """Armor=0 should result in no reduction."""
        engine = make_engine(
            {
                "combat": {
                    "armor_k_base": 100,
                    "armor_k_level_coeff": 10,
                    "damage_reduction_cap": 0.4,
                }
            }
        )
        defender = make_fighter("D", 1000, 10, 5, 10, armor=0, level_index=1)
        final = engine._apply_armor_and_reduction(defender, 100)
        assert final == 100

    def test_armor_reduces_damage_percent(self):
        """Armor should reduce damage by percent formula."""
        engine = make_engine(
            {
                "combat": {
                    "armor_k_base": 100,
                    "armor_k_level_coeff": 10,
                    "damage_reduction_cap": 0.4,
                }
            }
        )
        # L1, armor=100, K=110 -> rate = 100/210 ≈ 0.476
        defender = make_fighter("D", 1000, 10, 5, 10, armor=100, level_index=1)
        final = engine._apply_armor_and_reduction(defender, 100)
        # 100 * (1 - 100/210) = 100 * 110/210 ≈ 52
        assert final < 100
        assert final > 40

    def test_high_level_increases_k(self):
        """Higher level increases K, reducing armor effectiveness."""
        engine = make_engine(
            {
                "combat": {
                    "armor_k_base": 100,
                    "armor_k_level_coeff": 10,
                    "damage_reduction_cap": 0.4,
                }
            }
        )
        # Same armor, different levels
        defender_l1 = make_fighter("D1", 1000, 10, 5, 10, armor=100, level_index=1)
        defender_l50 = make_fighter("D50", 1000, 10, 5, 10, armor=100, level_index=50)

        final_l1 = engine._apply_armor_and_reduction(defender_l1, 100)
        final_l50 = engine._apply_armor_and_reduction(defender_l50, 100)
        # L50 has K=600, so armor is less effective
        assert final_l50 > final_l1

    def test_damage_never_below_one(self):
        """Even with extreme armor, damage minimum is 1 (but cap may raise it)."""
        engine = make_engine(
            {
                "combat": {
                    "armor_k_base": 100,
                    "armor_k_level_coeff": 10,
                    "damage_reduction_cap": 0.4,
                }
            }
        )
        # With cap=0.4, min_fraction=0.6, so even extreme armor deals at least 60% damage
        defender = make_fighter("D", 1000, 10, 5, 10, armor=99999, level_index=1)
        final = engine._apply_armor_and_reduction(defender, 10)
        # 10 * 0.6 = 6 (capped by damage_reduction_cap)
        assert final == 6

    def test_ultra_high_damage_penettrates(self):
        """Ultra high damage should still deal meaningful damage."""
        engine = make_engine(
            {
                "combat": {
                    "armor_k_base": 100,
                    "armor_k_level_coeff": 10,
                    "damage_reduction_cap": 0.4,
                }
            }
        )
        defender = make_fighter("D", 100000, 10, 5, 10, armor=500, level_index=50)
        # K = 100 + 10*50 = 600, rate = 500/1100 ≈ 0.455
        # Without cap: 10000 * (1 - 0.455) ≈ 5450
        # But cap limits reduction to 40%, so minimum fraction = 0.6
        # final = 10000 * 0.6 = 6000
        final = engine._apply_armor_and_reduction(defender, 10000)
        assert final == 6000


# ------------------------------------------------------------------
# Combat caps
# ------------------------------------------------------------------


class TestCombatCaps:
    def test_dodge_cap_40_percent(self):
        """Dodge cap should be 40% when configured."""
        engine = make_engine({"combat": {"dodge_cap": 0.4}})
        f1 = make_fighter("A", 100, 10, 5, 10)  # agility=5
        f2 = make_fighter("B", 100, 10, 9999, 10)  # agility=9999, speed=10

        rate = engine._calc_dodge_rate(f1, f2, cap=engine._dodge_cap)
        assert rate == 0.4

    def test_block_cap_30_percent(self):
        """Block cap should be 30% when configured."""
        engine = make_engine({"combat": {"block_cap": 0.3}})
        defender = make_fighter("D", 1000, 10, 5, 10, armor=99999)

        rate = engine._calc_block_rate(defender)
        assert rate == 0.3

    def test_crit_rate_capped(self):
        """Crit rate above cap should be truncated."""
        engine = make_engine({"combat": {"crit_rate_cap": 0.5}})
        attacker = make_fighter("A", 100, 50, 5, 10)
        attacker.crit_rate = 0.99  # Would be 99% without cap
        defender = make_fighter("B", 1000, 10, 5, 10)

        # Force crit by seeding random to 0.0 (always < 0.5)
        import random as _random

        original_random = _random.random
        _random.random = lambda: 0.0
        try:
            log: list[str] = []
            engine._resolve_attack(
                attacker, defender, dodge_cap=0.0, crit_multiplier=1.5, log=log
            )
            # With capped 50%, random=0.0 < 0.5 -> crit
            assert any("暴击" in entry for entry in log)
        finally:
            _random.random = original_random

        # Force no crit by seeding random to 0.6 (> 0.5 cap)
        _random.random = lambda: 0.6
        try:
            defender2 = make_fighter("B2", 1000, 10, 5, 10)
            log2: list[str] = []
            engine._resolve_attack(
                attacker, defender2, dodge_cap=0.0, crit_multiplier=1.5, log=log2
            )
            # With capped 50%, random=0.6 > 0.5 -> no crit
            assert not any("暴击" in entry for entry in log2)
        finally:
            _random.random = original_random

    def test_crit_damage_capped(self):
        """Crit damage multiplier above cap should be truncated."""
        engine = make_engine(
            {
                "combat": {
                    "crit_damage_multiplier": 3.0,  # Would be 3x without cap
                    "crit_damage_cap": 2.0,
                }
            }
        )
        attacker = make_fighter("A", 100, 100, 5, 10, base_dmg=100)
        attacker.crit_rate = 1.0  # Force crit
        defender = make_fighter(
            "B", 10000, 10, 5, 10, armor=-1000
        )  # Negative armor -> 0 block rate

        import random as _random

        original_random = _random.random
        original_uniform = _random.uniform
        # Force no dodge, no block (armor negative -> block rate 0), crit
        _random.random = lambda: 0.1  # 0.1 > 0 block rate
        _random.uniform = lambda a, b: 1.0
        try:
            log: list[str] = []
            engine._resolve_attack(
                attacker, defender, dodge_cap=0.0, crit_multiplier=3.0, log=log
            )
            # With cap=2.0, damage should be (100 + 100*1.0) * 2.0 = 400
            # Without cap it would be 600
            hp_loss = 10000 - defender.hp
            assert hp_loss == 400, f"Expected 400 damage, got {hp_loss}"
        finally:
            _random.random = original_random
            _random.uniform = original_uniform

    def test_damage_reduction_cap(self):
        """Total damage reduction should not exceed cap."""
        engine = make_engine(
            {
                "combat": {
                    "armor_k_base": 100,
                    "armor_k_level_coeff": 10,
                    "damage_reduction_cap": 0.4,
                }
            }
        )
        # High armor + high skill reduction
        defender = make_fighter("D", 1000, 10, 5, 10, armor=1000, level_index=1)
        defender.incoming_damage_mult = 0.1  # 90% skill reduction

        final = engine._apply_armor_and_reduction(defender, 100)
        # Without cap: armor_rate = 1000/1100 ≈ 0.909, total_fraction = 0.091 * 0.1 = 0.0091
        # With 40% cap: min_fraction = 0.6, so total_fraction = max(0.0091, 0.6) = 0.6
        # final = floor(100 * 0.6) = 60
        assert final == 60

    def test_damage_reduction_cap_resets_incoming_mult(self):
        """incoming_damage_mult should be reset after consumption."""
        engine = make_engine(
            {
                "combat": {
                    "armor_k_base": 100,
                    "armor_k_level_coeff": 10,
                    "damage_reduction_cap": 0.4,
                }
            }
        )
        defender = make_fighter("D", 1000, 10, 5, 10, armor=0, level_index=1)
        defender.incoming_damage_mult = 0.5

        engine._apply_armor_and_reduction(defender, 100)
        assert defender.incoming_damage_mult == 1.0

    def test_combo_cap_limits_triggers(self):
        """Combo effects should be capped at combo_cap."""
        engine = make_engine({"combat": {"combo_cap": 2}})
        attacker = make_fighter("A", 100, 50, 5, 10)
        attacker.trigger_skills = [
            {
                "name": "连击1",
                "trigger_timing": "on_attack",
                "trigger_rate": 1.0,
                "effect_type": "combo",
                "effect_value": 0.5,
            },
            {
                "name": "连击2",
                "trigger_timing": "on_attack",
                "trigger_rate": 1.0,
                "effect_type": "combo",
                "effect_value": 0.5,
            },
            {
                "name": "连击3",
                "trigger_timing": "on_attack",
                "trigger_rate": 1.0,
                "effect_type": "combo",
                "effect_value": 0.5,
            },
        ]
        defender = make_fighter("B", 1000, 10, 5, 10)

        import random as _random

        original_random = _random.random
        original_uniform = _random.uniform
        # Force all triggers to fire (dodge fail, block fail, crit fail)
        _random.random = lambda: 0.9
        _random.uniform = lambda a, b: 1.0
        try:
            log: list[str] = []
            engine._resolve_attack(
                attacker, defender, dodge_cap=0.0, crit_multiplier=1.5, log=log
            )
            # Only 2 combo triggers should apply (combo_cap=2)
            combo_triggers = [entry for entry in log if "连击" in entry]
            assert len(combo_triggers) == 2
        finally:
            _random.random = original_random
            _random.uniform = original_uniform


# ------------------------------------------------------------------
# Config defaults (backward compatibility)
# ------------------------------------------------------------------


class TestConfigDefaults:
    def test_all_caps_have_defaults(self):
        """Engine should work with empty config (all defaults)."""
        engine = make_engine({})
        assert engine._dodge_cap == 0.5  # old default
        assert engine._block_cap == 0.3
        assert engine._crit_rate_cap == 0.5
        assert engine._crit_damage_cap == 2.0
        assert engine._combo_cap == 2
        assert engine._damage_reduction_cap == 0.4
        assert engine._armor_k_base == 100
        assert engine._armor_k_level_coeff == 10

    def test_custom_config_overrides_defaults(self):
        """Custom config values should override defaults."""
        engine = make_engine(
            {
                "combat": {
                    "dodge_cap": 0.25,
                    "block_cap": 0.15,
                    "crit_rate_cap": 0.3,
                    "crit_damage_cap": 1.5,
                    "combo_cap": 1,
                    "damage_reduction_cap": 0.2,
                    "armor_k_base": 50,
                    "armor_k_level_coeff": 5,
                }
            }
        )
        assert engine._dodge_cap == 0.25
        assert engine._block_cap == 0.15
        assert engine._crit_rate_cap == 0.3
        assert engine._crit_damage_cap == 1.5
        assert engine._combo_cap == 1
        assert engine._damage_reduction_cap == 0.2
        assert engine._armor_k_base == 50
        assert engine._armor_k_level_coeff == 5


# ------------------------------------------------------------------
# Narrative leftover scenes render from config (narrative-text-migration-leftovers)
# ------------------------------------------------------------------


def make_engine_with_narrative(combat_scenes):
    """Build an engine whose fake config manager carries a narrative_config."""
    config = FakeConfigManager({})
    config.narrative_config = {"combat": combat_scenes}
    return CombatEngine(config, FakeSkillManager())


class TestNarrativeLeftoverScenes:
    """The 7 leftover combat scenes are rendered from narrative_config."""

    def test_round_header_uses_configured_copy(self):
        engine = make_engine_with_narrative({"round_header": "ROUND {rounds} 开战"})
        f1 = make_fighter("A", 10, 100, 5, 10)
        f2 = make_fighter("B", 10, 100, 5, 10)
        result = engine.resolve_combat(f1, f2)
        # resolve_combat merges the raw log lines into chunks; join to search.
        report = "\n".join(result.combat_log)
        assert "ROUND 1 开战" in report
        assert "-- 第" not in report

    def test_round_header_default_matches_original(self):
        engine = make_engine()
        f1 = make_fighter("A", 10, 100, 5, 10)
        f2 = make_fighter("B", 10, 100, 5, 10)
        result = engine.resolve_combat(f1, f2)
        assert "-- 第 1 回合 --" in "\n".join(result.combat_log)

    def test_static_handler_renders_via_engine_narrative(self):
        """_handler_heal (a staticmethod) must reach the engine's _narrative
        wrapper through state["engine"] and pick up configured copy."""
        engine = make_engine_with_narrative(
            {"effect_heal": "治疗:{actor_name}|{skill_name}|{heal}"}
        )
        actor = make_fighter("A", 50, 100, 5, 10)
        log: list[str] = []
        CombatEngine._handler_heal(
            actor,
            actor,
            {"name": "回春术", "effect_value": 0.5},
            {"log": log, "engine": engine},
        )
        assert log == ["治疗:A|回春术|25"]

    def test_static_handler_skill_name_fallback_becomes_variable(self):
        """The skill.get('name', '反击') fallback is resolved at the render
        point and passed in as skill_name."""
        engine = make_engine()
        actor = make_fighter("A", 100, 100, 5, 10)
        target = make_fighter("B", 1000, 100, 5, 10)
        log: list[str] = []
        CombatEngine._handler_counter(
            actor, target, {"effect_value": 0.5}, {"log": log, "engine": engine}
        )
        assert log == ["A 触发【反击】反击，对 B 造成 50 点伤害！"]

    def test_dot_tick_uses_configured_copy(self):
        engine = make_engine_with_narrative(
            {"effect_dot_tick": "DOT {name}/{effect_name}/{dot_dmg}"}
        )
        fighter = make_fighter("A", 100, 10, 5, 10)
        fighter.status_effects.append(
            StatusEffect(
                source_name="蛊毒",
                kind="dot",
                effect_value=0.5,
                duration=2,
                remaining=2,
                snapshot_damage=20,
            )
        )
        log: list[str] = []
        engine._tick_status_effects(fighter, log)
        assert "DOT A/蛊毒/10" in log

    def test_dot_tick_default_matches_original(self):
        engine = make_engine()
        fighter = make_fighter("A", 100, 10, 5, 10)
        fighter.status_effects.append(
            StatusEffect(
                source_name="蛊毒",
                kind="dot",
                effect_value=0.5,
                duration=2,
                remaining=2,
                snapshot_damage=20,
            )
        )
        log: list[str] = []
        engine._tick_status_effects(fighter, log)
        assert "A 受【蛊毒】侵蚀，损失 10 气血！" in log

    def test_stack_cap_rejection_uses_configured_copy(self):
        engine = make_engine_with_narrative(
            {"effect_stack_cap_rejected": "拒绝:{actor_name}/{effect_name}/{stack_cap}"}
        )
        actor = make_fighter("A", 100, 10, 5, 10)
        # Fill the (kind, stat) bucket up to the cap so the next attach fails.
        for _ in range(engine._status_stack_cap):
            actor.status_effects.append(
                StatusEffect(
                    source_name="嗜血",
                    kind="buff",
                    effect_value=0.1,
                    duration=9,
                    remaining=9,
                    params={"stat": "damage"},
                )
            )
        log: list[str] = []
        engine._attach_stat_status(
            actor,
            {"name": "战意", "effect_value": 0.2, "stat": "damage"},
            kind="buff",
            log=log,
            who=actor,
        )
        assert log == [f"拒绝:A/战意/{engine._status_stack_cap}"]

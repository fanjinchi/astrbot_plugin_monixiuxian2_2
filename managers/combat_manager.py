"""Unified combat engine for PvP (spar/duel/impart PK) and PvE.

Implements the spec-driven combat-core requirements:
- Speed-weighted initiative: P(A acts) = speed_A / (speed_A + speed_B)
- Muxxu damage formula: floor((base_dmg + dmg_attr * K) * skill_mult * random)
  with percent armor reduction (armor/(armor+K), K = 100 + 10*level, total reduction capped)
- Unified resolution chain: dodge -> block -> crit -> trigger -> ultimate -> damage
- Trigger skill timings: on_attack, on_defense, on_crit, round_start
- Control effects: stun skips the next action right
- Counter effects trigger on defense
- Battle report merged into chunks (configurable, default 10)
- Action limit with draw (default 200)
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

try:
    from ..models import Item
except ImportError:
    # Standalone execution / test loading bypasses the package root.
    import importlib.util

    _plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _spec = importlib.util.spec_from_file_location(
        "combat_models", os.path.join(_plugin_root, "models.py")
    )
    _models_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_models_mod)
    Item = _models_mod.Item

if TYPE_CHECKING:
    from ..config_manager import ConfigManager
    from ..core.skill_manager import SkillManager
    from ..models import Player

logger = logging.getLogger(__name__)


@dataclass
class CombatStats:
    """Legacy combat stats dataclass for backward compatibility.

    Deprecated: Use FighterState for new code.
    """

    user_id: str
    name: str
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    atk: int
    defense: int = 0
    crit_rate: int = 0
    exp: int = 0


@dataclass
class StatusEffect:
    """A persistent battle status (dot/buff/debuff/fatigue).

    Lives only within one battle (attached to FighterState); ticked at
    round start and removed on expiry. ``effect_value`` follows the 0.x
    additive contract (0.25 = ×1.25 when applied).
    """

    source_name: str
    kind: str  # dot | buff | debuff | fatigue
    effect_value: float
    tick_rate: float = 1.0  # dot damage coefficient (× value × snapshot)
    duration: int = 1  # total rounds
    remaining: int = 1
    # Snapshot of the triggering attack's expected damage (dot base).
    snapshot_damage: int = 0
    # Optional passthrough params (e.g. which stat a buff affects).
    params: dict = field(default_factory=dict)


@dataclass
class FighterState:
    """Mutable combat state for a single fighter."""

    user_id: str
    name: str
    hp: int
    max_hp: int
    damage: int
    agility: int
    speed: int
    armor_value: int
    # Level index for armor K calculation (percent armor formula)
    level_index: int = 1
    # Equipment
    weapon_k: float = 1.0
    base_damage: int = 0
    # Skills
    trigger_skills: list[dict] = field(default_factory=list)
    ultimates: list[dict] = field(default_factory=list)
    # Track which ultimates have been used this battle
    used_ultimates: set[str] = field(default_factory=set)
    # Control/status state
    skip_next_action: bool = False
    # Multipliers for the next attack (set by round_start / on_defense effects)
    next_attack_mult: float = 1.0
    incoming_damage_mult: float = 1.0
    # Crit rate (base 0.15, can be modified by skills, capped by config)
    crit_rate: float = 0.15
    # Combo stack counter for current action (resets each attack)
    combo_stack: int = 0
    # Generic battle flags container (v2 effects, spec: combat-core)
    battle_flags: dict = field(default_factory=dict)
    # Status effects (dot/buff/debuff/fatigue, spec: battle-status-effects)
    status_effects: list[StatusEffect] = field(default_factory=list)
    # One-shot attack modifiers (consumed per attack, spec: combat-core)
    next_attack_unavoidable: bool = False
    next_attack_vampire: float = 0.0  # heal-back fraction of dealt damage
    next_attack_pierce_rate: float = 0.0  # armor bypass fraction (0-1)
    # Survive (免死) charges and recovery (spec: combat-core)
    survive_charges: int = 0
    survive_recovery: float = 0.0
    # Reflect rate (0-1) + the round it was last consumed (max 1/round)
    reflect_rate: float = 0.0
    reflect_round: int = 0
    # Number of actions this fighter has taken in the current battle
    action_count: int = 0


@dataclass
class CombatResult:
    """Result of a combat resolution."""

    winner: str  # user_id or "draw"
    combat_log: list[str]
    fighter1_final_hp: int
    fighter2_final_hp: int
    rounds: int
    total_actions: int


class CombatEngine:
    """Unified combat engine."""

    def __init__(
        self, config_manager: ConfigManager, skill_manager: SkillManager | None = None
    ):
        self.config_manager = config_manager
        self.skill_manager = skill_manager
        self._combat_cfg = config_manager.game_config.get("combat", {})
        self._skill_cfg = config_manager.game_config.get("skill_system", {})

        # Caps and formula parameters (all with defaults for backward compat)
        self._dodge_cap = self._combat_cfg.get("dodge_cap", 0.5)
        self._block_cap = self._combat_cfg.get("block_cap", 0.3)
        self._crit_rate_cap = self._combat_cfg.get("crit_rate_cap", 0.5)
        self._crit_damage_cap = self._combat_cfg.get("crit_damage_cap", 2.0)
        self._combo_cap = self._combat_cfg.get("combo_cap", 2)
        self._status_stack_cap = self._combat_cfg.get("status_stack_cap", 3)
        self._damage_reduction_cap = self._combat_cfg.get("damage_reduction_cap", 0.4)
        self._armor_k_base = self._combat_cfg.get("armor_k_base", 100)
        self._armor_k_level_coeff = self._combat_cfg.get("armor_k_level_coeff", 10)
        self._base_crit_rate = self._combat_cfg.get("base_crit_rate", 0.15)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_combat(
        self,
        fighter1: FighterState,
        fighter2: FighterState,
        combat_type: str = "spar",
        merge_count: int | None = None,
    ) -> CombatResult:
        """Resolve a full combat between two fighters.

        Args:
            fighter1: Attacker/initiator fighter state.
            fighter2: Defender/target fighter state.
            combat_type: "spar" | "duel" | "impart_pk" | "pve"
            merge_count: Battle report merge chunk size (default from config).

        Returns:
            CombatResult with winner, log, and final HP values.
        """
        if merge_count is None:
            merge_count = self._skill_cfg.get("battle_report_merge_count", 10)

        action_limit = self._combat_cfg.get("action_limit", 200)
        dodge_cap = self._dodge_cap
        crit_multiplier = self._combat_cfg.get("crit_damage_multiplier", 1.5)

        log: list[str] = []
        log.append("☆━━━━ 战斗开始 ━━━━☆")
        log.append(f"{fighter1.name} VS {fighter2.name}")
        log.append(
            f"{fighter1.name}：气血 {fighter1.hp}/{fighter1.max_hp}，"
            f"伤害 {fighter1.damage}，身法 {fighter1.agility}，迅捷 {fighter1.speed}"
        )
        log.append(
            f"{fighter2.name}：气血 {fighter2.hp}/{fighter2.max_hp}，"
            f"伤害 {fighter2.damage}，身法 {fighter2.agility}，迅捷 {fighter2.speed}"
        )
        log.append("")

        total_actions = 0
        rounds = 0

        while fighter1.hp > 0 and fighter2.hp > 0 and total_actions < action_limit:
            # Start a new round every two actions; round-start skills fire once per round.
            if total_actions % 2 == 0:
                rounds += 1
                log.append(f"-- 第 {rounds} 回合 --")
                # Tick existing effects first so round-start skills applied this
                # round get their full duration (review fix: tick ordering).
                self._tick_status_effects(fighter1, log)
                self._tick_status_effects(fighter2, log)
                # A dot can be lethal; stop when a fighter died from it
                # (survive charges were already consumed inside the tick).
                if fighter1.hp <= 0 or fighter2.hp <= 0:
                    break
                self._process_round_start_skills(fighter1, log)
                self._process_round_start_skills(fighter2, log)

            # Determine who acts this action (speed-weighted, independent each action)
            if self._roll_initiative(fighter1, fighter2):
                self._resolve_attack(
                    fighter1, fighter2, dodge_cap, crit_multiplier, log, round_no=rounds
                )
                fighter1.action_count += 1
            else:
                self._resolve_attack(
                    fighter2, fighter1, dodge_cap, crit_multiplier, log, round_no=rounds
                )
                fighter2.action_count += 1
            total_actions += 1

            # Add a blank line after each completed round (every two actions)
            if total_actions % 2 == 0:
                log.append("")

        # Determine winner
        if fighter1.hp <= 0 and fighter2.hp <= 0:
            winner = "draw"
            log.append("☆━━━━ 同归于尽！平局！━━━━☆")
        elif fighter1.hp <= 0:
            winner = fighter2.user_id
            log.append(f"☆━━━━ {fighter2.name} 胜利！━━━━☆")
        elif fighter2.hp <= 0:
            winner = fighter1.user_id
            log.append(f"☆━━━━ {fighter1.name} 胜利！━━━━☆")
        elif total_actions >= action_limit:
            winner = "draw"
            log.append("☆━━━━ 战斗胶着，双方罢手，平局！━━━━☆")
        else:
            winner = "draw"
            log.append("☆━━━━ 平局！━━━━☆")

        # Merge log into chunks
        merged_log = self._merge_log(log, merge_count)

        return CombatResult(
            winner=winner,
            combat_log=merged_log,
            fighter1_final_hp=max(0, fighter1.hp),
            fighter2_final_hp=max(0, fighter2.hp),
            rounds=rounds,
            total_actions=total_actions,
        )

    async def build_fighter_from_player(
        self, player: Player, is_attacker: bool = True
    ) -> FighterState:
        """Build a FighterState from a Player model.

        Uses ``Player.get_total_attributes`` to include equipment bonuses,
        route multipliers and heart-method passive bonuses. Weapon data and
        active skills are provided by ``skill_manager.get_battle_loadout``.
        """
        loadout: dict = {}
        if self.skill_manager:
            loadout = await self.skill_manager.get_battle_loadout(player)

        equipped_items = self._build_equipped_items(player)
        total_attrs = player.get_total_attributes(equipped_items, pill_multipliers=None)

        return FighterState(
            user_id=player.user_id,
            name=player.user_name or player.user_id,
            hp=total_attrs["hp"],
            max_hp=total_attrs["hp"],
            damage=total_attrs["damage"],
            agility=total_attrs["agility"],
            speed=total_attrs["speed"],
            armor_value=total_attrs["armor_value"],
            level_index=player.level_index,
            weapon_k=loadout.get("weapon_coefficient_k", 1.0),
            base_damage=loadout.get("base_damage", 0),
            trigger_skills=loadout.get("trigger_skills", []),
            ultimates=loadout.get("ultimates", []),
        )

    def _build_equipped_items(self, player: Player) -> list[Item]:
        """Build Item objects for the player's current equipment."""
        items: list[Item] = []
        slot_names = [
            player.weapon,
            player.armor,
            player.main_technique,
        ] + player.get_techniques_list()
        for name in slot_names:
            if not name:
                continue
            item = self._parse_item_config(name)
            if item:
                items.append(item)
        return items

    def _parse_item_config(self, name: str) -> Item | None:
        """Parse a named equipment config into an Item instance."""
        cfg = self.config_manager.items_data.get(name)
        if not cfg:
            cfg = self.config_manager.weapons_data.get(name)
        if not cfg:
            cfg = self.config_manager.heart_methods_data.get(name)
        if not cfg:
            return None

        item_type = cfg.get("type", "")
        subtype = cfg.get("subtype", "")
        if item_type == "法器":
            if subtype == "武器":
                item_type = "weapon"
            elif subtype == "防具":
                item_type = "armor"
            else:
                item_type = "accessory"
        elif item_type == "功法":
            item_type = "technique"
        elif "passive_bonus" in cfg or "skill_pool" in cfg:
            item_type = "main_technique"
        elif "trigger_skill" in cfg or "ultimate" in cfg:
            item_type = "technique"

        def _json_str(value) -> str:
            """Serialize a value to a JSON string (passes strings through; falls back to an empty dict/array literal)."""
            if isinstance(value, str):
                return value
            try:
                return json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                return "{}" if isinstance(value, dict) else "[]"

        damage = cfg.get("damage", 0)
        armor_value = cfg.get("armor_value", 0)
        equip_effects = cfg.get("equip_effects", {})
        attack = equip_effects.get("attack", 0)
        defense = equip_effects.get("defense", 0)
        if attack:
            damage = max(damage, attack)
        if defense:
            armor_value = max(armor_value, defense)

        return Item(
            item_id=cfg.get("id", name),
            name=name,
            item_type=item_type,
            description=cfg.get("description", ""),
            rank=cfg.get("rank", ""),
            required_level_index=cfg.get("required_level_index", 0),
            weapon_category=cfg.get("weapon_category", ""),
            damage=damage,
            agility=cfg.get("agility", 0),
            speed=cfg.get("speed", 0),
            hp=cfg.get("hp", 0),
            armor_value=armor_value,
            weapon_coefficient_k=cfg.get("weapon_coefficient_k", 1.0),
            base_damage=cfg.get("base_damage", 0),
            route_multiplier=_json_str(cfg.get("route_multiplier", {})),
            trigger_skills=_json_str(cfg.get("trigger_skills", [])),
            exp_multiplier=cfg.get("exp_multiplier", 0.0),
            passive_bonus=_json_str(cfg.get("passive_bonus", {})),
            skill_pool=_json_str(cfg.get("skill_pool", [])),
        )

    # ------------------------------------------------------------------
    # Effect registry (spec: combat-core delta, skill-engine-fit-and-content-sync)
    # ------------------------------------------------------------------

    @staticmethod
    def _handler_damage_bonus(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle damage_bonus and combo effects.

        Returns the damage multiplier increment.
        """
        value = skill.get("effect_value", 0)
        effect = skill.get("effect_type", "")
        if effect == "combo" and actor.combo_stack >= state.get("combo_cap", 2):
            return 0.0
        if effect == "combo":
            actor.combo_stack += 1
        return value

    @staticmethod
    def _handler_stun(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle stun effect: skip target's next action."""
        target.skip_next_action = True
        return 0.0

    @staticmethod
    def _handler_counter(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle counter effect on defense: deal immediate damage to attacker.

        The damage log is emitted here, before survive (免死) resolution, so a
        lethal counter reads "反击…造成 N 点伤害" followed by the 免死 line
        (review fix: log ordering).
        """
        value = skill.get("effect_value", 0)
        counter_dmg = max(1, int(actor.damage * value))
        target.hp -= counter_dmg
        state["log"].append(
            f"{actor.name} 触发【{skill.get('name', '反击')}】反击，"
            f"对 {target.name} 造成 {counter_dmg} 点伤害！"
        )
        state["engine"]._try_survive(target, state["log"])
        return 0.0

    @staticmethod
    def _handler_damage_reduction(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle damage_reduction: reduce next incoming attack damage."""
        value = skill.get("effect_value", 0)
        reduction = 1.0 - float(value)
        # Applies to the skill owner (actor), not the opponent. on_defense
        # processing passes (defender, attacker), so the defender's own next
        # incoming hit is reduced. Consumed and reset in
        # _apply_armor_and_reduction.
        actor.incoming_damage_mult *= max(0.0, reduction)
        return 0.0

    @staticmethod
    def _handler_heal(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle heal effect: restore max_hp × heal_percent (default value).

        Vampire mode (``vampire: true``) defers the heal to damage time via
        the ``next_attack_vampire`` one-shot flag.
        """
        value = skill.get("effect_value", 0)
        if skill.get("vampire"):
            actor.next_attack_vampire = value
            return 0.0
        heal_percent = skill.get("heal_percent", value)
        heal = max(1, int(actor.max_hp * heal_percent))
        actor.hp = min(actor.max_hp, actor.hp + heal)
        state["log"].append(
            f"{actor.name} 触发【{skill.get('name', '治疗')}】，恢复 {heal} 气血！"
        )
        return 0.0

    @staticmethod
    def _handler_dot(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle dot: attach a per-round damage status to the target.

        The base damage is snapshotted from the triggering attack's expected
        damage (base + buffed damage × K, times the accumulated damage
        multiplier) so it matches the actual attack even under damage
        buffs/debuffs (review fix). Note: the snapshot uses
        ``state["damage_mult"]`` at this skill's position in the trigger
        loop, so a ``damage_bonus`` skill processed later in the same attack
        phase does not fold into the snapshot (documented limitation).
        """
        value = skill.get("effect_value", 0)
        # Mirror _calc_damage's unarmed fallback so the snapshot matches the
        # expected attack damage exactly (base 5 / K 0.5 without a weapon).
        if actor.base_damage > 0:
            base = actor.base_damage
            k = actor.weapon_k
        else:
            base, k = 5, 0.5
        buffed_damage = int(
            actor.damage * state["engine"]._buff_multiplier(actor, "damage")
        )
        snapshot = max(
            1, int((base + buffed_damage * k) * state.get("damage_mult", 1.0))
        )
        effect = StatusEffect(
            source_name=skill.get("name", "dot"),
            kind="dot",
            effect_value=value,
            tick_rate=skill.get("tick_rate", 1.0),
            duration=skill.get("duration", 1),
            remaining=skill.get("duration", 1),
            snapshot_damage=snapshot,
        )
        applied = state["engine"]._apply_status_effect(target, effect)
        if applied:
            state["log"].append(
                f"{actor.name} 使【{skill.get('name', 'dot')}】附着于 {target.name}"
            )
        return 0.0

    @staticmethod
    def _handler_buff(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle buff: attach a self stat-boost status (duration rounds)."""
        state["engine"]._attach_stat_status(
            actor, skill, kind="buff", log=state["log"], who=actor
        )
        return 0.0

    @staticmethod
    def _handler_debuff(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle debuff: attach a target stat-penalty status."""
        state["engine"]._attach_stat_status(
            actor, skill, kind="debuff", log=state["log"], who=target
        )
        return 0.0

    @staticmethod
    def _handler_fatigue(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle fatigue: self debuff (trade-off for a boost, spec D8)."""
        state["engine"]._attach_stat_status(
            actor, skill, kind="fatigue", log=state["log"], who=actor
        )
        return 0.0

    def _attach_stat_status(
        self,
        actor: FighterState,
        skill: dict,
        *,
        kind: str,
        log: list[str],
        who: FighterState,
    ) -> None:
        """Attach a stat-affecting status (buff/debuff/fatigue)."""
        effect = StatusEffect(
            source_name=skill.get("name", kind),
            kind=kind,
            effect_value=skill.get("effect_value", 0),
            duration=skill.get("duration", 1),
            remaining=skill.get("duration", 1),
            params={"stat": skill.get("stat", "damage")},
        )
        applied = self._apply_status_effect(who, effect)
        if applied:
            log.append(f"{actor.name} 的【{effect.source_name}】作用于 {who.name}")
        else:
            # Cap rejection must not be logged as a successful application
            # (review fix: truthful battle log).
            log.append(
                f"{actor.name} 的【{effect.source_name}】未生效："
                f"同类效果已达叠加上限（{self._status_stack_cap}）"
            )

    @staticmethod
    def _handler_pierce(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle pierce: next attack bypasses armor by pierce_rate (0-1)."""
        rate = min(
            1.0, max(0.0, skill.get("pierce_rate", skill.get("effect_value", 0)))
        )
        actor.next_attack_pierce_rate = max(actor.next_attack_pierce_rate, rate)
        return 0.0

    @staticmethod
    def _handler_unavoidable(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle unavoidable: next attack skips dodge/block/counter checks."""
        actor.next_attack_unavoidable = True
        return 0.0

    @staticmethod
    def _handler_reflect(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle reflect: refund reflect_rate × actual damage (max 1/round)."""
        rate = min(
            1.0, max(0.0, skill.get("reflect_rate", skill.get("effect_value", 0)))
        )
        actor.reflect_rate = max(actor.reflect_rate, rate)
        return 0.0

    @staticmethod
    def _handler_survive(
        actor: FighterState,
        target: FighterState,
        skill: dict,
        state: dict,
    ) -> float:
        """Handle survive: grant lethal-protection charges for this battle."""
        actor.survive_charges += skill.get("survive_count", 1)
        actor.survive_recovery = skill.get("survive_recovery", actor.survive_recovery)
        state["log"].append(f"{actor.name} 获得【{skill.get('name', '免死')}】庇护！")
        return 0.0

    EFFECT_HANDLERS: dict[str, Callable] = {
        "damage_bonus": _handler_damage_bonus,
        "combo": _handler_damage_bonus,
        "stun": _handler_stun,
        "counter": _handler_counter,
        "damage_reduction": _handler_damage_reduction,
        "heal": _handler_heal,
        "dot": _handler_dot,
        "buff": _handler_buff,
        "debuff": _handler_debuff,
        "pierce": _handler_pierce,
        "unavoidable": _handler_unavoidable,
        "survive": _handler_survive,
        "reflect": _handler_reflect,
        "fatigue": _handler_fatigue,
    }

    # ------------------------------------------------------------------
    # Internal resolution
    # ------------------------------------------------------------------

    def _roll_initiative(self, f1: FighterState, f2: FighterState) -> bool:
        """Return True if f1 gets the action, weighted by speed."""
        speed1 = f1.speed * self._buff_multiplier(f1, "speed")
        speed2 = f2.speed * self._buff_multiplier(f2, "speed")
        total_speed = speed1 + speed2
        if total_speed <= 0:
            return random.random() < 0.5
        return random.random() < (speed1 / total_speed)

    def _buff_multiplier(self, fighter: FighterState, stat: str) -> float:
        """Multiplicative modifier from buff/debuff/fatigue status effects.

        Args:
            fighter: The fighter whose status effects are read.
            stat: The affected stat name ("damage" | "armor" | "speed").

        Returns:
            Multiplier (1.0 when no matching status). buff stacks ×(1+value),
            debuff/fatigue ×max(0, 1-value) (spec: battle-status-effects).
        """
        mult = 1.0
        for effect in fighter.status_effects:
            if effect.kind not in ("buff", "debuff", "fatigue"):
                continue
            if effect.params.get("stat", "*") != stat:
                continue
            if effect.kind == "buff":
                mult *= 1.0 + effect.effect_value
            else:
                mult *= max(0.0, 1.0 - effect.effect_value)
        return mult

    def _apply_status_effect(self, fighter: FighterState, effect: StatusEffect) -> bool:
        """Attach a status effect with same-source refresh / cross-source stack cap.

        Args:
            fighter: The target fighter.
            effect: The new status effect.

        Returns:
            True when applied (or refreshed), False when over the stack cap.
        """
        for existing in fighter.status_effects:
            if (
                existing.source_name == effect.source_name
                and existing.kind == effect.kind
            ):
                # Same-source refresh: reset duration, take new values.
                existing.remaining = effect.duration
                existing.effect_value = effect.effect_value
                existing.tick_rate = effect.tick_rate
                existing.snapshot_damage = effect.snapshot_damage
                existing.params = effect.params
                return True
        key = (effect.kind, effect.params.get("stat", "*"))
        stacked = sum(
            1
            for e in fighter.status_effects
            if (e.kind, e.params.get("stat", "*")) == key
        )
        if stacked >= self._status_stack_cap:
            return False
        fighter.status_effects.append(effect)
        return True

    def _tick_status_effects(self, fighter: FighterState, log: list[str]) -> None:
        """Tick persistent status effects at round start (spec: battle-status-effects).

        dot damage is ``max(1, snapshot_damage × effect_value × tick_rate)``;
        durations decrement and expired effects are removed.
        """
        alive: list[StatusEffect] = []
        for effect in fighter.status_effects:
            if effect.kind == "dot":
                dmg = max(
                    1,
                    int(
                        effect.snapshot_damage * effect.effect_value * effect.tick_rate
                    ),
                )
                fighter.hp -= dmg
                log.append(
                    f"{fighter.name} 受【{effect.source_name}】侵蚀，损失 {dmg} 气血！"
                )
                # Lethal dots consume survive charges like any damage source
                # (review fix: funnel through _try_survive).
                self._try_survive(fighter, log)
            effect.remaining -= 1
            if effect.remaining > 0:
                alive.append(effect)
            else:
                log.append(f"{fighter.name} 的【{effect.source_name}】效果消散")
        fighter.status_effects = alive

    def _process_round_start_skills(
        self, fighter: FighterState, log: list[str]
    ) -> None:
        """Resolve round_start trigger skills for a fighter.

        Dispatches through EFFECT_HANDLERS like _process_trigger_skills
        (spec: combat-core delta) so unknown effect_types warn instead of
        being silently ignored. Damage increments accumulate into
        ``next_attack_mult``.
        """
        for skill in fighter.trigger_skills:
            if skill.get("trigger_timing") != "round_start":
                continue
            rate = skill.get("trigger_rate", 0.0)
            if random.random() >= rate:
                continue
            effect = skill.get("effect_type", "")
            skill_name = skill.get("name", "未知")
            # round_start only supports self-buff effects; dispatching others
            # (stun/counter/damage_reduction) with actor == target would
            # produce unexpected self-targeting side effects.
            if effect not in ("damage_bonus", "combo", "buff", "debuff"):
                logger.warning(
                    "effect_type '%s' in round_start skill '%s' is not a "
                    "self-buff effect; skipping.",
                    effect,
                    skill_name,
                )
                continue
            handler = self.EFFECT_HANDLERS.get(effect)
            if handler is None:
                logger.warning(
                    "Unknown effect_type '%s' in round_start skill '%s'; skipping.",
                    effect,
                    skill_name,
                )
                continue
            state = {"combo_cap": self._combo_cap, "log": log, "engine": self}
            dmg_increment = handler(fighter, fighter, skill, state)
            if dmg_increment:
                fighter.next_attack_mult += dmg_increment
                log.append(f"{fighter.name} 触发【{skill_name}】，下回合攻势更盛！")

    def _process_trigger_skills(
        self,
        timing: str,
        actor: FighterState,
        target: FighterState,
        log: list[str],
        *,
        damage_mult: float = 1.0,
        skip_counter: bool = False,
    ) -> dict:
        """Resolve trigger skills of ``actor`` for the given timing.

        Returns a dict with ``damage_mult`` and any control flags. Counter damage
        is applied immediately; stun/damage-reduction are applied to ``target``.
        """
        result = {"damage_mult": damage_mult}
        for skill in actor.trigger_skills:
            if skill.get("trigger_timing") != timing:
                continue
            rate = skill.get("trigger_rate", 0.0)
            if random.random() >= rate:
                continue

            effect = skill.get("effect_type", "")
            skill_name = skill.get("name", "未知")

            # counter is only meaningful on defense; outside on_defense it
            # would deal damage with no log line (legacy if/elif only handled
            # it at on_defense timing). An unavoidable attack also exempts the
            # defender's counter (spec: combat-core).
            if effect == "counter" and (timing != "on_defense" or skip_counter):
                logger.warning(
                    "effect_type 'counter' in skill '%s' outside on_defense; skipping.",
                    skill_name,
                )
                continue

            handler = self.EFFECT_HANDLERS.get(effect)
            if handler is None:
                logger.warning(
                    "Unknown effect_type '%s' in skill '%s'; skipping.",
                    effect,
                    skill_name,
                )
                continue

            state = {
                "combo_cap": self._combo_cap,
                "damage_mult": result["damage_mult"],
                "log": log,
                "engine": self,
            }
            dmg_increment = handler(actor, target, skill, state)
            if dmg_increment:
                result["damage_mult"] += dmg_increment
                log.append(f"{actor.name} 触发【{skill_name}】，攻势更盛！")
            elif effect == "stun":
                log.append(
                    f"{actor.name} 触发【{skill_name}】，"
                    f"{target.name} 被眩晕，下回合无法出手！"
                )
            elif effect == "damage_reduction":
                log.append(f"{actor.name} 触发【{skill_name}】，受到的伤害降低！")
        return result

    def _resolve_attack(
        self,
        attacker: FighterState,
        defender: FighterState,
        dodge_cap: float,
        crit_multiplier: float,
        log: list[str],
        crit_damage_cap: float | None = None,
        round_no: int = 0,
    ) -> None:
        """Resolve a single attack action through the full chain."""
        if crit_damage_cap is None:
            crit_damage_cap = self._crit_damage_cap
        # Reset combo stack for this action
        attacker.combo_stack = 0

        # Stun check: skip this action right
        if attacker.skip_next_action:
            attacker.skip_next_action = False
            log.append(f"{attacker.name} 处于眩晕状态，无法出手！")
            return

        # One-shot unavoidable flag (consumed on this attack, spec: combat-core)
        unavoidable = attacker.next_attack_unavoidable
        attacker.next_attack_unavoidable = False

        # 1. Dodge (exempt when unavoidable)
        dodge_rate = self._calc_dodge_rate(attacker, defender, dodge_cap)
        if not unavoidable and random.random() < dodge_rate:
            log.append(f"{defender.name} 身形一闪，躲过了 {attacker.name} 的攻击！")
            return

        # 2. Block (simplified: 10% base + equipment bonuses; exempt when unavoidable)
        block_rate = self._calc_block_rate(defender)
        blocked = (not unavoidable) and random.random() < block_rate
        if blocked:
            log.append(f"{defender.name} 举盾格挡，化解了部分攻势！")

        # 3. Crit (capped crit rate)
        effective_crit_rate = min(attacker.crit_rate, self._crit_rate_cap)
        is_crit = random.random() < effective_crit_rate
        if is_crit:
            log.append(f"{attacker.name} 目光如电，寻得破绽！")

        skill_mult = 1.0

        # 4. Trigger skills - on_crit
        if is_crit:
            crit_result = self._process_trigger_skills(
                "on_crit", attacker, defender, log, damage_mult=skill_mult
            )
            skill_mult = crit_result["damage_mult"]

        # 5. Trigger skills - on_attack
        attack_result = self._process_trigger_skills(
            "on_attack", attacker, defender, log, damage_mult=skill_mult
        )
        skill_mult = attack_result["damage_mult"]

        # 6. Ultimate (once per battle per ultimate)
        # Unlock check: min_action_index + optional HP thresholds (AND logic)
        ultimate_mult = 1.0
        for ult in attacker.ultimates:
            ult_id = ult.get("id", "")
            if ult_id in attacker.used_ultimates:
                continue
            # Unlock threshold checks
            min_actions = ult.get("min_action_index", 0)
            if attacker.action_count < min_actions:
                continue
            self_hp_threshold = ult.get("trigger_self_hp_below", 1.0)
            if attacker.hp / max(1, attacker.max_hp) > self_hp_threshold:
                continue
            opp_hp_threshold = ult.get("trigger_opponent_hp_below", 1.0)
            if defender.hp / max(1, defender.max_hp) > opp_hp_threshold:
                continue
            rate = ult.get("trigger_rate", 0.0)
            if random.random() < rate:
                attacker.used_ultimates.add(ult_id)
                ult_name = ult.get("name", "绝招")
                # Dispatch through the shared EFFECT_HANDLERS registry
                # (spec: skill-system delta). Legacy ultimates carry no
                # effect_type: default to damage_bonus for backwards
                # compatibility (adds effect_value to ultimate_mult).
                effect = ult.get("effect_type", "damage_bonus")
                handler = self.EFFECT_HANDLERS.get(effect)
                if handler is None:
                    logger.warning(
                        "Unknown effect_type '%s' in ultimate '%s'; "
                        "falling back to damage_bonus.",
                        effect,
                        ult_name,
                    )
                    effect = "damage_bonus"
                    handler = self.EFFECT_HANDLERS[effect]
                log.append(f"{attacker.name} 施展大招【{ult_name}】，天地变色！")
                state = {
                    "combo_cap": self._combo_cap,
                    "damage_mult": ultimate_mult,
                    "log": log,
                    "engine": self,
                }
                ultimate_mult += handler(attacker, defender, ult, state)
                break  # Only one ultimate per action

        # Apply round-start / previous defensive multipliers
        total_skill_mult = skill_mult * ultimate_mult * attacker.next_attack_mult
        attacker.next_attack_mult = 1.0

        # 7. Damage calculation (Muxxu formula)
        # Cap crit multiplier
        effective_crit_mult = min(crit_multiplier, crit_damage_cap)
        buffed_damage = int(attacker.damage * self._buff_multiplier(attacker, "damage"))
        raw_damage = self._calc_damage(
            buffed_damage,
            attacker.weapon_k,
            attacker.base_damage,
            total_skill_mult,
            is_crit,
            effective_crit_mult,
        )

        # Apply block reduction
        if blocked:
            raw_damage = max(1, raw_damage // 2)

        # Pierce: attacker's next-attack armor bypass (one-shot, spec D-pierce)
        pierce_rate = attacker.next_attack_pierce_rate
        attacker.next_attack_pierce_rate = 0.0

        # Apply percent armor reduction + damage reduction cap
        final_damage = self._apply_armor_and_reduction(
            defender, raw_damage, pierce_rate=pierce_rate
        )

        defender.hp -= final_damage

        if is_crit:
            log.append(f"{attacker.name} 暴击！造成 {final_damage} 点伤害！")
        else:
            log.append(f"{attacker.name} 发起攻击，造成 {final_damage} 点伤害")

        # Reflect: refund fraction of actual damage back to the attacker
        # (max once per round, never reflects reflect).
        if defender.reflect_rate > 0 and defender.reflect_round != round_no:
            defender.reflect_round = round_no
            reflect_dmg = max(1, int(final_damage * defender.reflect_rate))
            attacker.hp -= reflect_dmg
            log.append(f"{defender.name} 反弹 {reflect_dmg} 点伤害！")
            self._try_survive(attacker, log)

        # Vampire heal-back (one-shot, from heal/vampire effect)
        if attacker.next_attack_vampire > 0:
            heal = max(1, int(final_damage * attacker.next_attack_vampire))
            attacker.hp = min(attacker.max_hp, attacker.hp + heal)
            log.append(f"{attacker.name} 吸取 {heal} 气血！")
            attacker.next_attack_vampire = 0.0

        # Survive (免死): lethal damage keeps the fighter at 1 HP once per charge
        self._try_survive(defender, log)

        log.append(f"{defender.name} 剩余气血: {max(0, defender.hp)}")

        # 8. Trigger skills - on_defense (counter / stun / damage reduction)
        if defender.hp > 0:
            self._process_trigger_skills(
                "on_defense",
                defender,
                attacker,
                log,
                skip_counter=unavoidable,
            )

    def _try_survive(self, fighter: FighterState, log: list[str]) -> None:
        """Apply the survive (免死) effect when hp dropped to zero.

        Args:
            fighter: The fighter whose hp is being checked.
            log: Battle log to append to.
        """
        if fighter.hp > 0 or fighter.survive_charges <= 0:
            return
        fighter.survive_charges -= 1
        fighter.hp = 1
        if fighter.survive_recovery > 0:
            fighter.hp = min(
                fighter.max_hp,
                fighter.hp + int(fighter.max_hp * fighter.survive_recovery),
            )
        log.append(f"{fighter.name} 触发【免死】，于绝境中存活！")

    def _calc_dodge_rate(
        self, attacker: FighterState, defender: FighterState, cap: float
    ) -> float:
        """Calculate dodge rate based on agility difference, capped."""
        if defender.agility <= 0:
            return 0.0
        # Base dodge: 5% + agility difference bonus
        # For every 10 points of agility advantage, +5% dodge (up to cap)
        diff = defender.agility - attacker.agility
        rate = 0.05 + diff * 0.005  # 5% base + 0.5% per point difference
        return min(max(rate, 0.0), cap)

    def _calc_block_rate(self, defender: FighterState) -> float:
        """Calculate block rate from armor and skills, capped by config."""
        # Base 5% + small bonus from armor
        return min(0.05 + defender.armor_value * 0.001, self._block_cap)

    def _calc_damage(
        self,
        damage_attr: int,
        weapon_k: float,
        base_damage: int,
        skill_multiplier: float,
        is_crit: bool,
        crit_multiplier: float,
    ) -> int:
        """Muxxu-style damage formula.

        Damage = floor((base_dmg + dmg_attr * K) * skill_mult * random(0.95-1.05))
        """
        # Unarmed fallback: if no weapon, use small base damage
        if base_damage <= 0:
            base_damage = 5  # Unarmed base damage
            weapon_k = 0.5  # Unarmed K

        base = base_damage + damage_attr * weapon_k
        randomized = base * random.uniform(0.95, 1.05)
        multiplied = randomized * skill_multiplier

        if is_crit:
            multiplied *= crit_multiplier

        return max(1, math.floor(multiplied))

    def _apply_armor_and_reduction(
        self, defender: FighterState, raw_damage: int, pierce_rate: float = 0.0
    ) -> int:
        """Apply percent armor reduction and capped damage reduction.

        Formula: 减伤率 = 护甲 / (护甲 + K), K = armor_k_base + armor_k_level_coeff * 等级
        Total damage fraction = (1 - armor_rate) * incoming_damage_mult
        Capped by damage_reduction_cap (block halving already applied before this).
        pierce_rate (0-1) bypasses that fraction of the armor reduction.
        """
        # Percent armor reduction
        armor_k = self._armor_k_base + self._armor_k_level_coeff * defender.level_index
        eff_armor = defender.armor_value * self._buff_multiplier(defender, "armor")
        if armor_k <= 0 or eff_armor <= 0:
            armor_rate = 0.0
        else:
            armor_rate = eff_armor / (eff_armor + armor_k)
        armor_rate *= 1.0 - min(1.0, max(0.0, pierce_rate))

        # Skill damage reduction (already multiplicative in incoming_damage_mult)
        skill_fraction = defender.incoming_damage_mult
        defender.incoming_damage_mult = 1.0  # Reset after consumption

        # Combined fraction: armor and skill reductions multiply
        total_fraction = (1.0 - armor_rate) * skill_fraction

        # Cap total reduction: total_fraction >= 1 - damage_reduction_cap
        min_fraction = 1.0 - self._damage_reduction_cap
        total_fraction = max(total_fraction, min_fraction)

        return max(1, math.floor(raw_damage * total_fraction))

    def _merge_log(self, log: list[str], chunk_size: int) -> list[str]:
        """Merge log entries into chunks of approximately chunk_size lines."""
        if chunk_size <= 0:
            chunk_size = 10

        merged: list[str] = []
        current_chunk: list[str] = []

        for entry in log:
            current_chunk.append(entry)
            if len(current_chunk) >= chunk_size:
                merged.append("\n".join(current_chunk))
                current_chunk = []

        if current_chunk:
            merged.append("\n".join(current_chunk))

        return merged


# Legacy adapter for backward compatibility during migration
class CombatManager:
    """Legacy adapter that delegates to the new CombatEngine.

    Maintains backward compatibility with existing code while
    the migration to CombatEngine is in progress.
    """

    def __init__(
        self, config_manager: ConfigManager, skill_manager: SkillManager | None = None
    ):
        self.engine = CombatEngine(config_manager, skill_manager)
        self.config_manager = config_manager

    @staticmethod
    def calculate_hp_mp(
        experience: int, hp_buff: float = 0.0, mp_buff: float = 0.0
    ) -> tuple[int, int]:
        """Legacy HP/MP calculation (deprecated, kept for compatibility)."""
        base_hp = experience // 2
        hp = int(base_hp * (1 + hp_buff))
        mp = int(experience * (1 + mp_buff))
        return hp, mp

    def _get_merge_count(self, player) -> int:
        """Return the player's battle report merge count preference.

        Falls back to the game_config default if the player has not set one.
        """
        default = self.engine._skill_cfg.get("battle_report_merge_count", 10)
        if hasattr(player, "battle_report_merge_count"):
            val = getattr(player, "battle_report_merge_count", 0)
            if isinstance(val, int) and val > 0:
                return max(1, min(50, val))
        return default

    @staticmethod
    def calculate_turn_attack(
        base_atk: int, crit_rate: int = 0, atk_buff: float = 0.0
    ) -> tuple[bool, int]:
        """Legacy turn attack calculation (deprecated, kept for compatibility).

        Args:
            base_atk: Base attack value
            crit_rate: Crit rate as integer percentage (0-100)
            atk_buff: Attack buff multiplier

        Returns:
            (is_crit, damage) tuple
        """
        damage = int(round(random.uniform(0.95, 1.05), 2) * base_atk * (1 + atk_buff))
        is_crit = random.randint(0, 99) < crit_rate
        if is_crit:
            damage = int(damage * 1.5)
        return is_crit, damage

    @staticmethod
    def apply_damage_reduction(damage: int, defense: int = 0) -> int:
        """Legacy damage reduction (deprecated, kept for compatibility)."""
        if defense <= 0:
            return damage
        reduction_rate = defense / (defense + 100)
        final_damage = int(damage * (1 - reduction_rate))
        return max(1, final_damage)

    @staticmethod
    def calculate_atk(
        experience: int, atkpractice: int = 0, atk_buff: float = 0.0
    ) -> int:
        """Legacy ATK calculation (deprecated, kept for compatibility)."""
        base_atk = experience // 10
        practice_bonus = atkpractice * 0.04
        return max(int(base_atk * (1 + practice_bonus + atk_buff)), 1)

    async def player_vs_player(
        self, player1: Player, player2: Player, combat_type: int = 1
    ) -> dict:
        """Legacy PvP entry point (combat_type: 1=spar, 2=duel)."""
        f1 = await self.engine.build_fighter_from_player(player1, is_attacker=True)
        f2 = await self.engine.build_fighter_from_player(player2, is_attacker=False)

        combat_type_str = "duel" if combat_type == 2 else "spar"
        merge_count = self._get_merge_count(player1)
        result = self.engine.resolve_combat(
            f1, f2, combat_type_str, merge_count=merge_count
        )

        # Map to legacy return format
        return {
            "winner": result.winner,
            "combat_log": result.combat_log,
            "player1_final_hp": (
                player1.hp if combat_type == 1 else max(1, result.fighter1_final_hp)
            ),
            "player1_final_mp": player1.hp,  # Legacy MP = HP in new system
            "player2_final_hp": (
                player2.hp if combat_type == 1 else max(1, result.fighter2_final_hp)
            ),
            "player2_final_mp": player2.hp,
            "rounds": result.rounds,
        }

    async def player_vs_boss(self, player: Player, boss: Player) -> dict:
        """Legacy PvE entry point (Boss battle)."""
        f1 = await self.engine.build_fighter_from_player(player, is_attacker=True)
        f2 = await self.engine.build_fighter_from_player(boss, is_attacker=False)

        merge_count = self._get_merge_count(player)
        result = self.engine.resolve_combat(f1, f2, "pve", merge_count=merge_count)

        # Calculate reward based on damage dealt
        damage_dealt = f2.max_hp - result.fighter2_final_hp
        damage_ratio = damage_dealt / f2.max_hp if f2.max_hp > 0 else 0
        reward = (
            int(boss.experience * damage_ratio)
            if result.winner != player.user_id
            else boss.experience
        )

        return {
            "winner": result.winner,
            "combat_log": result.combat_log,
            "player_final_hp": max(1, result.fighter1_final_hp),
            "player_final_mp": player.hp,
            "boss_final_hp": result.fighter2_final_hp,
            "reward": reward,
            "rounds": result.rounds,
        }

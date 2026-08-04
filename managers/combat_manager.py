"""Unified combat engine for PvP (spar/duel/impart PK) and PvE.

Implements the spec-driven combat-core requirements:
- Speed-weighted initiative: P(A acts) = speed_A / (speed_A + speed_B)
- Muxxu damage formula: floor((base_dmg + dmg_attr * K) * skill_mult * random - armor)
- Unified resolution chain: dodge -> block -> crit -> trigger -> ultimate -> damage
- Trigger skill timings: on_attack, on_defense, on_crit, round_start
- Control effects: stun skips the next action right
- Counter effects trigger on defense
- Battle report merged into chunks (configurable, default 10)
- Action limit with draw (default 200)
"""

from __future__ import annotations

import json
import math
import os
import random
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
                self._process_round_start_skills(fighter1, log)
                self._process_round_start_skills(fighter2, log)

            # Determine who acts this action (speed-weighted, independent each action)
            if self._roll_initiative(fighter1, fighter2):
                self._resolve_attack(
                    fighter1, fighter2, dodge_cap, crit_multiplier, log
                )
            else:
                self._resolve_attack(
                    fighter2, fighter1, dodge_cap, crit_multiplier, log
                )
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
    # Internal resolution
    # ------------------------------------------------------------------

    def _roll_initiative(self, f1: FighterState, f2: FighterState) -> bool:
        """Return True if f1 gets the action, weighted by speed."""
        total_speed = f1.speed + f2.speed
        if total_speed <= 0:
            return random.random() < 0.5
        return random.random() < (f1.speed / total_speed)

    def _process_round_start_skills(
        self, fighter: FighterState, log: list[str]
    ) -> None:
        """Resolve round_start trigger skills for a fighter."""
        for skill in fighter.trigger_skills:
            if skill.get("trigger_timing") != "round_start":
                continue
            rate = skill.get("trigger_rate", 0.0)
            if random.random() >= rate:
                continue
            effect = skill.get("effect_type", "")
            value = skill.get("effect_value", 0)
            if effect == "combo" and fighter.combo_stack >= self._combo_cap:
                continue
            if effect in ("damage_bonus", "combo"):
                if effect == "combo":
                    fighter.combo_stack += 1
                fighter.next_attack_mult += value
                log.append(
                    f"{fighter.name} 触发【{skill.get('name', '未知')}】，"
                    f"下回合攻势更盛！"
                )

    def _process_trigger_skills(
        self,
        timing: str,
        actor: FighterState,
        target: FighterState,
        log: list[str],
        *,
        damage_mult: float = 1.0,
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
            value = skill.get("effect_value", 0)
            skill_name = skill.get("name", "未知")

            if effect in ("damage_bonus", "combo"):
                if effect == "combo" and actor.combo_stack >= self._combo_cap:
                    continue
                if effect == "combo":
                    actor.combo_stack += 1
                result["damage_mult"] += value
                log.append(f"{actor.name} 触发【{skill_name}】，攻势更盛！")
            elif effect == "stun":
                target.skip_next_action = True
                log.append(
                    f"{actor.name} 触发【{skill_name}】，"
                    f"{target.name} 被眩晕，下回合无法出手！"
                )
            elif effect == "counter" and timing == "on_defense":
                counter_dmg = max(1, int(actor.damage * value))
                target.hp -= counter_dmg
                log.append(
                    f"{actor.name} 触发【{skill_name}】反击，"
                    f"对 {target.name} 造成 {counter_dmg} 点伤害！"
                )
            elif effect == "damage_reduction":
                # Reduces the next incoming attack damage
                reduction = 1.0 - float(value)
                target.incoming_damage_mult *= max(0.0, reduction)
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

        # 1. Dodge
        dodge_rate = self._calc_dodge_rate(attacker, defender, dodge_cap)
        if random.random() < dodge_rate:
            log.append(f"{defender.name} 身形一闪，躲过了 {attacker.name} 的攻击！")
            return

        # 2. Block (simplified: 10% base + equipment bonuses)
        block_rate = self._calc_block_rate(defender)
        blocked = random.random() < block_rate
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
        ultimate_mult = 1.0
        for ult in attacker.ultimates:
            ult_id = ult.get("id", "")
            if ult_id in attacker.used_ultimates:
                continue
            rate = ult.get("trigger_rate", 0.0)
            if random.random() < rate:
                attacker.used_ultimates.add(ult_id)
                ultimate_mult += ult.get("effect_value", 0.5)
                log.append(
                    f"{attacker.name} 施展大招【{ult.get('name', '绝招')}】，天地变色！"
                )
                break  # Only one ultimate per action

        # Apply round-start / previous defensive multipliers
        total_skill_mult = skill_mult * ultimate_mult * attacker.next_attack_mult
        attacker.next_attack_mult = 1.0

        # 7. Damage calculation (Muxxu formula)
        # Cap crit multiplier
        effective_crit_mult = min(crit_multiplier, crit_damage_cap)
        raw_damage = self._calc_damage(
            attacker.damage,
            attacker.weapon_k,
            attacker.base_damage,
            total_skill_mult,
            is_crit,
            effective_crit_mult,
        )

        # Apply block reduction
        if blocked:
            raw_damage = max(1, raw_damage // 2)

        # Apply percent armor reduction + damage reduction cap
        final_damage = self._apply_armor_and_reduction(defender, raw_damage)

        defender.hp -= final_damage

        if is_crit:
            log.append(f"{attacker.name} 暴击！造成 {final_damage} 点伤害！")
        else:
            log.append(f"{attacker.name} 发起攻击，造成 {final_damage} 点伤害")
        log.append(f"{defender.name} 剩余气血: {max(0, defender.hp)}")

        # 8. Trigger skills - on_defense (counter / stun / damage reduction)
        if defender.hp > 0:
            self._process_trigger_skills("on_defense", defender, attacker, log)

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
        self, defender: FighterState, raw_damage: int
    ) -> int:
        """Apply percent armor reduction and capped damage reduction.

        Formula: 减伤率 = 护甲 / (护甲 + K), K = armor_k_base + armor_k_level_coeff * 等级
        Total damage fraction = (1 - armor_rate) * incoming_damage_mult
        Capped by damage_reduction_cap (block halving already applied before this).
        """
        # Percent armor reduction
        armor_k = self._armor_k_base + self._armor_k_level_coeff * defender.level_index
        if armor_k <= 0 or defender.armor_value <= 0:
            armor_rate = 0.0
        else:
            armor_rate = defender.armor_value / (defender.armor_value + armor_k)

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

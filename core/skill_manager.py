# core/skill_manager.py
"""Skill system manager: comprehension, star-up, heart method passive bonuses.

This module handles the skill acquisition and management layer:
- Building the comprehension pool from heart method skill pools + study target +
  universal pool (breakthrough channel only).
- Three comprehension channels: breakthrough success/fail, cultivation.
- Star-up for duplicate skills.
- Heart method passive bonus application.
- Equipment validation (learned check, slot limit).
- Battle loadout export for the combat engine (Group 4).
"""

from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config_manager import ConfigManager
    from ..data import DataBase
    from ..models import Player


class SkillManager:
    """Manages skill comprehension, star-up, and heart method passives."""

    # Star-up multiplier: each star level adds this percentage to trigger rate/effect.
    STAR_UP_BONUS = 0.10

    def __init__(self, config_manager: ConfigManager, db: DataBase | None = None):
        self.config_manager = config_manager
        self.db = db
        self._skill_cfg = config_manager.game_config.get("skill_system", {})

    # ------------------------------------------------------------------
    # Comprehension pool building
    # ------------------------------------------------------------------

    async def _build_comprehension_pool(
        self,
        player: Player,
        channel: str,  # "breakthrough_success" | "breakthrough_fail" | "cultivation"
    ) -> list[dict]:
        """Build the comprehension pool for a given channel.

        Pool composition (design D4 / spec skill-system):
        - Heart method skill pool (uniform selection; coefficient only affects
          success probability, not selection weight).
        - Study target (if set and not yet learned).
        - Sect exclusive pool (all channels; only while the player belongs to
          a sect whose faction configures ``skill_pool``).
        - Universal pool is intentionally excluded here; it is handled by a
          separate independent roll in breakthrough channels.

        Returns a list of dicts:
        {"skill_id": str, "weight": float, "coefficient": float, "source": str}.
        """
        pool: list[dict] = []

        # 1. Heart method skill pool
        heart_method_name = player.main_technique
        if heart_method_name:
            heart_method = self.config_manager.heart_methods_data.get(heart_method_name)
            if heart_method:
                skill_pool = heart_method.get("skill_pool", [])
                for entry in skill_pool:
                    skill_id = entry.get("skill_id")
                    coeff = entry.get("learn_coefficient", 1.0)
                    if skill_id:
                        pool.append(
                            {
                                "skill_id": skill_id,
                                "weight": 1.0,
                                "coefficient": coeff,
                                "source": "heart_method",
                            }
                        )

        # 2. Study target
        study_target = player.study_target
        if study_target and not await self._is_skill_learned(player, study_target):
            pool.append(
                {
                    "skill_id": study_target,
                    "weight": 1.0,
                    "coefficient": 1.0,
                    "source": "study_target",
                }
            )

        # 3. Sect exclusive skill pool (spec skill-system MODIFIED): injected
        # for every comprehension channel while the player belongs to a sect
        # whose faction configures ``skill_pool``.
        faction_id = await self._get_player_faction_id(player)
        for skill in self._get_sect_pool_skills(faction_id):
            pool.append(
                {
                    "skill_id": str(skill["id"]),
                    "weight": 1.0,
                    "coefficient": skill.get("learn_coefficient", 1.0),
                    "source": "sect",
                    "origin_sect_id": faction_id,
                    "sect_bound": True,
                }
            )

        return pool

    async def _get_player_faction_id(self, player: Player) -> str | None:
        """Resolve the faction_id of the player's sect (None when sectless or a player-built sect)."""
        sect_id = getattr(player, "sect_id", 0)
        if not isinstance(sect_id, int) or not sect_id:
            return None
        if self.db is None or self.db.ext is None:
            return None
        sect = await self.db.ext.get_sect_by_id(sect_id)
        if sect is None:
            return None
        return getattr(sect, "faction_id", None)

    def _get_sect_pool_skills(self, faction_id: str | None) -> list[dict]:
        """Return skill definitions of the faction's exclusive skill pool (empty when unconfigured)."""
        if not faction_id:
            return []
        sect_factions = getattr(self.config_manager, "sect_factions", None) or {}
        pool_name = None
        for faction in sect_factions.get("factions", []):
            if isinstance(faction, dict) and faction.get("id") == faction_id:
                pool_name = faction.get("skill_pool")
                break
        if not pool_name:
            return []
        return [
            skill
            for skill in self.config_manager.skills_data.values()
            if isinstance(skill, dict)
            and skill.get("_group") == pool_name
            and skill.get("id")
        ]

    async def _is_skill_learned(self, player: Player, skill_id: str) -> bool:
        """Check if a skill is already learned by the player."""
        if self.db is None or self.db.ext is None:
            return False
        return await self.db.ext.is_skill_learned(player.user_id, skill_id)

    # ------------------------------------------------------------------
    # Comprehension roll helpers
    # ------------------------------------------------------------------

    def _roll_comprehension(self, pool: list[dict], base_rate: float) -> dict | None:
        """Uniform random draw from the comprehension pool.

        The learn coefficient only affects the success probability:
        actual comprehension rate = base_rate * coefficient.
        Selection is uniform (fixed weight) so a coefficient of 0.2 gives
        exactly one-fifth the success probability of coefficient 1.0.
        """
        if not pool:
            return None

        # Uniform selection: every pool entry has the same chance to be drawn.
        chosen = random.choice(pool)
        coefficient = chosen.get("coefficient", 1.0)
        actual_rate = base_rate * coefficient
        if random.random() < actual_rate:
            return chosen
        return None

    # ------------------------------------------------------------------
    # Public comprehension API (three channels)
    # ------------------------------------------------------------------

    async def roll_breakthrough_success_comprehension(
        self, player: Player
    ) -> dict | None:
        """Comprehension roll on breakthrough success.

        With an equipped heart method: first roll the heart-method pool +
        study target. If a skill is learned, an independent 5% roll decides
        whether the result is replaced by a universal-pool skill.
        Without a heart method, the normal pool is empty and the universal
        fallback is handled by ``roll_universal_pool_breakthrough``.

        Returns the learned skill definition (from skills_data) or None.
        """
        if not player.main_technique:
            return None

        base_rate = self._skill_cfg.get("breakthrough_success_learn_rate", 0.20)
        pool = await self._build_comprehension_pool(player, "breakthrough_success")
        chosen = self._roll_comprehension(pool, base_rate)
        if chosen is None:
            return None

        universal_rate = self._skill_cfg.get("universal_pool_rate", 0.05)
        if random.random() < universal_rate:
            universal_skill = await self._pick_universal_skill(player)
            if universal_skill:
                return await self._resolve_and_learn(
                    player,
                    {
                        "skill_id": universal_skill["id"],
                        "source": "universal",
                    },
                )

        return await self._resolve_and_learn(player, chosen)

    async def roll_breakthrough_fail_comprehension(self, player: Player) -> dict | None:
        """Comprehension roll on breakthrough failure ("破而后立").

        Uses the same pool rules as ``roll_breakthrough_success_comprehension``
        with the fail base rate.
        """
        if not player.main_technique:
            return None

        base_rate = self._skill_cfg.get("breakthrough_fail_learn_rate", 0.10)
        pool = await self._build_comprehension_pool(player, "breakthrough_fail")
        chosen = self._roll_comprehension(pool, base_rate)
        if chosen is None:
            return None

        universal_rate = self._skill_cfg.get("universal_pool_rate", 0.05)
        if random.random() < universal_rate:
            universal_skill = await self._pick_universal_skill(player)
            if universal_skill:
                return await self._resolve_and_learn(
                    player,
                    {
                        "skill_id": universal_skill["id"],
                        "source": "universal",
                    },
                )

        return await self._resolve_and_learn(player, chosen)

    async def roll_cultivation_comprehension(
        self, player: Player, hours: int
    ) -> list[dict]:
        """Comprehension roll on cultivation end.

        Rolls once every `cultivation_learn_interval_hours` (default 2h).
        MUST NOT access the universal pool (spec requirement).
        Returns a list of learned skill definitions (can be multiple if very long).
        """
        interval = self._skill_cfg.get("cultivation_learn_interval_hours", 2)
        base_rate = self._skill_cfg.get("cultivation_learn_rate", 0.15)
        roll_count = hours // interval

        results: list[dict] = []
        for _ in range(roll_count):
            pool = await self._build_comprehension_pool(player, "cultivation")
            chosen = self._roll_comprehension(pool, base_rate)
            if chosen:
                learned = await self._resolve_and_learn(player, chosen)
                if learned:
                    results.append(learned)
        return results

    # ------------------------------------------------------------------
    # Universal pool fallback (no heart method equipped)
    # ------------------------------------------------------------------

    async def roll_universal_pool_breakthrough(
        self, player: Player, success: bool
    ) -> dict | None:
        """Independent universal pool roll for breakthrough (no heart method).

        When player has no heart method equipped, the normal comprehension
        pool is empty. This method provides the 3% fallback (design D4).
        Called separately from the main comprehension roll.

        The sect exclusive pool is injected into the candidate set under the
        same 3% gate when the player belongs to a sect with a configured
        ``skill_pool`` (spec MODIFIED: sect pool applies to all channels).

        The ``success`` parameter is kept for API compatibility but the rate
        is always ``universal_pool_no_heart_rate`` (3%) when no heart
        method is equipped.
        """
        if player.main_technique:
            return None  # Has heart method, use normal pool

        base_rate = self._skill_cfg.get("universal_pool_no_heart_rate", 0.03)

        # Candidates are copies so the shared config definitions are never
        # mutated; sect pool entries are tagged with their attribution.
        candidates: list[dict] = [
            dict(skill) for skill in await self._list_universal_skills(player)
        ]
        faction_id = await self._get_player_faction_id(player)
        for skill in self._get_sect_pool_skills(faction_id):
            candidates.append(
                dict(skill, _fallback_source="sect", _origin_sect_id=faction_id)
            )
        if not candidates:
            return None

        if random.random() < base_rate:
            chosen = random.choice(candidates)
            entry: dict = {
                "skill_id": str(chosen["id"]),
                "source": chosen.get("_fallback_source", "universal_fallback"),
            }
            if entry["source"] == "sect":
                entry["origin_sect_id"] = chosen.get("_origin_sect_id")
                entry["sect_bound"] = True
            return await self._resolve_and_learn(player, entry)
        return None

    async def _list_universal_skills(self, player: Player) -> list[dict]:
        """List unlearned skills from the universal pool."""
        return [
            skill
            for skill in self.config_manager.skills_data.values()
            if skill.get("_group") == "通用功法池"
            and skill.get("id")
            and not await self._is_skill_learned(player, skill["id"])
        ]

    async def _pick_universal_skill(self, player: Player) -> dict | None:
        """Pick a random unlearned skill from the universal pool.

        Returns the skill definition or None if all universal skills are
        already learned or the pool is empty.
        """
        universal_skills = await self._list_universal_skills(player)
        if not universal_skills:
            return None
        return random.choice(universal_skills)

    # ------------------------------------------------------------------
    # Learn / star-up logic
    # ------------------------------------------------------------------

    async def _resolve_and_learn(self, player: Player, chosen: dict) -> dict | None:
        """Resolve a chosen skill ID to its full definition and update player state.

        Handles star-up for duplicates. Clears study_target if matched.
        Returns the skill definition (with current star level) or None.
        """
        if self.db is None or self.db.ext is None:
            return None

        skill_id = chosen["skill_id"]
        source = chosen.get("source", "")

        # Find skill definition across all categories
        skill_def = self._find_skill_definition(skill_id)
        if skill_def is None:
            return None

        max_star = self._skill_cfg.get("max_star", 3)
        # Pre-compute the max-star duplicate compensation so the exp grant
        # commits in the same transaction as the comprehension record.
        compensation = self._calc_star_compensation(skill_def)
        # Sect-pool skills carry origin attribution (spec: 宗门功法归属标记).
        learn_kwargs: dict = {}
        if chosen.get("sect_bound"):
            learn_kwargs["origin_sect_id"] = chosen.get("origin_sect_id")
            learn_kwargs["sect_bound"] = True
        is_new, star_level = await self.db.ext.learn_or_star_up(
            player.user_id,
            skill_id,
            source,
            max_star=max_star,
            max_star_exp_compensation=compensation,
            **learn_kwargs,
        )

        # Clear study target if matched
        if player.study_target == skill_id:
            player.study_target = ""

        # Build result with star-level multipliers
        result = self._apply_star_to_def(skill_def, star_level)
        result["learn_source"] = source
        result["is_new_learn"] = is_new

        # Max-star duplicate compensation (spec D5). The exp grant was
        # already committed atomically inside learn_or_star_up.
        if not is_new and star_level >= max_star and compensation > 0:
            result["max_star_compensation"] = compensation
            result["compensation_message"] = (
                f"【{result.get('name', skill_id)}】已达{max_star}星圆满，"
                f"参悟所得折算为 {compensation} 点修为。"
            )

        return result

    def _find_skill_definition(self, skill_id: str) -> dict | None:
        """Find a skill definition by ID across all skill categories."""
        for skill in self.config_manager.skills_data.values():
            if isinstance(skill, dict) and skill.get("id") == skill_id:
                return skill
        return None

    def _apply_star_to_def(self, skill_def: dict, star_level: int) -> dict:
        """Return a skill definition with star-level multipliers applied.

        Trigger rate and effect value are boosted by star level using
        multiplicative scaling: base * (1 + STAR_UP_BONUS) ^ (star - 1).
        Trigger rate is capped at 1.0. Ultimate trigger_rate defaults to 1.0
        (must-release) if not explicitly set in config.
        A normalized ``trigger_timing`` key is injected so the combat engine
        can filter skills by phase (on_attack / on_defense / on_crit /
        round_start / ultimate).
        """
        result = dict(skill_def)
        trigger = result.get("trigger_skill")
        if trigger:
            rate = trigger.get("trigger_rate", 0.0)
            value = trigger.get("effect_value", 0.0)
            coeff = self._skill_cfg.get("star_up_bonus", self.STAR_UP_BONUS)
            bonus = (1 + coeff) ** (star_level - 1)
            trigger = dict(trigger)
            trigger["trigger_rate"] = min(rate * bonus, 1.0)
            trigger["effect_value"] = value * bonus
            trigger["star_level"] = star_level
            # Default effect_type for configs predating the registry (spec 6.1)
            trigger.setdefault("effect_type", "damage_bonus")
            # Normalize timing for the combat engine
            condition = trigger.get("trigger_condition", "")
            timing_map = {
                "attack": "on_attack",
                "defend": "on_defense",
                "crit": "on_crit",
                "round_start": "round_start",
                "once_per_battle": "ultimate",
            }
            trigger["trigger_timing"] = timing_map.get(condition, condition)
            result["trigger_skill"] = trigger

        ultimate = result.get("ultimate")
        if ultimate:
            value = ultimate.get("effect_value", 0.0)
            coeff = self._skill_cfg.get("star_up_bonus", self.STAR_UP_BONUS)
            bonus = (1 + coeff) ** (star_level - 1)
            ultimate = dict(ultimate)
            ultimate["effect_value"] = value * bonus
            ultimate["star_level"] = star_level
            # Default effect_type for legacy ultimates (spec 5.2)
            ultimate.setdefault("effect_type", "damage_bonus")
            # Default trigger_rate to 1.0 for must-release ultimates (spec D2)
            if "trigger_rate" not in ultimate:
                ultimate["trigger_rate"] = 1.0
            condition = ultimate.get("trigger_condition", "once_per_battle")
            timing_map = {
                "attack": "on_attack",
                "defend": "on_defense",
                "crit": "on_crit",
                "round_start": "round_start",
                "once_per_battle": "ultimate",
            }
            ultimate["trigger_timing"] = timing_map.get(condition, condition)
            result["ultimate"] = ultimate

        result["current_star_level"] = star_level
        return result

    # ------------------------------------------------------------------
    # Star compensation for max-star duplicates
    # ------------------------------------------------------------------

    def _calc_star_compensation(self, skill_def: dict) -> int:
        """Calculate experience compensation for max-star duplicate comprehension.

        Flat compensation for now: config skills carry no rank field, so
        rank-tiered compensation is deferred to the skill-pool redesign
        (bd: dhh). Both base and ratio are config-tunable under
        ``skill_system``.

        Args:
            skill_def: The skill definition dict (currently unused).

        Returns:
            Compensation experience amount.
        """
        base = self._skill_cfg.get("star_compensation_base", 1000)
        ratio = self._skill_cfg.get("star_compensation_ratio", 0.5)
        return int(base * ratio)

    # ------------------------------------------------------------------
    # Study target management
    # ------------------------------------------------------------------

    async def set_study_target(
        self, player: Player, skill_id: str, owned_skill_ids: list[str]
    ) -> tuple[bool, str]:
        """Set a skill as the player's study target.

        Validation (spec skill-system):
        - Must be owned (in owned_skill_ids).
        - Must not already be learned.
        """
        if skill_id not in owned_skill_ids:
            return False, "你尚未拥有该功法，无法设为修习目标"

        if await self._is_skill_learned(player, skill_id):
            return False, "该功法已领悟，无需再修习"

        player.study_target = skill_id
        return True, f"已将【{self._get_skill_name(skill_id)}】设为修习目标"

    def clear_study_target(self, player: Player) -> tuple[bool, str]:
        """Clear the player's study target."""
        if not player.study_target:
            return False, "当前没有修习目标"
        old = player.study_target
        player.study_target = ""
        return True, f"已取消修习目标【{self._get_skill_name(old)}】"

    def get_study_target_info(self, player: Player) -> dict:
        """Get study target display info."""
        skill_id = player.study_target
        if not skill_id:
            return {"has_target": False, "message": "当前没有修习目标"}

        skill_def = self._find_skill_definition(skill_id)
        name = skill_def.get("name", skill_id) if skill_def else skill_id
        return {
            "has_target": True,
            "skill_id": skill_id,
            "name": name,
            "description": skill_def.get("description", "") if skill_def else "",
        }

    def _get_skill_name(self, skill_id: str) -> str:
        """Get skill display name by ID."""
        skill_def = self._find_skill_definition(skill_id)
        return skill_def.get("name", skill_id) if skill_def else skill_id

    # ------------------------------------------------------------------
    # Heart method passive bonus
    # ------------------------------------------------------------------

    def get_heart_method_passive(self, player: Player) -> dict[str, int | float]:
        """Get the passive bonus dict from the equipped heart method.

        Returns empty dict if no heart method equipped or no passive defined.
        """
        heart_method_name = player.main_technique
        if not heart_method_name:
            return {}

        heart_method = self.config_manager.heart_methods_data.get(heart_method_name)
        if not heart_method:
            return {}

        passive = heart_method.get("passive_bonus", {})
        if isinstance(passive, str):
            try:
                passive = json.loads(passive)
            except json.JSONDecodeError:
                return {}
        return passive if isinstance(passive, dict) else {}

    # ------------------------------------------------------------------
    # Equipment validation
    # ------------------------------------------------------------------

    async def can_equip_technique(
        self, player: Player, technique_name: str, all_skill_ids: list[str]
    ) -> tuple[bool, str]:
        """Check if a technique (功法) can be equipped.

        Rules (spec skill-system):
        - Must be learned.
        - Must not exceed max technique slots (default 3).
        """
        # Find skill ID by name
        skill_id = self._find_skill_id_by_name(technique_name)
        if skill_id is None:
            return False, f"未找到功法【{technique_name}】"

        if not await self._is_skill_learned(player, skill_id):
            return False, f"功法【{technique_name}】尚未领悟，无法装备"

        techniques_list = player.get_techniques_list()
        max_slots = self._skill_cfg.get("max_technique_slots", 4)
        if len(techniques_list) >= max_slots:
            return False, f"功法栏已满（最多{max_slots}个），请先卸下其他功法"

        if technique_name in techniques_list:
            return False, f"功法【{technique_name}】已装备"

        return True, ""

    def _find_skill_id_by_name(self, name: str) -> str | None:
        """Find skill ID by its display name."""
        skill = self.config_manager.skills_data.get(name)
        if isinstance(skill, dict):
            return skill.get("id")
        return None

    # ------------------------------------------------------------------
    # Battle loadout export (for Group 4 combat engine)
    # ------------------------------------------------------------------

    async def get_battle_loadout(self, player: Player) -> dict:
        """Export the player's full battle loadout for the combat engine.

        Returns a dict with:
        - trigger_skills: list of active trigger skills (from weapon + techniques)
        - ultimates: list of active ultimate skills (from techniques)
        - heart_method_passive: passive bonus dict from heart method
        - weapon_coefficient_k: K value of equipped weapon
        - base_damage: base damage of equipped weapon
        - armor_value: total armor from all equipment

        Technique skills are exported with the route multiplier applied
        (per player.cultivation_type): trigger rate is scaled by the route
        multiplier and capped at 1.0; ultimate effect_value is scaled by it
        (mandatory-cast ultimates keep rate at 1.0). Star-level bonuses are
        applied before the route multiplier.

        When the player belongs to a sect with an enshrined mainbuff skill
        (镇派功法位), that skill's trigger skill is appended to
        ``trigger_skills`` at star-1 normalization with the route multiplier
        applied (sect buffs are not learned skills).
        """
        loadout = {
            "trigger_skills": [],
            "ultimates": [],
            "heart_method_passive": self.get_heart_method_passive(player),
            "weapon_coefficient_k": 1.0,
            "base_damage": 0,
            "armor_value": 0,
        }

        # Weapon trigger skills
        if player.weapon:
            weapon_def = self.config_manager.weapons_data.get(player.weapon)
            if weapon_def:
                loadout["weapon_coefficient_k"] = weapon_def.get(
                    "weapon_coefficient_k", 1.0
                )
                loadout["base_damage"] = weapon_def.get("base_damage", 0)
                loadout["armor_value"] += weapon_def.get("armor_value", 0)
                for ts in weapon_def.get("trigger_skills", []):
                    loadout["trigger_skills"].append(ts)

        # Armor (from items.json or weapons.json)
        if player.armor:
            armor_def = self.config_manager.items_data.get(player.armor)
            if not armor_def:
                armor_def = self.config_manager.weapons_data.get(player.armor)
            if armor_def:
                loadout["armor_value"] += armor_def.get("armor_value", 0)

        # Techniques (learned skills only)
        techniques_list = player.get_techniques_list()
        for tech_name in techniques_list:
            skill_id = self._find_skill_id_by_name(tech_name)
            if skill_id is None:
                continue
            if not await self._is_skill_learned(player, skill_id):
                continue  # Should not happen if validation is correct

            skill_def = self._find_skill_definition(skill_id)
            if skill_def is None:
                continue

            # Apply star level from persistent table
            star_level = await self._get_skill_star_level(player, skill_id)
            skill_def = self._apply_star_to_def(skill_def, star_level)

            # Route multiplier (route_mult_ling/ti): scales the expected gain
            # of trigger skills (rate) and ultimates (effect_value, rate is
            # fixed at 1.0 by the mandatory-cast rule). Copies are exported so
            # the shared config definitions are never mutated.
            route_mult = skill_def.get("route_multiplier", {}).get(
                player.cultivation_type, 1.0
            )

            trigger = skill_def.get("trigger_skill")
            if trigger:
                trigger = dict(trigger)
                trigger["trigger_rate"] = min(
                    1.0, trigger.get("trigger_rate", 0.0) * route_mult
                )
                loadout["trigger_skills"].append(trigger)

            ultimate = skill_def.get("ultimate")
            if ultimate:
                ultimate = dict(ultimate)
                ultimate["effect_value"] = (
                    ultimate.get("effect_value", 0.0) * route_mult
                )
                loadout["ultimates"].append(ultimate)

        # Sect mainbuff (镇派功法位, design §4.3): members of a sect with an
        # enshrined skill gain its trigger skill as an additional battle
        # trigger. Injection lives here so every combat path (PvE/PvP/Boss)
        # picks it up via the same loadout export; sect buffs are not
        # learned skills, so they are fixed at star 1 normalization. A
        # trigger skill whose name is already present (the player learned
        # and equipped the same sect skill themselves) is skipped so it
        # never fires twice per attack.
        sect_id = getattr(player, "sect_id", 0)
        if self.db is not None and self.db.ext is not None and sect_id:
            sect = await self.db.ext.get_sect_by_id(sect_id)
            if sect is not None:
                for buff_skill_id in sect.get_mainbuff_list():
                    sect_skill_def = self._find_skill_definition(str(buff_skill_id))
                    if sect_skill_def is None:
                        continue
                    sect_skill_def = self._apply_star_to_def(sect_skill_def, 1)
                    route_mult = sect_skill_def.get("route_multiplier", {}).get(
                        player.cultivation_type, 1.0
                    )
                    trigger = sect_skill_def.get("trigger_skill")
                    if trigger:
                        existing_names = {
                            t.get("name")
                            for t in loadout["trigger_skills"]
                            if isinstance(t, dict)
                        }
                        if trigger.get("name") in existing_names:
                            continue
                        trigger = dict(trigger)
                        trigger["trigger_rate"] = min(
                            1.0, trigger.get("trigger_rate", 0.0) * route_mult
                        )
                        loadout["trigger_skills"].append(trigger)

        return loadout

    async def _get_skill_star_level(self, player: Player, skill_id: str) -> int:
        """Get the star level of a learned skill from the database."""
        if self.db is None or self.db.ext is None:
            return 1
        return await self.db.ext.get_star_level(player.user_id, skill_id)

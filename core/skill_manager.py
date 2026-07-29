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
    STAR_UP_RATE_BONUS = 0.20
    STAR_UP_EFFECT_BONUS = 0.20

    def __init__(self, config_manager: "ConfigManager", db: "DataBase" | None = None):
        self.config_manager = config_manager
        self.db = db
        self._skill_cfg = config_manager.game_config.get("skill_system", {})

    # ------------------------------------------------------------------
    # Comprehension pool building
    # ------------------------------------------------------------------

    async def _build_comprehension_pool(
        self,
        player: "Player",
        channel: str,  # "breakthrough_success" | "breakthrough_fail" | "cultivation"
    ) -> list[dict]:
        """Build the comprehension pool for a given channel.

        Pool composition (design D4 / spec skill-system):
        - Heart method skill pool (uniform selection; coefficient only affects
          success probability, not selection weight).
        - Study target (if set and not yet learned).
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

        return pool

    async def _is_skill_learned(self, player: "Player", skill_id: str) -> bool:
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
        self, player: "Player"
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

    async def roll_breakthrough_fail_comprehension(
        self, player: "Player"
    ) -> dict | None:
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
        self, player: "Player", hours: int
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
        self, player: "Player", success: bool
    ) -> dict | None:
        """Independent universal pool roll for breakthrough (no heart method).

        When player has no heart method equipped, the normal comprehension
        pool is empty. This method provides the 3% fallback (design D4).
        Called separately from the main comprehension roll.

        The ``success`` parameter is kept for API compatibility but the rate
        is always ``universal_pool_no_heart_rate`` (3%) when no heart
        method is equipped.
        """
        if player.main_technique:
            return None  # Has heart method, use normal pool

        base_rate = self._skill_cfg.get("universal_pool_no_heart_rate", 0.03)

        universal_skill = await self._pick_universal_skill(player)
        if universal_skill is None:
            return None

        if random.random() < base_rate:
            return await self._resolve_and_learn(
                player,
                {"skill_id": universal_skill["id"], "source": "universal_fallback"},
            )
        return None

    async def _pick_universal_skill(self, player: "Player") -> dict | None:
        """Pick a random unlearned skill from the universal pool.

        Returns the skill definition or None if all universal skills are
        already learned or the pool is empty.
        """
        universal_skills = [
            skill
            for skill in self.config_manager.skills_data.values()
            if skill.get("_group") == "通用功法池"
            and skill.get("id")
            and not await self._is_skill_learned(player, skill["id"])
        ]
        if not universal_skills:
            return None
        return random.choice(universal_skills)

    # ------------------------------------------------------------------
    # Learn / star-up logic
    # ------------------------------------------------------------------

    async def _resolve_and_learn(self, player: "Player", chosen: dict) -> dict | None:
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

        is_new, star_level = await self.db.ext.learn_or_star_up(
            player.user_id, skill_id, source
        )

        # Clear study target if matched
        if player.study_target == skill_id:
            player.study_target = ""

        # Provide a source hint in the returned definition for callers
        result = self._apply_star_to_def(skill_def, star_level)
        result["learn_source"] = source
        result["is_new_learn"] = is_new
        return result

    def _find_skill_definition(self, skill_id: str) -> dict | None:
        """Find a skill definition by ID across all skill categories."""
        for skill in self.config_manager.skills_data.values():
            if isinstance(skill, dict) and skill.get("id") == skill_id:
                return skill
        return None

    def _apply_star_to_def(self, skill_def: dict, star_level: int) -> dict:
        """Return a skill definition with star-level multipliers applied.

        Trigger rate and effect value are boosted by star level.
        A normalized ``trigger_timing`` key is injected so the combat engine
        can filter skills by phase (on_attack / on_defense / on_crit /
        round_start / ultimate).
        """
        result = dict(skill_def)
        trigger = result.get("trigger_skill")
        if trigger:
            rate = trigger.get("trigger_rate", 0.0)
            value = trigger.get("effect_value", 0.0)
            bonus = (star_level - 1) * self.STAR_UP_RATE_BONUS
            trigger = dict(trigger)
            trigger["trigger_rate"] = min(rate * (1 + bonus), 1.0)
            trigger["effect_value"] = value * (1 + bonus)
            trigger["star_level"] = star_level
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
            bonus = (star_level - 1) * self.STAR_UP_EFFECT_BONUS
            ultimate = dict(ultimate)
            ultimate["effect_value"] = value * (1 + bonus)
            ultimate["star_level"] = star_level
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
    # Study target management
    # ------------------------------------------------------------------

    async def set_study_target(
        self, player: "Player", skill_id: str, owned_skill_ids: list[str]
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

    def clear_study_target(self, player: "Player") -> tuple[bool, str]:
        """Clear the player's study target."""
        if not player.study_target:
            return False, "当前没有修习目标"
        old = player.study_target
        player.study_target = ""
        return True, f"已取消修习目标【{self._get_skill_name(old)}】"

    def get_study_target_info(self, player: "Player") -> dict:
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

    def get_heart_method_passive(self, player: "Player") -> dict[str, int | float]:
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
        self, player: "Player", technique_name: str, all_skill_ids: list[str]
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
        max_slots = self._skill_cfg.get("max_technique_slots", 3)
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

    async def get_battle_loadout(self, player: "Player") -> dict:
        """Export the player's full battle loadout for the combat engine.

        Returns a dict with:
        - trigger_skills: list of active trigger skills (from weapon + techniques)
        - ultimates: list of active ultimate skills (from techniques)
        - heart_method_passive: passive bonus dict from heart method
        - weapon_coefficient_k: K value of equipped weapon
        - base_damage: base damage of equipped weapon
        - armor_value: total armor from all equipment
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

            trigger = skill_def.get("trigger_skill")
            if trigger:
                loadout["trigger_skills"].append(trigger)

            ultimate = skill_def.get("ultimate")
            if ultimate:
                loadout["ultimates"].append(ultimate)

        return loadout

    async def _get_skill_star_level(self, player: "Player", skill_id: str) -> int:
        """Get the star level of a learned skill from the database."""
        if self.db is None or self.db.ext is None:
            return 1
        return await self.db.ext.get_star_level(player.user_id, skill_id)

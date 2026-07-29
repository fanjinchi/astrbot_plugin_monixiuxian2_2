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

import json
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config_manager import ConfigManager
    from ..models import Player


class SkillManager:
    """Manages skill comprehension, star-up, and heart method passives."""

    # Star-up multiplier: each star level adds this percentage to trigger rate/effect.
    STAR_UP_RATE_BONUS = 0.20
    STAR_UP_EFFECT_BONUS = 0.20

    def __init__(self, config_manager: "ConfigManager"):
        self.config_manager = config_manager
        self._skill_cfg = config_manager.game_config.get("skill_system", {})

    # ------------------------------------------------------------------
    # Comprehension pool building
    # ------------------------------------------------------------------

    def _build_comprehension_pool(
        self,
        player: "Player",
        channel: str,  # "breakthrough_success" | "breakthrough_fail" | "cultivation"
    ) -> list[dict]:
        """Build the comprehension pool for a given channel.

        Pool composition (design D4 / spec skill-system):
        - Heart method skill pool (weighted by learn_coefficient) if equipped.
        - Study target (if set and not yet learned).
        - Universal pool (breakthrough channels only; cultivation MUST NOT access it).

        Returns a list of dicts: {"skill_id": str, "weight": float, "source": str}.
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
                                "weight": coeff,
                                "source": "heart_method",
                            }
                        )

        # 2. Study target
        study_target = player.study_target
        if study_target and not self._is_skill_learned(player, study_target):
            pool.append(
                {
                    "skill_id": study_target,
                    "weight": 1.0,
                    "source": "study_target",
                }
            )

        # 3. Universal pool (breakthrough channels only)
        if channel.startswith("breakthrough"):
            universal_skills = self.config_manager.skills_data.get("通用功法池", [])
            for skill_def in universal_skills:
                skill_id = skill_def.get("id")
                if skill_id:
                    pool.append(
                        {
                            "skill_id": skill_id,
                            "weight": 1.0,
                            "source": "universal",
                        }
                    )

        return pool

    def _is_skill_learned(self, player: "Player", skill_id: str) -> bool:
        """Check if a skill is already learned by the player."""
        learned = player.get_learned_skills()
        return any(entry.get("skill_id") == skill_id for entry in learned)

    # ------------------------------------------------------------------
    # Comprehension roll helpers
    # ------------------------------------------------------------------

    def _roll_comprehension(self, pool: list[dict], base_rate: float) -> dict | None:
        """Weighted random draw from the comprehension pool.

        Actual comprehension rate for each entry = base_rate * weight.
        We draw one entry with probability proportional to weight, then
        roll against base_rate * weight for that entry.
        """
        if not pool:
            return None

        total_weight = sum(entry["weight"] for entry in pool)
        if total_weight <= 0:
            return None

        # Weighted random pick
        pick = random.random() * total_weight
        cumulative = 0.0
        chosen = None
        for entry in pool:
            cumulative += entry["weight"]
            if pick <= cumulative:
                chosen = entry
                break

        if chosen is None:
            chosen = pool[-1]

        # Roll comprehension for the chosen skill
        actual_rate = base_rate * chosen["weight"]
        if random.random() < actual_rate:
            return chosen
        return None

    # ------------------------------------------------------------------
    # Public comprehension API (three channels)
    # ------------------------------------------------------------------

    def roll_breakthrough_success_comprehension(self, player: "Player") -> dict | None:
        """Comprehension roll on breakthrough success.

        Returns the learned skill definition (from skills_data) or None.
        """
        base_rate = self._skill_cfg.get("breakthrough_success_learn_rate", 0.20)
        pool = self._build_comprehension_pool(player, "breakthrough_success")
        chosen = self._roll_comprehension(pool, base_rate)
        if chosen is None:
            return None
        return self._resolve_and_learn(player, chosen)

    def roll_breakthrough_fail_comprehension(self, player: "Player") -> dict | None:
        """Comprehension roll on breakthrough failure ("破而后立").

        Returns the learned skill definition or None.
        """
        base_rate = self._skill_cfg.get("breakthrough_fail_learn_rate", 0.10)
        pool = self._build_comprehension_pool(player, "breakthrough_fail")
        chosen = self._roll_comprehension(pool, base_rate)
        if chosen is None:
            return None
        return self._resolve_and_learn(player, chosen)

    def roll_cultivation_comprehension(
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
            pool = self._build_comprehension_pool(player, "cultivation")
            chosen = self._roll_comprehension(pool, base_rate)
            if chosen:
                learned = self._resolve_and_learn(player, chosen)
                if learned:
                    results.append(learned)
        return results

    # ------------------------------------------------------------------
    # Universal pool fallback (no heart method equipped)
    # ------------------------------------------------------------------

    def roll_universal_pool_breakthrough(
        self, player: "Player", success: bool
    ) -> dict | None:
        """Independent universal pool roll for breakthrough (no heart method).

        When player has no heart method equipped, the normal comprehension
        pool is empty. This method provides the 3% fallback (design D4).
        Called separately from the main comprehension roll.
        """
        if player.main_technique:
            return None  # Has heart method, use normal pool

        rate_key = "universal_pool_rate" if success else "universal_pool_no_heart_rate"
        # For success: 5% from universal pool; for fail: 3% independent
        base_rate = self._skill_cfg.get(rate_key, 0.05 if success else 0.03)

        universal_skills = self.config_manager.skills_data.get("通用功法池", [])
        if not universal_skills:
            return None

        chosen_def = random.choice(universal_skills)
        skill_id = chosen_def.get("id")
        if not skill_id or self._is_skill_learned(player, skill_id):
            return None

        if random.random() < base_rate:
            return self._resolve_and_learn(
                player, {"skill_id": skill_id, "source": "universal_fallback"}
            )
        return None

    # ------------------------------------------------------------------
    # Learn / star-up logic
    # ------------------------------------------------------------------

    def _resolve_and_learn(self, player: "Player", chosen: dict) -> dict | None:
        """Resolve a chosen skill ID to its full definition and update player state.

        Handles star-up for duplicates. Clears study_target if matched.
        Returns the skill definition (with current star level) or None.
        """
        skill_id = chosen["skill_id"]

        # Find skill definition across all categories
        skill_def = self._find_skill_definition(skill_id)
        if skill_def is None:
            return None

        learned_list = player.get_learned_skills()

        # Check if already learned -> star up
        for entry in learned_list:
            if entry.get("skill_id") == skill_id:
                entry["star_level"] = entry.get("star_level", 1) + 1
                player.set_learned_skills(learned_list)
                # Clear study target if it was this skill
                if player.study_target == skill_id:
                    player.study_target = ""
                return self._apply_star_to_def(skill_def, entry["star_level"])

        # New learn
        learned_list.append({"skill_id": skill_id, "star_level": 1})
        player.set_learned_skills(learned_list)

        # Clear study target if matched
        if player.study_target == skill_id:
            player.study_target = ""

        return self._apply_star_to_def(skill_def, 1)

    def _find_skill_definition(self, skill_id: str) -> dict | None:
        """Find a skill definition by ID across all skill categories."""
        for category, skills in self.config_manager.skills_data.items():
            if isinstance(skills, list):
                for skill in skills:
                    if skill.get("id") == skill_id:
                        return skill
        return None

    def _apply_star_to_def(self, skill_def: dict, star_level: int) -> dict:
        """Return a skill definition with star-level multipliers applied.

        Trigger rate and effect value are boosted by star level.
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
            result["trigger_skill"] = trigger

        ultimate = result.get("ultimate")
        if ultimate:
            value = ultimate.get("effect_value", 0.0)
            bonus = (star_level - 1) * self.STAR_UP_EFFECT_BONUS
            ultimate = dict(ultimate)
            ultimate["effect_value"] = value * (1 + bonus)
            ultimate["star_level"] = star_level
            result["ultimate"] = ultimate

        result["current_star_level"] = star_level
        return result

    # ------------------------------------------------------------------
    # Study target management
    # ------------------------------------------------------------------

    def set_study_target(
        self, player: "Player", skill_id: str, owned_skill_ids: list[str]
    ) -> tuple[bool, str]:
        """Set a skill as the player's study target.

        Validation (spec skill-system):
        - Must be owned (in owned_skill_ids).
        - Must not already be learned.
        """
        if skill_id not in owned_skill_ids:
            return False, "你尚未拥有该功法，无法设为修习目标"

        if self._is_skill_learned(player, skill_id):
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

    def can_equip_technique(
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

        if not self._is_skill_learned(player, skill_id):
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
        for category, skills in self.config_manager.skills_data.items():
            if isinstance(skills, list):
                for skill in skills:
                    if skill.get("name") == name:
                        return skill.get("id")
        return None

    # ------------------------------------------------------------------
    # Battle loadout export (for Group 4 combat engine)
    # ------------------------------------------------------------------

    def get_battle_loadout(self, player: "Player") -> dict:
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

        # Armor
        if player.armor:
            armor_def = self.config_manager.weapons_data.get(player.armor)
            if armor_def:
                loadout["armor_value"] += armor_def.get("armor_value", 0)

        # Techniques (learned skills only)
        techniques_list = player.get_techniques_list()
        for tech_name in techniques_list:
            skill_id = self._find_skill_id_by_name(tech_name)
            if skill_id is None:
                continue
            if not self._is_skill_learned(player, skill_id):
                continue  # Should not happen if validation is correct

            skill_def = self._find_skill_definition(skill_id)
            if skill_def is None:
                continue

            # Apply star level
            star_level = self._get_skill_star_level(player, skill_id)
            skill_def = self._apply_star_to_def(skill_def, star_level)

            trigger = skill_def.get("trigger_skill")
            if trigger:
                loadout["trigger_skills"].append(trigger)

            ultimate = skill_def.get("ultimate")
            if ultimate:
                loadout["ultimates"].append(ultimate)

        return loadout

    def _get_skill_star_level(self, player: "Player", skill_id: str) -> int:
        """Get the star level of a learned skill."""
        for entry in player.get_learned_skills():
            if entry.get("skill_id") == skill_id:
                return entry.get("star_level", 1)
        return 1

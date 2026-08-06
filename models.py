import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config_manager import ConfigManager


@dataclass
class Item:
    """Equipment item model"""

    item_id: str  # Unique item ID
    name: str  # Item name
    item_type: str  # Equipment type: weapon, armor, main_technique, technique
    description: str = ""  # Item description

    # Equipment rank
    rank: str = ""  # Rank: 凡品, 灵品, 地品, 天品, 皇品, 帝品, 道品, 仙品, 混元先天
    required_level_index: int = 0  # Minimum level required
    weapon_category: str = ""  # Weapon category

    # New four main attributes (legacy five-dim fields removed)
    damage: int = 0  # Damage bonus
    agility: int = 0  # Agility bonus (dodge/hit)
    speed: int = 0  # Speed bonus (initiative frequency)
    hp: int = 0  # HP bonus

    # Armor value (from equipment, additive damage reduction)
    armor_value: int = 0

    # Weapon coefficient K (large weapons have higher K)
    weapon_coefficient_k: float = 1.0

    # Base damage for unarmed fallback
    base_damage: int = 0

    # Route multiplier (same item, different values for spirit/body routes)
    route_multiplier: str = "{}"  # JSON: {"灵修": 1.0, "体修": 1.0}

    # Trigger skills (JSON list)
    trigger_skills: str = "[]"

    # Heart method exclusive attributes
    exp_multiplier: float = 0.0  # EXP multiplier (heart method only)
    passive_bonus: str = "{}"  # JSON: passive attribute bonuses

    # Skill pool (heart method only)
    skill_pool: str = "[]"  # JSON list of learnable skills with coefficients

    def get_route_multiplier(self, route: str = "灵修") -> float:
        """Get route multiplier for this item"""
        try:
            data = json.loads(self.route_multiplier)
            return data.get(route, 1.0)
        except json.JSONDecodeError:
            return 1.0

    def get_trigger_skills_list(self) -> list[dict]:
        """Get trigger skills list"""
        try:
            return json.loads(self.trigger_skills)
        except json.JSONDecodeError:
            return []

    def get_skill_pool(self) -> list[dict]:
        """Get skill pool for heart method"""
        try:
            return json.loads(self.skill_pool)
        except json.JSONDecodeError:
            return []

    def get_attribute_display(self) -> str:
        """Get attribute bonus display text"""
        attrs = []
        if self.base_damage > 0:
            attrs.append(f"每击基础伤害+{self.base_damage}")
        if self.damage > 0:
            attrs.append(f"伤害+{self.damage}")
        if self.agility > 0:
            attrs.append(f"身法+{self.agility}")
        if self.speed > 0:
            attrs.append(f"迅捷+{self.speed}")
        if self.hp > 0:
            attrs.append(f"气血+{self.hp}")
        if self.armor_value > 0:
            attrs.append(f"护甲+{self.armor_value}")
        if self.weapon_coefficient_k != 1.0:
            attrs.append(f"武器系数K×{self.weapon_coefficient_k}")
        if self.exp_multiplier > 0:
            attrs.append(f"修为倍率+{self.exp_multiplier:.1%}")
        return "、".join(attrs) if attrs else "无属性加成"


@dataclass
class Player:
    """Player data model - new four-main-attribute framework"""

    user_id: str
    level_index: int = 1
    spiritual_root: str = "未知"
    cultivation_type: str = "灵修"  # 灵修 or 体修
    user_name: str = ""  # Dao name

    # Basic attributes
    lifespan: int = 100  # Lifespan
    experience: int = 0  # EXP
    gold: int = 0  # Spirit stones
    state: str = "空闲"
    cultivation_start_time: int = 0  # Unix timestamp, 0 = not cultivating
    last_check_in_date: str = ""  # YYYY-MM-DD
    level_up_rate: int = 0  # Permanent breakthrough success rate bonus in integer percentage points (5 = +5%); consumed by calculate_breakthrough_success_rate, currently no grant source

    # Breakthrough fail-streak pity counter
    breakthrough_fail_streak: int = 0  # Consecutive failures without death

    # Equipment slots
    weapon: str = ""  # Weapon name
    armor: str = ""  # Armor name
    main_technique: str = ""  # Main heart method
    techniques: str = "[]"  # Technique list (JSON, max 3)

    # Four main attributes (new framework)
    damage: int = 10  # Damage (attack power)
    agility: int = 5  # Agility (dodge/hit)
    speed: int = 5  # Speed (initiative frequency)
    hp: int = 100  # HP (life)

    # Armor value (derived from equipment)
    armor_value: int = 0

    # Skill system
    study_target: str = ""  # Current study target skill ID

    # Battle report preference (0 = use game_config default)
    battle_report_merge_count: int = 0
    # Sect system
    sect_id: int = 0
    sect_position: int = 4  # 0=宗主,1=长老,2=亲传,3=内门,4=外门
    sect_contribution: int = 0
    sect_task: int = 0
    sect_elixir_get: int = 0

    # Blessed land
    blessed_spot_flag: int = 0
    blessed_spot_name: str = ""

    # Pill system
    active_pill_effects: str = "[]"
    permanent_pill_gains: str = "{}"
    has_resurrection_pill: bool = False
    has_debuff_shield: bool = False
    pills_inventory: str = "{}"

    # Storage ring
    storage_ring: str = "基础储物戒"
    storage_ring_items: str = "{}"

    # Daily limits
    daily_pill_usage: str = "{}"
    last_daily_reset: str = ""

    def get_level(self, config_manager: "ConfigManager") -> str:
        """Get level name via the central config API."""
        return config_manager.get_level_name(self.level_index, self.cultivation_type)

    def get_required_exp(self, config_manager: "ConfigManager") -> int:
        """Get required EXP for the next level via the central config API."""
        return config_manager.get_exp_needed(self.level_index, self.cultivation_type)

    def get_techniques_list(self) -> list[str]:
        """Get technique list"""
        try:
            return json.loads(self.techniques)
        except json.JSONDecodeError:
            return []

    def set_techniques_list(self, techniques_list: list[str]):
        """Set technique list"""
        self.techniques = json.dumps(techniques_list, ensure_ascii=False)

    def get_active_pill_effects(self) -> list[dict]:
        """Get active temporary pill effects"""
        try:
            return json.loads(self.active_pill_effects)
        except json.JSONDecodeError:
            return []

    def set_active_pill_effects(self, effects: list[dict]):
        """Set active pill effects"""
        self.active_pill_effects = json.dumps(effects, ensure_ascii=False)

    def get_permanent_pill_gains(self) -> dict:
        """Get permanent pill gains"""
        try:
            return json.loads(self.permanent_pill_gains)
        except json.JSONDecodeError:
            return {}

    def set_permanent_pill_gains(self, gains: dict):
        """Set permanent pill gains"""
        self.permanent_pill_gains = json.dumps(gains, ensure_ascii=False)

    def get_pills_inventory(self) -> dict:
        """Get pill inventory"""
        try:
            return json.loads(self.pills_inventory)
        except json.JSONDecodeError:
            return {}

    def set_pills_inventory(self, inventory: dict):
        """Set pill inventory"""
        self.pills_inventory = json.dumps(inventory, ensure_ascii=False)

    def get_storage_ring_items(self) -> dict:
        """Get storage ring items"""
        try:
            return json.loads(self.storage_ring_items)
        except json.JSONDecodeError:
            return {}

    def set_storage_ring_items(self, items: dict):
        """Set storage ring items"""
        self.storage_ring_items = json.dumps(items, ensure_ascii=False)

    def get_total_attributes(
        self, equipped_items: list[Item], pill_multipliers: dict | None = None
    ) -> dict:
        """Calculate total combat attributes from base, equipment, and pills.

        The new framework uses four main attributes plus armor (percent damage reduction).

        Args:
            equipped_items: List of equipped items
            pill_multipliers: Optional pill attribute multipliers

        Returns:
            Dict with damage, agility, speed, hp, armor_value and exp_multiplier.
        """
        # Base attributes from player
        total = {
            "damage": self.damage,
            "agility": self.agility,
            "speed": self.speed,
            "hp": self.hp,
            "armor_value": self.armor_value,
            "exp_multiplier": 0.0,
        }

        # Add equipment bonuses
        for item in equipped_items:
            route = self.cultivation_type
            mult = item.get_route_multiplier(route)

            total["damage"] += int(item.damage * mult)
            total["agility"] += int(item.agility * mult)
            total["speed"] += int(item.speed * mult)
            total["hp"] += int(item.hp * mult)
            total["armor_value"] += int(item.armor_value * mult)

            # Heart method exclusive passive bonuses
            if item.item_type == "main_technique":
                total["exp_multiplier"] += item.exp_multiplier
                try:
                    passive = json.loads(item.passive_bonus)
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
                except json.JSONDecodeError:
                    pass

        # Apply pill multipliers (new attribute keys)
        if pill_multipliers:
            total["damage"] = int(total["damage"] * pill_multipliers.get("damage", 1.0))
            total["agility"] = int(
                total["agility"] * pill_multipliers.get("agility", 1.0)
            )
            total["speed"] = int(total["speed"] * pill_multipliers.get("speed", 1.0))
            total["hp"] = int(total["hp"] * pill_multipliers.get("hp", 1.0))
            total["armor_value"] = int(
                total["armor_value"] * pill_multipliers.get("armor_value", 1.0)
            )

        return total

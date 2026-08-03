# core/equipment_manager.py

import json
from typing import TYPE_CHECKING

from ..data import DataBase
from ..models import Item, Player

if TYPE_CHECKING:
    from ..config_manager import ConfigManager
    from .storage_ring_manager import StorageRingManager


def _json_str(value) -> str:
    """Convert a dict/list to JSON string; pass through strings."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}" if isinstance(value, dict) else "[]"


def _normalize_item_type(item_config: dict) -> str:
    """Resolve item type to the new equipment type enum."""
    item_type = item_config.get("type", "")
    if item_type == "法器":
        subtype = item_config.get("subtype", "")
        if subtype == "武器":
            return "weapon"
        if subtype == "防具":
            return "armor"
        return "accessory"
    if item_type == "功法":
        return "technique"
    # Heart methods do not carry a type but have passive_bonus / skill_pool.
    if "passive_bonus" in item_config or "skill_pool" in item_config:
        return "main_technique"
    # Techniques/skills carry trigger_skill / ultimate.
    if "trigger_skill" in item_config or "ultimate" in item_config:
        return "technique"
    return item_type


class EquipmentManager:
    """装备管理器 - 处理装备的穿戴、卸下和属性计算"""

    def __init__(
        self,
        db: DataBase,
        config_manager: "ConfigManager" = None,
        storage_ring_manager: "StorageRingManager" = None,
    ):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager

    def parse_item_from_name(
        self,
        item_name: str,
        items_data: dict,
        weapons_data: dict | None = None,
        heart_methods_data: dict | None = None,
    ) -> Item | None:
        """从物品名称解析为Item对象

        Args:
            item_name: 物品名称
            items_data: 物品配置数据字典
            weapons_data: 武器配置数据字典（可选）
            heart_methods_data: 心法配置数据字典（可选）

        Returns:
            Item对象，如果未找到则返回None
        """
        if not item_name or item_name == "":
            return None

        item_config = items_data.get(item_name)
        if not item_config and weapons_data:
            item_config = weapons_data.get(item_name)
        if not item_config and heart_methods_data:
            item_config = heart_methods_data.get(item_name)

        if not item_config:
            return None

        item_type = _normalize_item_type(item_config)

        # New four-main-attribute framework fields (preferred)
        damage = item_config.get("damage", 0)
        agility = item_config.get("agility", 0)
        speed = item_config.get("speed", 0)
        hp = item_config.get("hp", 0)
        armor_value = item_config.get("armor_value", 0)
        weapon_coefficient_k = item_config.get("weapon_coefficient_k", 1.0)
        base_damage = item_config.get("base_damage", 0)
        route_multiplier = item_config.get("route_multiplier", {})
        trigger_skills = item_config.get("trigger_skills", [])
        passive_bonus = item_config.get("passive_bonus", {})
        skill_pool = item_config.get("skill_pool", [])

        # Legacy five-dimension mapping for old config files
        physical_damage = item_config.get("physical_damage", 0)
        magic_damage = item_config.get("magic_damage", 0)
        physical_defense = item_config.get("physical_defense", 0)
        magic_defense = item_config.get("magic_defense", 0)
        if physical_damage or magic_damage:
            damage = max(damage, physical_damage + magic_damage)
        if physical_defense or magic_defense:
            armor_value = max(armor_value, physical_defense + magic_defense)

        # Legacy equip_effects mapping (items.json 法器)
        equip_effects = item_config.get("equip_effects", {})
        attack = equip_effects.get("attack", 0)
        defense = equip_effects.get("defense", 0)
        if attack:
            damage = max(damage, attack)
        if defense:
            armor_value = max(armor_value, defense)

        return Item(
            item_id=item_config.get("id", item_name),
            name=item_name,
            item_type=item_type,
            description=item_config.get("description", ""),
            rank=item_config.get("rank", ""),
            required_level_index=item_config.get("required_level_index", 0),
            weapon_category=item_config.get("weapon_category", ""),
            damage=damage,
            agility=agility,
            speed=speed,
            hp=hp,
            armor_value=armor_value,
            weapon_coefficient_k=weapon_coefficient_k,
            base_damage=base_damage,
            route_multiplier=_json_str(route_multiplier),
            trigger_skills=_json_str(trigger_skills),
            exp_multiplier=item_config.get("exp_multiplier", 0.0),
            passive_bonus=_json_str(passive_bonus),
            skill_pool=_json_str(skill_pool),
        )

    def get_equipped_items(
        self, player: Player, items_data: dict, weapons_data: dict = None
    ) -> list[Item]:
        """获取玩家所有已装备的物品

        Args:
            player: 玩家对象
            items_data: 物品配置数据字典
            weapons_data: 武器配置数据字典（可选）

        Returns:
            已装备物品列表
        """
        equipped = []

        # 武器
        if player.weapon:
            item = self.parse_item_from_name(player.weapon, items_data, weapons_data)
            if item:
                equipped.append(item)

        # 防具
        if player.armor:
            item = self.parse_item_from_name(player.armor, items_data, weapons_data)
            if item:
                equipped.append(item)

        # 主修心法
        if player.main_technique:
            item = self.parse_item_from_name(
                player.main_technique, items_data, weapons_data
            )
            if item:
                equipped.append(item)

        # 功法列表
        techniques_list = player.get_techniques_list()
        for technique_name in techniques_list:
            item = self.parse_item_from_name(technique_name, items_data, weapons_data)
            if item:
                equipped.append(item)

        return equipped

    def check_equipment_level_requirement(
        self, player: Player, item: Item
    ) -> tuple[bool, str]:
        """检查玩家是否满足装备的境界要求

        Args:
            player: 玩家对象
            item: 装备物品

        Returns:
            (是否满足, 提示消息)
        """
        if player.level_index < item.required_level_index:
            # 获取需求境界名称
            required_level_name = self._format_required_level(item.required_level_index)
            return (
                False,
                f"境界不足！装备【{item.name}】（{item.rank}）需要达到【{required_level_name}】以上",
            )
        return True, ""

    def _format_required_level(self, level_index: int) -> str:
        """格式化需求境界名称（同时显示灵修/体修）"""
        if not self.config_manager:
            return f"境界{level_index}"

        names = []
        spirit_name = self.config_manager.get_level_name(level_index, "灵修")
        body_name = self.config_manager.get_level_name(level_index, "体修")
        if spirit_name:
            names.append(spirit_name)
        if body_name and body_name != spirit_name:
            names.append(body_name)

        if not names:
            return f"境界{level_index}"
        return " / ".join(names)

    async def equip_item(self, player: Player, item: Item) -> tuple[bool, str]:
        """装备物品

        Args:
            player: 玩家对象
            item: 要装备的物品

        Returns:
            (是否成功, 消息)
        """
        # 检查境界要求
        can_equip, error_msg = self.check_equipment_level_requirement(player, item)
        if not can_equip:
            return False, error_msg

        # 根据物品类型装备到相应位置
        if item.item_type == "weapon":
            old_item = player.weapon
            player.weapon = item.name
            await self.db.update_player(player)
            if old_item:
                # 尝试将旧装备存入储物戒
                storage_msg = await self._store_old_equipment(player, old_item)
                return (
                    True,
                    f"已将【{old_item}】替换为【{item.name}】（{item.rank}）{storage_msg}",
                )
            else:
                return True, f"已装备武器【{item.name}】（{item.rank}）"

        elif item.item_type == "armor":
            old_item = player.armor
            player.armor = item.name
            await self.db.update_player(player)
            if old_item:
                # 尝试将旧装备存入储物戒
                storage_msg = await self._store_old_equipment(player, old_item)
                return (
                    True,
                    f"已将【{old_item}】替换为【{item.name}】（{item.rank}）{storage_msg}",
                )
            else:
                return True, f"已装备防具【{item.name}】（{item.rank}）"

        elif item.item_type == "main_technique":
            old_item = player.main_technique
            player.main_technique = item.name
            await self.db.update_player(player)
            if old_item:
                # 尝试将旧心法存入储物戒
                storage_msg = await self._store_old_equipment(player, old_item)
                return (
                    True,
                    f"已将主修心法【{old_item}】替换为【{item.name}】（{item.rank}）{storage_msg}",
                )
            else:
                return True, f"已装备主修心法【{item.name}】（{item.rank}）"

        elif item.item_type == "technique":
            techniques_list = player.get_techniques_list()

            # 检查是否已装备
            if item.name in techniques_list:
                return False, f"功法【{item.name}】已装备"

            # 检查功法栏是否已满（最多3个）
            if len(techniques_list) >= 3:
                return False, "功法栏已满（最多3个），请先卸下其他功法"

            # 添加功法
            techniques_list.append(item.name)
            player.set_techniques_list(techniques_list)
            await self.db.update_player(player)
            return (
                True,
                f"已装备功法【{item.name}】（{item.rank}）（{len(techniques_list)}/3）",
            )

        else:
            return False, f"未知的装备类型：{item.item_type}"

    async def unequip_item(self, player: Player, slot_or_name: str) -> tuple[bool, str]:
        """卸下装备

        Args:
            player: 玩家对象
            slot_or_name: 装备槽位名称（武器/防具/主修心法）或功法名称

        Returns:
            (是否成功, 消息)
        """
        # 尝试按槽位卸下
        if slot_or_name in ["武器", "weapon"]:
            if not player.weapon:
                return False, "未装备武器"
            item_name = player.weapon
            player.weapon = ""
            await self.db.update_player(player)
            return True, f"已卸下武器【{item_name}】"

        elif slot_or_name in ["防具", "armor"]:
            if not player.armor:
                return False, "未装备防具"
            item_name = player.armor
            player.armor = ""
            await self.db.update_player(player)
            return True, f"已卸下防具【{item_name}】"

        elif slot_or_name in ["主修心法", "心法", "main_technique"]:
            if not player.main_technique:
                return False, "未装备主修心法"
            item_name = player.main_technique
            player.main_technique = ""
            await self.db.update_player(player)
            return True, f"已卸下主修心法【{item_name}】"

        # 尝试从功法列表中卸下（按名称）
        techniques_list = player.get_techniques_list()
        if slot_or_name in techniques_list:
            techniques_list.remove(slot_or_name)
            player.set_techniques_list(techniques_list)
            await self.db.update_player(player)
            return True, f"已卸下功法【{slot_or_name}】"

        return False, f"未找到装备：{slot_or_name}"

    async def _store_old_equipment(self, player: Player, item_name: str) -> str:
        """尝试将旧装备存入储物戒

        Args:
            player: 玩家对象
            item_name: 物品名称

        Returns:
            存储结果消息
        """
        if not self.storage_ring_manager:
            return ""

        success, msg = await self.storage_ring_manager.store_item(
            player, item_name, 1, silent=True
        )
        if success:
            return f"\n旧装备【{item_name}】已存入储物戒"
        else:
            return f"\n⚠️ 旧装备【{item_name}】存入储物戒失败：{msg}"

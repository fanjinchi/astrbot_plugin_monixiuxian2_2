# managers/enemy_manager.py
"""
敌人管理器 - 根据玩家等级和经验生成对应难度的敌人
用于PVE战斗系统
"""

import json
import random
from dataclasses import dataclass
from typing import Any

from astrbot.api import logger


@dataclass
class Enemy:
    """敌人数据模型，与 CombatStats 字段兼容"""

    user_id: str
    name: str  # 敌人名称
    hp: int  # 当前气血
    max_hp: int  # 最大气血
    mp: int  # 当前真元
    max_mp: int  # 最大真元
    atk: int  # 攻击力
    defense: int = 0  # 防御力
    crit_rate: int = 0  # 会心率（百分比）
    exp: int = 0  # 修为（用于计算属性）


class EnemyManager:
    """敌人管理器 - 根据玩家等级和经验生成对应难度的敌人"""

    def __init__(self, config_path: str):
        """
        初始化敌人管理器

        Args:
            config_path: enemies.json 配置文件路径
        """
        self.config_path = config_path
        with open(config_path, encoding="utf-8") as f:
            self.config = json.load(f)
        self.enemy_groups = self.config.get("enemy_groups", [])
        self.difficulty_coefficients = self.config.get("difficulty_coefficients", {})
        self.naming = self.config.get("naming", {})
        logger.info(f"敌人管理器初始化完成，加载了 {len(self.enemy_groups)} 个敌人分组")

    def _get_group_by_level(self, player_level: int) -> dict[str, Any]:
        """
        根据玩家等级选择对应的敌人分组

        Args:
            player_level: 玩家等级

        Returns:
            敌人分组配置字典
        """
        for group in self.enemy_groups:
            level_range = group.get("level_range", [0, 0])
            if level_range[0] <= player_level <= level_range[1]:
                return group
        # 等级超过31时，默认使用顶级分组
        return self.enemy_groups[-1] if self.enemy_groups else {}

    def spawn_enemy(self, player_level: int, player_exp: int, category: str) -> Enemy:
        """
        生成一个敌人

        根据玩家等级选择敌人分组，随机选择模板，
        应用难度系数和类别倍率生成最终属性。

        Args:
            player_level: 玩家等级，用于选择敌人分组
            player_exp: 玩家修为，用于计算敌人基础属性
            category: 敌人类别，可选 "normal"（普通）、"elite"（精英）、"boss"（首领）

        Returns:
            生成的敌人对象

        Raises:
            ValueError: 当找不到敌人模板时抛出
        """
        group = self._get_group_by_level(player_level)
        templates = group.get("templates", [])
        if not templates:
            raise ValueError("未找到敌人模板配置")

        template = random.choice(templates)

        # 从模板获取基础倍率
        hp_mult = template.get("hp_mult", 1.0)
        atk_mult = template.get("atk_mult", 1.0)
        defense = template.get("defense", 0)
        crit_rate = template.get("crit_rate", 0)

        # 应用类别倍率
        if category == "elite":
            elite_config = group.get("elite", {})
            hp_mult *= elite_config.get("hp_mult", 1.0)
            atk_mult *= elite_config.get("atk_mult", 1.0)
            defense += elite_config.get("defense_bonus", 0)
            crit_rate += elite_config.get("crit_rate_bonus", 0)
        elif category == "boss":
            boss_config = group.get("boss", {})
            hp_mult *= boss_config.get("hp_mult", 1.2)
            atk_mult *= boss_config.get("atk_mult", 1.2)
            defense += boss_config.get("defense_bonus", 0)
            crit_rate += boss_config.get("crit_rate_bonus", 0)

        # 计算基础修为
        difficulty_coeff = self.difficulty_coefficients.get(category, 0.85)
        base_exp = int(player_exp * difficulty_coeff)

        # 计算最终属性
        hp = int((base_exp // 2) * hp_mult)
        atk = int((base_exp // 10) * atk_mult)
        mp = base_exp

        # 组合敌人名称
        if category == "normal":
            name = self.naming.get("normal", "{name}").format(
                name=template.get("name", "未知妖兽")
            )
        elif category == "elite":
            prefix = random.choice(template.get("elite_prefixes", ["强大的"]))
            name = self.naming.get("elite", "{prefix}{name}").format(
                prefix=prefix, name=template.get("name", "未知妖兽")
            )
        elif category == "boss":
            boss_name = random.choice(template.get("boss_names", ["妖王"]))
            name = self.naming.get("boss", "{boss_name}").format(boss_name=boss_name)
        else:
            name = template.get("name", "未知妖兽")

        return Enemy(
            user_id=f"enemy_{template.get('key', 'unknown')}",
            name=name,
            hp=hp,
            max_hp=hp,
            mp=mp,
            max_mp=mp,
            atk=atk,
            defense=defense,
            crit_rate=crit_rate,
            exp=base_exp,
        )

    def get_drop_items(self, drop_tier: str) -> list[dict[str, Any]]:
        """
        获取掉落物品列表

        Args:
            drop_tier: 掉落等级，如 "low"、"mid"、"high"、"top"

        Returns:
            掉落物品列表（当前为占位实现，Phase 2 完善）
        """
        return []

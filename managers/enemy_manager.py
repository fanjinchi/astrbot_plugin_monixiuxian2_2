# managers/enemy_manager.py
"""
敌人管理器 - 根据玩家等级生成对应难度的敌人
用于PVE战斗系统
"""

import json
import random
from dataclasses import dataclass
from pathlib import Path
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
    """敌人管理器 - 根据玩家等级生成对应难度的敌人"""

    CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "enemies.json"
    LEVEL_CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "level_config.json"

    DEFAULT_CONFIG = {
        "enemy_groups": [
            {
                "key": "default",
                "name": "默认妖域",
                "level_range": [0, 100],
                "templates": [
                    {
                        "key": "default_monster",
                        "name": "未知妖兽",
                        "elite_prefixes": ["强大的"],
                        "boss_names": ["妖王"],
                        "hp_mult": 1.0,
                        "atk_mult": 1.0,
                        "defense": 0,
                        "crit_rate": 0,
                    }
                ],
                "elite": {
                    "hp_mult": 1.0,
                    "atk_mult": 1.0,
                    "defense_bonus": 0,
                    "crit_rate_bonus": 0,
                },
                "boss": {
                    "hp_mult": 1.2,
                    "atk_mult": 1.2,
                    "defense_bonus": 0,
                    "crit_rate_bonus": 0,
                },
                "drop_tier": "low",
            }
        ],
        "difficulty_coefficients": {
            "normal": 0.85,
            "elite": 1.0,
            "boss": 1.2,
        },
        "naming": {
            "normal": "{name}",
            "elite": "{prefix}{name}",
            "boss": "{boss_name}",
        },
    }

    DEFAULT_LEVEL_CONFIG = [
        {"exp_needed": 0},
        {"exp_needed": 500},
        {"exp_needed": 1200},
        {"exp_needed": 2000},
        {"exp_needed": 3000},
        {"exp_needed": 4500},
        {"exp_needed": 6500},
        {"exp_needed": 9000},
        {"exp_needed": 12000},
        {"exp_needed": 16000},
        {"exp_needed": 25000},
        {"exp_needed": 45000},
        {"exp_needed": 75000},
        {"exp_needed": 150000},
        {"exp_needed": 350000},
        {"exp_needed": 700000},
        {"exp_needed": 1200000},
        {"exp_needed": 2000000},
        {"exp_needed": 3500000},
        {"exp_needed": 6000000},
        {"exp_needed": 10000000},
    ]

    def __init__(self, level_config: list = None):
        """
        初始化敌人管理器

        Args:
            level_config: 等级配置列表（可选）。若未提供，自动从
                config/level_config.json 加载。
        """
        self.enemy_groups: list[dict] = []
        self.difficulty_coefficients: dict = {}
        self.naming: dict = {}
        self.level_config: list = []
        self.reload_config(level_config)

    def reload_config(self, level_config: list = None):
        """重新加载配置文件"""
        config = self._load_config_file()
        self.enemy_groups = config.get("enemy_groups", self.DEFAULT_CONFIG["enemy_groups"])
        self.difficulty_coefficients = config.get(
            "difficulty_coefficients", self.DEFAULT_CONFIG["difficulty_coefficients"]
        )
        self.naming = config.get("naming", self.DEFAULT_CONFIG["naming"])

        if level_config is not None:
            self.level_config = level_config
        else:
            self.level_config = self._load_level_config()

        logger.info(f"敌人管理器初始化完成，加载了 {len(self.enemy_groups)} 个敌人分组")

    def _load_config_file(self) -> dict:
        """加载敌人配置文件并在失败时回退到默认配置"""
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info("已加载 enemies.json")
                    return data
            except Exception as exc:
                logger.error(f"加载 enemies.json 失败，将使用默认配置: {exc}")
        return self.DEFAULT_CONFIG

    def _load_level_config(self) -> list:
        """加载等级配置文件并在失败时回退到默认配置"""
        if self.LEVEL_CONFIG_FILE.exists():
            try:
                with open(self.LEVEL_CONFIG_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info("已加载 level_config.json")
                    return data
            except Exception as exc:
                logger.error(f"加载 level_config.json 失败，将使用默认配置: {exc}")
        return self.DEFAULT_LEVEL_CONFIG

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

    def _get_exp_for_level(self, level_index: int) -> int:
        """根据等级索引获取该等级突破所需修为（即等级初始值）。"""
        if 0 <= level_index < len(self.level_config):
            return self.level_config[level_index].get("exp_needed", 0)
        return 0

    def spawn_enemy(self, player_level: int, category: str) -> Enemy:
        """
        生成一个敌人

        根据玩家等级选择敌人分组，在分组等级范围内随机选择敌人等级，
        以该等级的突破修为作为基础修为，应用难度系数和类别倍率生成最终属性。

        Args:
            player_level: 玩家等级，用于选择敌人分组
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

        level_range = group.get("level_range", [0, 0])
        enemy_level = random.randint(level_range[0], level_range[1])
        base_exp = self._get_exp_for_level(enemy_level)

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

# managers/enemy_manager.py
"""
敌人管理器 - 根据玩家等级生成对应难度的敌人
用于PVE战斗系统
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from astrbot.api import logger

if TYPE_CHECKING:
    from ..config_manager import ConfigManager


@dataclass
class Enemy:
    """Enemy data model using the new four-main-attribute framework."""

    user_id: str
    name: str
    hp: int
    max_hp: int
    damage: int
    agility: int
    speed: int
    armor_value: int
    exp: int
    crit_rate: int = 0
    # Legacy fields kept for compatibility with old callers/tests
    mp: int = 0
    max_mp: int = 0
    atk: int = 0
    defense: int = 0


class EnemyManager:
    """敌人管理器 - 根据玩家等级生成对应难度的敌人"""

    CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "enemies.json"
    LEVEL_CONFIG_FILE = (
        Path(__file__).resolve().parents[1] / "config" / "level_config.json"
    )

    # 类级计数器，用于为每个生成的敌人分配唯一 user_id
    _spawn_counter = 0

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

    def __init__(self, level_config: list = None, config_manager: ConfigManager = None):
        """
        初始化敌人管理器

        Args:
            level_config: 等级配置列表（可选）。若未提供，自动从
                config/level_config.json 加载。
            config_manager: 配置管理器（可选），用于读取 PvE 难度系数和
                境界基础属性。
        """
        self.config_manager: ConfigManager | None = config_manager
        self.enemy_groups: list[dict] = []
        self.difficulty_coefficients: dict = {}
        self.naming: dict = {}
        self.level_config: list = []
        self.reload_config(level_config)

    def reload_config(self, level_config: list = None):
        """重新加载配置文件"""
        config = self._load_config_file()
        self.enemy_groups = config.get(
            "enemy_groups", self.DEFAULT_CONFIG["enemy_groups"]
        )
        self.difficulty_coefficients = config.get(
            "difficulty_coefficients", self.DEFAULT_CONFIG["difficulty_coefficients"]
        )
        self.naming = config.get("naming", self.DEFAULT_CONFIG["naming"])

        if level_config is not None:
            self.level_config = level_config
        elif self.config_manager is not None:
            self.level_config = self.config_manager.level_data
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

    def _global_difficulty_multiplier(self) -> float:
        """读取 game_config 中的 PvE 全局难度系数。"""
        if self.config_manager is None:
            return 1.0
        return self.config_manager.game_config.get("pve", {}).get(
            "difficulty_multiplier", 1.0
        )

    def _randomize_base_value(self, base_value: int) -> int:
        """在基准值 ±10% 范围内随机生成最终值，至少为 1。"""
        if base_value <= 0:
            return 1
        low = max(1, int(base_value * 0.9))
        high = max(low, int(base_value * 1.1))
        return random.randint(low, high)

    def _get_level_base(self, level_index: int, key: str) -> int:
        """从等级配置中读取指定基础属性，缺失时返回合理默认值。"""
        if 0 <= level_index < len(self.level_config):
            return self.level_config[level_index].get(key, 0)
        return 0

    def _extract_realm_prefix(self, level_name: str) -> str:
        """从境界名称提取境界前缀（如'炼气期一层' -> '炼气期'）。"""
        if "期" in level_name:
            return level_name[: level_name.index("期") + 1]
        return level_name

    def _get_realm_range(self, player_level: int) -> list[int, int]:
        """根据玩家等级计算其所属境界在 level_config 中的连续索引范围。"""
        if not self.level_config:
            return [0, 0]
        max_index = len(self.level_config) - 1
        safe_level = max(0, min(player_level, max_index))
        level_name = self.level_config[safe_level].get("level_name", "")
        prefix = self._extract_realm_prefix(level_name)
        if not prefix:
            return [safe_level, safe_level]

        start = safe_level
        while (
            start > 0
            and self._extract_realm_prefix(
                self.level_config[start - 1].get("level_name", "")
            )
            == prefix
        ):
            start -= 1

        end = safe_level
        while (
            end < max_index
            and self._extract_realm_prefix(
                self.level_config[end + 1].get("level_name", "")
            )
            == prefix
        ):
            end += 1

        return [start, end]

    @staticmethod
    def _intersect_ranges(*ranges: list[int, int]) -> list[int, int] | None:
        """计算多个闭区间的交集，无交集时返回 None。"""
        low = max(r[0] for r in ranges)
        high = min(r[1] for r in ranges)
        if low > high:
            return None
        return [low, high]

    def _choose_enemy_level(
        self, player_level: int, group_range: list[int, int]
    ) -> int:
        """在分组、境界、玩家等级范围内选取敌人等级。"""
        realm_range = self._get_realm_range(player_level)
        player_range = [max(0, player_level - 2), player_level + 1]

        final_range = self._intersect_ranges(group_range, realm_range, player_range)
        if final_range is None:
            final_range = self._intersect_ranges(group_range, player_range)
        if final_range is None:
            final_range = group_range

        return random.randint(final_range[0], final_range[1])

    def spawn_enemy(self, player_level: int, category: str) -> Enemy:
        """
        生成一个敌人。

        敌人的四主属性基于对应境界的基准区间，再乘以模板倍率、类别倍率
        和全局 PvE 难度系数生成；不再使用旧的 base_exp 派生 hp/atk。

        Args:
            player_level: 玩家等级，用于选择敌人分组
            category: 敌人类别，可选 "normal" / "elite" / "boss"

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

        # 模板基础倍率
        hp_mult = template.get("hp_mult", 1.0)
        atk_mult = template.get("atk_mult", 1.0)
        armor_value = template.get("defense", 0)
        crit_rate = template.get("crit_rate", 0)

        # 应用类别倍率
        if category == "elite":
            elite_config = group.get("elite", {})
            hp_mult *= elite_config.get("hp_mult", 1.0)
            atk_mult *= elite_config.get("atk_mult", 1.0)
            armor_value += elite_config.get("defense_bonus", 0)
            crit_rate += elite_config.get("crit_rate_bonus", 0)
        elif category == "boss":
            boss_config = group.get("boss", {})
            hp_mult *= boss_config.get("hp_mult", 1.2)
            atk_mult *= boss_config.get("atk_mult", 1.2)
            armor_value += boss_config.get("defense_bonus", 0)
            crit_rate += boss_config.get("crit_rate_bonus", 0)

        level_range = group.get("level_range", [0, 0])
        enemy_level = self._choose_enemy_level(player_level, level_range)

        # 从境界配置读取四主属性基准并应用 ±10% 随机区间
        base_damage = self._get_level_base(enemy_level, "base_damage")
        base_agility = self._get_level_base(enemy_level, "base_agility")
        base_speed = self._get_level_base(enemy_level, "base_speed")
        base_hp = self._get_level_base(enemy_level, "base_hp")

        # 向后兼容：若配置缺少新字段，则用旧 exp_needed 派生基础值
        if base_damage == 0 and base_hp == 0:
            base_exp = self._get_level_base(enemy_level, "exp_needed")
            base_damage = max(1, base_exp // 10)
            base_hp = max(1, base_exp // 2)
            base_agility = max(1, base_damage // 2)
            base_speed = max(1, base_damage // 2)

        damage = int(self._randomize_base_value(base_damage) * atk_mult)
        hp = int(self._randomize_base_value(base_hp) * hp_mult)
        agility = self._randomize_base_value(base_agility)
        speed = self._randomize_base_value(base_speed)

        # 应用全局 PvE 难度系数
        difficulty_multiplier = self._global_difficulty_multiplier()
        damage = max(1, int(damage * difficulty_multiplier))
        hp = max(1, int(hp * difficulty_multiplier))
        armor_value = max(0, int(armor_value * difficulty_multiplier))

        # 修为奖励仍按敌人等级锚定
        exp_reward = self._get_level_base(enemy_level, "exp_needed")

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

        EnemyManager._spawn_counter += 1
        suffix = EnemyManager._spawn_counter
        random_token = f"{random.getrandbits(16):04x}"
        return Enemy(
            user_id=f"enemy_{template.get('key', 'unknown')}_{suffix}_{random_token}",
            name=name,
            hp=hp,
            max_hp=hp,
            damage=damage,
            agility=agility,
            speed=speed,
            armor_value=armor_value,
            exp=exp_reward,
            crit_rate=crit_rate,
            # 兼容旧字段
            mp=exp_reward,
            max_mp=exp_reward,
            atk=damage,
            defense=armor_value,
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

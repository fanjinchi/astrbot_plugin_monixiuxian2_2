"""Boss system manager - spawn, challenge, and reward world bosses.

Uses the new four-main-attribute framework: boss stats are generated from
level_config.json base values multiplied by boss-level multipliers and the
global PvE difficulty_multiplier. Old exp-derived hp/atk formulas are removed.
"""

from __future__ import annotations

import importlib.util
import os
import random
import sys
import time
from typing import TYPE_CHECKING

from astrbot.api import logger

if TYPE_CHECKING:
    from ..config_manager import ConfigManager
    from ..core import StorageRingManager
    from ..data.data_manager import DataBase


def _load_module(name, rel_path):
    """Load a module from a relative path for standalone execution."""
    plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(plugin_root, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    from ..models import Player
    from ..models_extended import Boss, UserStatus
    from .combat_manager import CombatManager, FighterState
except ImportError:
    _mod = _load_module("boss_manager_models", "models.py")
    Player = _mod.Player
    _mod_ext = _load_module("boss_manager_models_extended", "models_extended.py")
    Boss = _mod_ext.Boss
    UserStatus = _mod_ext.UserStatus
    _cm = _load_module("boss_manager_combat", "managers/combat_manager.py")
    CombatManager = _cm.CombatManager
    FighterState = _cm.FighterState


class BossManager:
    """Boss系统管理器 - 处理Boss生成、战斗、奖励等逻辑"""

    # 8 world-boss tiers mapped to the new decimal realm levels.
    # level_index matches the "level" field in level_config.json.
    BOSS_LEVELS = [
        {
            "name": "练气",
            "level_index": 1,
            "hp_mult": 1.0,
            "atk_mult": 1.0,
            "reward_mult": 1.0,
            "armor_value": 0,
        },
        {
            "name": "筑基",
            "level_index": 10,
            "hp_mult": 1.5,
            "atk_mult": 1.2,
            "reward_mult": 1.5,
            "armor_value": 0,
        },
        {
            "name": "金丹",
            "level_index": 20,
            "hp_mult": 2.0,
            "atk_mult": 1.5,
            "reward_mult": 2.0,
            "armor_value": 5,
        },
        {
            "name": "元婴",
            "level_index": 30,
            "hp_mult": 2.5,
            "atk_mult": 1.8,
            "reward_mult": 2.5,
            "armor_value": 10,
        },
        {
            "name": "化神",
            "level_index": 40,
            "hp_mult": 3.0,
            "atk_mult": 2.0,
            "reward_mult": 3.0,
            "armor_value": 20,
        },
        {
            "name": "炼虚",
            "level_index": 50,
            "hp_mult": 4.0,
            "atk_mult": 2.5,
            "reward_mult": 4.0,
            "armor_value": 40,
        },
        {
            "name": "合体",
            "level_index": 60,
            "hp_mult": 5.0,
            "atk_mult": 3.0,
            "reward_mult": 5.0,
            "armor_value": 70,
        },
        {
            "name": "大乘",
            "level_index": 70,
            "hp_mult": 6.0,
            "atk_mult": 3.5,
            "reward_mult": 6.0,
            "armor_value": 110,
        },
    ]

    # Backward-compatible mapping for old 36-level boss indices.
    _LEGACY_LEVEL_INDEX_MAP = {
        0: 1,
        3: 10,
        6: 20,
        9: 30,
        12: 40,
        15: 50,
        18: 60,
        21: 70,
    }

    # Boss名称池
    BOSS_NAMES = [
        "血魔",
        "邪修",
        "魔头",
        "妖王",
        "魔君",
        "异兽",
        "凶兽",
        "妖尊",
        "魔尊",
        "邪帝",
        "天魔",
        "地魔",
        "魔神",
        "妖神",
        "邪神",
    ]

    # Boss物品掉落表
    BOSS_DROP_TABLE = {
        "low": [  # 低级Boss (练气-金丹)
            {"name": "灵兽内丹", "weight": 40, "min": 1, "max": 2},
            {"name": "妖兽精血", "weight": 30, "min": 1, "max": 3},
            {"name": "玄铁", "weight": 30, "min": 3, "max": 6},
        ],
        "mid": [  # 中级Boss (元婴-化神)
            {"name": "灵兽内丹", "weight": 30, "min": 2, "max": 4},
            {"name": "星辰石", "weight": 25, "min": 2, "max": 4},
            {"name": "天材地宝", "weight": 20, "min": 1, "max": 2},
            {"name": "功法残页", "weight": 25, "min": 1, "max": 2},
        ],
        "high": [  # 高级Boss (炼虚及以上)
            {"name": "天材地宝", "weight": 30, "min": 2, "max": 4},
            {"name": "混沌精华", "weight": 25, "min": 1, "max": 2},
            {"name": "神兽之骨", "weight": 20, "min": 1, "max": 1},
            {"name": "远古秘籍", "weight": 15, "min": 1, "max": 1},
            {"name": "仙器碎片", "weight": 10, "min": 1, "max": 1},
        ],
    }

    def __init__(
        self,
        db: DataBase,
        combat_mgr: CombatManager,
        config_manager: ConfigManager | None = None,
        storage_ring_manager: StorageRingManager | None = None,
    ):
        self.db = db
        self.engine = getattr(combat_mgr, "engine", combat_mgr)
        self.storage_ring_manager = storage_ring_manager
        self.config_manager = config_manager
        self.config = config_manager.boss_config if config_manager else {}
        raw_levels = self.config.get("levels", self.BOSS_LEVELS)
        self.levels = [self._normalize_level_config(cfg) for cfg in raw_levels]

    def _normalize_level_config(self, cfg: dict) -> dict:
        """Normalize old 36-level indices to the new decimal realm levels."""
        normalized = dict(cfg)
        level_index = normalized.get("level_index", 1)
        if level_index in self._LEGACY_LEVEL_INDEX_MAP:
            normalized["level_index"] = self._LEGACY_LEVEL_INDEX_MAP[level_index]
        return normalized

    def _difficulty_multiplier(self) -> float:
        """Return the global PvE difficulty multiplier from game_config."""
        if self.config_manager is None:
            return 1.0
        return self.config_manager.game_config.get("pve", {}).get(
            "difficulty_multiplier", 1.0
        )

    def _get_level_base(self, level_index: int, key: str) -> int:
        """Read a base attribute from level_config by matching the level field.

        Falls back to array indexing if the level field is absent.
        """
        if not self.config_manager:
            return 0
        level_data = self.config_manager.get_level_data("灵修")
        for level_info in level_data:
            if level_info.get("level") == level_index:
                return level_info.get(key, 0)
        # Fallback: treat level_index as array index.
        if 0 <= level_index < len(level_data):
            return level_data[level_index].get(key, 0)
        return 0

    def _generate_boss_stats(self, level_config: dict) -> dict:
        """Generate four-main-attribute stats for a boss tier.

        Stats are derived from level_config base values multiplied by the
        boss-level multipliers and the global PvE difficulty_multiplier.
        """
        level_index = level_config.get("level_index", 1)
        hp_mult = level_config.get("hp_mult", 1.0)
        atk_mult = level_config.get("atk_mult", 1.0)
        base_armor = level_config.get("armor_value", 0)

        base = {
            "damage": self._get_level_base(level_index, "base_damage"),
            "agility": self._get_level_base(level_index, "base_agility"),
            "speed": self._get_level_base(level_index, "base_speed"),
            "hp": self._get_level_base(level_index, "base_hp"),
        }

        # Fallback for configs that still lack the new base attribute keys.
        if base["damage"] == 0 and base["hp"] == 0:
            logger.warning(
                f"Boss stats are missing base_* data for level_index={level_index}; "
                f"using exp_needed as a transitional fallback. Boss values are in a transitional state."
            )
            exp_needed = self._get_level_base(level_index, "exp_needed")
            base["damage"] = max(1, exp_needed // 10)
            base["hp"] = max(1, exp_needed // 2)
            base["agility"] = max(1, base["damage"] // 2)
            base["speed"] = max(1, base["damage"] // 2)

        difficulty = self._difficulty_multiplier()
        return {
            "damage": max(1, int(base["damage"] * atk_mult * difficulty)),
            "agility": max(1, int(base["agility"] * difficulty)),
            "speed": max(1, int(base["speed"] * difficulty)),
            "hp": max(1, int(base["hp"] * hp_mult * difficulty)),
            "armor_value": max(0, int(base_armor * difficulty)),
        }

    def _resolve_boss_stats(self, level_config: dict) -> dict:
        """Resolve the final boss stats, applying a small random variance to HP."""
        stats = self._generate_boss_stats(level_config)
        # Small HP variance to avoid perfectly uniform bosses.
        hp_var = random.uniform(0.95, 1.05)
        stats["hp"] = max(1, int(stats["hp"] * hp_var))
        return stats

    def _boss_stats_from_boss(self, boss: Boss) -> dict:
        """Recompute four-main-attribute stats from a persisted Boss object.

        Agility and speed are not stored in the old Boss schema, so they are
        derived from the boss's realm level.
        """
        level_config = self._get_level_config_by_name(boss.boss_level)
        if level_config is None:
            return {
                "damage": boss.atk,
                "agility": 5,
                "speed": 5,
                "hp": boss.hp,
                "armor_value": boss.defense,
            }
        stats = self._generate_boss_stats(level_config)
        # Preserve current HP from the persisted boss.
        stats["hp"] = boss.hp
        stats["max_hp"] = boss.max_hp
        return stats

    def _get_level_config_by_name(self, name: str) -> dict | None:
        """Find the BOSS_LEVELS entry whose name matches the boss realm."""
        for cfg in self.levels:
            if cfg.get("name") == name:
                return cfg
        return None

    def _get_level_config_by_level(self, level_index: int) -> dict | None:
        """Find the BOSS_LEVELS entry by level_index."""
        for cfg in self.levels:
            if cfg.get("level_index") == level_index:
                return cfg
        return None

    async def spawn_boss(
        self, base_exp: int = 0, level_config: dict | None = None
    ) -> tuple[bool, str, Boss | None]:
        """Generate a new world Boss.

        Args:
            base_exp: Legacy argument, kept for compatibility but ignored.
            level_config: Boss tier configuration. If None, a tier is chosen
                randomly.

        Returns:
            (success, message, Boss instance)
        """
        # 检查是否已有存活的Boss
        existing_boss = await self.db.ext.get_active_boss()
        if existing_boss:
            return False, f"❌ 当前已有Boss『{existing_boss.boss_name}』存在！", None

        # 选择Boss等级
        if not level_config:
            level_config = random.choice(self.levels)
        else:
            level_config = self._normalize_level_config(level_config)

        # 生成Boss名称
        boss_name = random.choice(self.BOSS_NAMES) + f"·{level_config['name']}境"

        # 计算Boss属性
        stats = self._resolve_boss_stats(level_config)
        max_hp = stats["hp"]
        reward_mult = level_config.get("reward_mult", 1.0)
        stone_reward = int(
            max(1, self._get_level_base(level_config["level_index"], "exp_needed"))
            * reward_mult
            // 10
        )

        # 创建Boss
        boss = Boss(
            boss_id=0,  # 自动生成
            boss_name=boss_name,
            boss_level=level_config["name"],
            hp=max_hp,
            max_hp=max_hp,
            atk=stats["damage"],
            defense=stats["armor_value"],
            stone_reward=stone_reward,
            create_time=int(time.time()),
            status=1,  # 1=存活
        )

        boss_id = await self.db.ext.create_boss(boss)
        boss.boss_id = boss_id

        msg = f"""
👹 Boss降临
━━━━━━━━━━━━━━━

{boss_name}降临世间！

境界：{level_config["name"]}
HP：{max_hp}
伤害：{stats["damage"]}
身法：{stats["agility"]}
迅捷：{stats["speed"]}
护甲：{stats["armor_value"]}
奖励：{stone_reward}灵石

快来挑战吧！
        """.strip()

        return True, msg, boss

    async def challenge_boss(self, user_id: str) -> tuple[bool, str, dict | None]:
        """挑战世界Boss.

        Args:
            user_id: 挑战者ID

        Returns:
            (成功标志, 消息, 战斗结果)
        """
        # 1. 检查玩家
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None

        # 2. 检查Boss是否存在
        boss = await self.db.ext.get_active_boss()
        if not boss:
            return False, "❌ 当前没有Boss！", None

        # 3. 检查玩家状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd:
            await self.db.ext.create_user_cd(user_id)
            user_cd = await self.db.ext.get_user_cd(user_id)

        if user_cd.type != UserStatus.IDLE:
            return False, "❌ 你当前正忙，无法挑战Boss！", None

        # 4. 构建玩家战斗状态
        player_fighter = await self.engine.build_fighter_from_player(player)

        # 5. 构建Boss战斗状态
        boss_stats = self._boss_stats_from_boss(boss)
        boss_fighter = FighterState(
            user_id=str(boss.boss_id),
            name=boss.boss_name,
            hp=boss_stats["hp"],
            max_hp=boss_stats.get("max_hp", boss.max_hp),
            damage=boss_stats["damage"],
            agility=boss_stats["agility"],
            speed=boss_stats["speed"],
            armor_value=boss_stats["armor_value"],
        )

        # 6. 开始战斗
        result = self.engine.resolve_combat(
            player_fighter, boss_fighter, combat_type="pve"
        )

        # 7. 处理战斗结果
        winner = result.winner
        damage_dealt = boss_fighter.max_hp - result.fighter2_final_hp
        damage_ratio = (
            damage_dealt / boss_fighter.max_hp if boss_fighter.max_hp > 0 else 0
        )

        if winner == user_id:
            # 玩家胜利
            boss.status = 0  # 标记Boss为已击败
            await self.db.ext.defeat_boss(boss.boss_id)

            reward = boss.stone_reward
            player.gold += reward

            # 物品掉落
            item_msg = ""
            dropped_items = []
            if self.storage_ring_manager:
                dropped_items = await self._roll_boss_drops(player, boss)
                if dropped_items:
                    item_lines = []
                    for item_name, count in dropped_items:
                        success, _ = await self.storage_ring_manager.store_item(
                            player, item_name, count, silent=True
                        )
                        if success:
                            item_lines.append(f"  · {item_name} x{count}")
                        else:
                            item_lines.append(
                                f"  · {item_name} x{count}（储物戒已满，丢失）"
                            )
                    if item_lines:
                        item_msg = "\n\n📦 获得物品：\n" + "\n".join(item_lines)

            result_msg = f"""
🎉 挑战成功！
━━━━━━━━━━━━━━━

你成功击败了『{boss.boss_name}』！

战斗回合数：{result.rounds}
获得灵石：{reward}{item_msg}

{player_fighter.name}
HP：{result.fighter1_final_hp}/{player_fighter.max_hp}
            """.strip()
        else:
            # 玩家失败或平局: consolation reward based on damage dealt.
            if winner == "draw":
                reward = int(boss.stone_reward * damage_ratio * 0.5)
            else:
                reward = int(boss.stone_reward * damage_ratio)
            reward = max(0, reward)

            boss.hp = result.fighter2_final_hp
            await self.db.ext.update_boss(boss)

            result_msg = f"""
💀 挑战失败
━━━━━━━━━━━━━━━

你被『{boss.boss_name}』击败了！

战斗回合数：{result.rounds}
安慰奖：{reward}灵石

{boss.boss_name} 剩余HP：{boss.hp}/{boss.max_hp}
            """.strip()

            if reward > 0:
                player.gold += reward

        # 更新玩家HP
        player.hp = result.fighter1_final_hp
        await self.db.update_player(player)

        # 返回完整战斗日志
        combat_log = "\n".join(result.combat_log)
        full_msg = combat_log + "\n\n" + result_msg

        battle_result = {
            "winner": result.winner,
            "combat_log": result.combat_log,
            "player_final_hp": result.fighter1_final_hp,
            "player_final_mp": result.fighter1_final_hp,
            "boss_final_hp": result.fighter2_final_hp,
            "reward": reward,
            "rounds": result.rounds,
        }

        return True, full_msg, battle_result

    async def get_boss_info(self) -> tuple[bool, str, Boss | None]:
        """获取当前Boss信息

        Returns:
            (成功标志, 消息, Boss对象)
        """
        boss = await self.db.ext.get_active_boss()
        if not boss:
            return False, "❌ 当前没有Boss！", None

        hp_percent = (boss.hp / boss.max_hp) * 100
        stats = self._boss_stats_from_boss(boss)

        msg = f"""
👹 当前Boss
━━━━━━━━━━━━━━━

名称：{boss.boss_name}
境界：{boss.boss_level}

HP：{boss.hp}/{boss.max_hp} ({hp_percent:.1f}%)
伤害：{stats["damage"]}
身法：{stats["agility"]}
迅捷：{stats["speed"]}
护甲：{stats["armor_value"]}

奖励：{boss.stone_reward}灵石

使用 /挑战Boss 来挑战！
        """.strip()

        return True, msg, boss

    async def auto_spawn_boss(
        self, player_count: int = 0
    ) -> tuple[bool, str, Boss | None]:
        """自动生成Boss（定时任务使用）
        根据服务器玩家平均境界自动调整Boss难度

        Args:
            player_count: 玩家数量（用于调整难度，保留兼容）

        Returns:
            (成功标志, 消息, Boss对象)
        """
        # 检查是否已有Boss
        existing_boss = await self.db.ext.get_active_boss()
        if existing_boss:
            return False, "当前已有Boss存在", None

        # 获取所有玩家的平均境界
        all_players = await self.db.get_all_players()
        if not all_players:
            level_config = self.levels[0]
        else:
            avg_level = sum(p.level_index for p in all_players) // len(all_players)
            # 选择不超过平均境界+5的最高档Boss
            level_config = None
            for cfg in self.levels:
                if cfg["level_index"] <= avg_level + 5:
                    level_config = cfg
            if level_config is None:
                level_config = self.levels[0]

        # 生成Boss
        return await self.spawn_boss(level_config=level_config)

    async def _roll_boss_drops(
        self, player: Player, boss: Boss
    ) -> list[tuple[str, int]]:
        """根据Boss等级随机掉落物品

        Args:
            player: 玩家对象
            boss: Boss对象

        Returns:
            掉落物品列表 [(物品名, 数量), ...]
        """
        dropped_items = []

        # 根据Boss等级确定掉落表
        level_config = self._get_level_config_by_name(boss.boss_level)
        boss_level_index = level_config.get("level_index", 0) if level_config else 0

        if boss_level_index <= 20:  # 练气-金丹
            drop_table = self.BOSS_DROP_TABLE["low"]
        elif boss_level_index <= 40:  # 元婴-化神
            drop_table = self.BOSS_DROP_TABLE["mid"]
        else:  # 炼虚及以上
            drop_table = self.BOSS_DROP_TABLE["high"]

        # Boss击杀100%掉落至少1件物品
        total_weight = sum(item["weight"] for item in drop_table)
        roll = random.randint(1, total_weight)

        current_weight = 0
        for item in drop_table:
            current_weight += item["weight"]
            if roll <= current_weight:
                count = random.randint(item["min"], item["max"])
                dropped_items.append((item["name"], count))
                break

        # 高级Boss有额外掉落概率
        if boss_level_index >= 30:  # 元婴及以上
            extra_chance = 50 if boss_level_index < 50 else 70
            if random.randint(1, 100) <= extra_chance:
                roll = random.randint(1, total_weight)
                current_weight = 0
                for item in drop_table:
                    current_weight += item["weight"]
                    if roll <= current_weight:
                        count = random.randint(item["min"], item["max"])
                        dropped_items.append((item["name"], count))
                        break

        return dropped_items

"""PVE战斗管理器 - 处理玩家vs环境的战斗触发、奖励计算和结果格式化。

现版本已接入统一 CombatEngine：敌人与玩家均被转换为 FighterState 后调用
``resolve_combat``，胜负判定与奖励规则保持不变。
"""

import importlib.util
import os
import random
import sys


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
    from ..managers.combat_manager import CombatEngine, CombatManager, FighterState
    from ..managers.enemy_manager import Enemy, EnemyManager
    from ..models import Player
except ImportError:
    # Standalone execution (for testing)
    _cm = _load_module("pve_combat_manager_combat", "managers/combat_manager.py")
    CombatEngine = _cm.CombatEngine
    CombatManager = _cm.CombatManager
    FighterState = _cm.FighterState

    _em = _load_module("pve_combat_manager_enemy", "managers/enemy_manager.py")
    EnemyManager = _em.EnemyManager
    Enemy = _em.Enemy

    _md = _load_module("pve_combat_manager_models", "models.py")
    Player = _md.Player


# 秘境层数 -> PVE 难度映射（4/5 层为 extreme，未知层数回退到 low）
RIFT_LEVEL_DIFFICULTY_MAP = {
    1: "low",
    2: "mid",
    3: "high",
    4: "extreme",
    5: "extreme",
}


class PVECombatManager:
    """PVE战斗管理器 - 处理战斗触发、敌人选择、奖励计算和结果格式化"""

    def __init__(
        self,
        combat_mgr: CombatManager,
        enemy_mgr: EnemyManager,
        config_manager=None,
        impart_manager=None,
    ):
        """
        初始化PVE战斗管理器

        Args:
            combat_mgr: 统一战斗引擎或其 Legacy 适配器。
            enemy_mgr: 敌人管理器，用于生成敌人
            config_manager: 配置管理器，可选，用于读取装备数据
            impart_manager: 传承管理器，可选，用于获取传承加成
        """
        # 兼容直接传入 CombatEngine 或 Legacy CombatManager
        self.combat_engine = getattr(combat_mgr, "engine", combat_mgr)
        self.enemy_mgr = enemy_mgr
        self.config_manager = config_manager
        self.impart_manager = impart_manager

    def _should_trigger_combat(self, scene: str, difficulty: str) -> bool:
        """
        判断是否应该触发战斗

        根据场景和难度返回基于概率的布尔值。

        Args:
            scene: 场景类型，"adventure"（历练）或 "rift"（秘境）
            difficulty: 难度等级，"low" / "mid" / "high" / "extreme"

        Returns:
            True 表示触发战斗，False 表示不触发
        """
        # 战斗触发概率配置
        encounter_rates = {
            "adventure": {
                "low": 0.30,
                "mid": 0.45,
                "high": 0.65,
                "extreme": 0.75,
            },
            "rift": {
                "low": 0.50,
                "mid": 0.70,
                "high": 0.90,
                "extreme": 0.95,
            },
        }

        rate = encounter_rates.get(scene, {}).get(difficulty, 0.0)
        return random.random() < rate

    def _select_enemy_category(self, scene: str, difficulty: str) -> str:
        """
        选择敌人类别

        根据场景和难度，按概率返回敌人类别。

        Args:
            scene: 场景类型，"adventure"（历练）或 "rift"（秘境）
            difficulty: 难度等级，"low" / "mid" / "high" / "extreme"

        Returns:
            敌人类别字符串："normal" / "elite" / "boss"
        """
        rand = random.random()

        if scene == "adventure":
            if difficulty == "low":
                return "normal"
            elif difficulty == "mid":
                if rand < 0.70:
                    return "normal"
                elif rand < 0.95:
                    return "elite"
                else:
                    return "boss"
            elif difficulty == "high":
                if rand < 0.40:
                    return "normal"
                elif rand < 0.80:
                    return "elite"
                else:
                    return "boss"
            elif difficulty == "extreme":
                if rand < 0.30:
                    return "normal"
                elif rand < 0.65:
                    return "elite"
                else:
                    return "boss"
        elif scene == "rift":
            if difficulty == "low":
                if rand < 0.80:
                    return "normal"
                else:
                    return "elite"
            elif difficulty == "mid":
                if rand < 0.50:
                    return "normal"
                elif rand < 0.85:
                    return "elite"
                else:
                    return "boss"
            elif difficulty == "high":
                if rand < 0.30:
                    return "normal"
                elif rand < 0.70:
                    return "elite"
                else:
                    return "boss"
            elif difficulty == "extreme":
                if rand < 0.20:
                    return "normal"
                elif rand < 0.60:
                    return "elite"
                else:
                    return "boss"

        # 默认返回普通敌人
        return "normal"

    def _build_enemy_fighter(self, enemy: Enemy) -> FighterState:
        """Build a FighterState directly from an Enemy object."""
        return FighterState(
            user_id=enemy.user_id,
            name=enemy.name,
            hp=enemy.hp,
            max_hp=enemy.max_hp,
            damage=enemy.damage,
            agility=enemy.agility,
            speed=enemy.speed,
            armor_value=enemy.armor_value,
        )

    def _calculate_rewards(
        self, result: dict, base_rewards: dict, enemy: Enemy
    ) -> dict:
        """
        计算战斗奖励

        根据战斗结果应用奖励倍率。

        Args:
            result: 战斗结果字典，包含winner等字段
            base_rewards: 基础奖励字典，包含exp、gold等
            enemy: 敌人对象，用于获取额外奖励

        Returns:
            计算后的奖励字典
        """
        rewards = {
            "exp": base_rewards.get("exp", 0),
            "gold": base_rewards.get("gold", 0),
            "bonus_exp": 0,
            "hp_penalty": False,
        }

        winner = result.get("winner", "")
        # In engine: winner = player.user_id if player wins, else enemy.user_id
        is_enemy_winner = isinstance(winner, str) and winner.startswith("enemy_")
        is_draw = winner == "draw"

        if is_draw:
            # 平局：奖励不变
            pass
        elif is_enemy_winner:
            rewards["exp"] = int(rewards["exp"] * 0.3)
            rewards["gold"] = 0
            consolation_reward = result.get("reward")
            if consolation_reward is not None:
                rewards["gold"] += consolation_reward
            rewards["hp_penalty"] = True
        else:
            # 胜利
            rewards["exp"] = int(rewards["exp"] * 1.2)
            rewards["bonus_exp"] = enemy.exp

        return rewards

    def _format_combat_result(self, result: dict, enemy: Enemy, rewards: dict) -> str:
        """
        格式化战斗结果消息

        Args:
            result: 战斗结果字典
            enemy: 敌人对象
            rewards: 奖励字典

        Returns:
            格式化的战斗结果字符串
        """
        lines = []
        lines.extend(result.get("combat_log", []))
        lines.append("")

        winner = result.get("winner", "")
        is_enemy_winner = isinstance(winner, str) and winner.startswith("enemy_")
        is_draw = winner == "draw"

        if is_draw:
            lines.append("⚖️ 战斗结果：平局")
        elif is_enemy_winner:
            lines.append("💀 战斗结果：战败")
        else:
            lines.append("🏆 战斗结果：胜利")

        lines.append("")
        lines.append("📦 战斗奖励：")
        if rewards.get("exp", 0) > 0:
            lines.append(f"  修为：+{rewards['exp']}")
        if rewards.get("bonus_exp", 0) > 0:
            lines.append(f"  额外修为：+{rewards['bonus_exp']}")
        if rewards.get("gold", 0) > 0:
            lines.append(f"  灵石：+{rewards['gold']}")
        if rewards.get("hp_penalty"):
            lines.append("  ⚠️ 气血受损，需休养恢复")

        lines.append("")
        lines.append(f"💚 剩余气血：{result.get('player_final_hp', 0)}")
        lines.append(f"💙 剩余真元：{result.get('player_final_mp', 0)}")

        return "\n".join(lines)

    async def trigger_pve_combat(
        self,
        player: Player,
        scene: str,
        difficulty: str,
        base_rewards: dict | None = None,
    ) -> tuple[str, dict] | None:
        """
        触发PVE战斗的主入口

        完整的战斗流程：判定触发 → 选择敌人 → 生成敌人 → 构建双方 FighterState
        → 调用统一 CombatEngine → 计算奖励 → 格式化结果

        Args:
            player: 玩家对象
            scene: 场景类型，"adventure"（历练）或 "rift"（秘境）
            difficulty: 难度等级，"low" / "mid" / "high" / "extreme"
            base_rewards: 基础奖励字典，可选，默认{"exp": 100, "gold": 50}

        Returns:
            战斗结果消息字符串，未触发战斗时返回None
        """
        from astrbot.api import logger

        # 1. 检查是否触发战斗
        if not self._should_trigger_combat(scene, difficulty):
            return None

        # 2. 选择敌人类别
        category = self._select_enemy_category(scene, difficulty)

        # 3. 生成敌人
        try:
            enemy = self.enemy_mgr.spawn_enemy(player.level_index, category)
        except Exception as e:
            logger.error(f"生成敌人失败: {e}")
            return None

        # 4. 构建玩家与敌人的 FighterState
        player_fighter = await self.combat_engine.build_fighter_from_player(player)
        enemy_fighter = self._build_enemy_fighter(enemy)

        # 5. 执行统一战斗引擎
        result = self.combat_engine.resolve_combat(
            player_fighter, enemy_fighter, combat_type="pve"
        )

        # 6. 将战斗后的当前 HP 写回玩家对象
        player.hp = result.fighter1_final_hp

        # 7. 计算奖励
        if base_rewards is None:
            base_rewards = {"exp": 100, "gold": 50}

        # Build the legacy-style result dict used by reward calculation
        legacy_result = {
            "winner": result.winner,
            "combat_log": result.combat_log,
            "player_final_hp": result.fighter1_final_hp,
            "player_final_mp": result.fighter1_final_hp,
            "reward": 0,
        }
        rewards = self._calculate_rewards(legacy_result, base_rewards, enemy)

        # 8. 格式化并返回结果
        msg = self._format_combat_result(legacy_result, enemy, rewards)
        return msg, rewards

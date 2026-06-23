# managers/pve_combat_manager.py
"""
PVE战斗管理器 - 处理玩家vs环境的战斗触发、奖励计算和结果格式化
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
    from ..managers.combat_manager import CombatManager, CombatStats
    from ..managers.enemy_manager import Enemy, EnemyManager
    from ..models import Player
except ImportError:
    # Standalone execution (for testing)
    # Use prefixed module names to avoid colliding with real package imports.
    _cm = _load_module("pve_combat_manager_combat", "managers/combat_manager.py")
    CombatManager = _cm.CombatManager
    CombatStats = _cm.CombatStats

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


def calculate_equipment_atk_bonus(player: Player, config_manager) -> int:
    """
    计算装备提供的攻击力加成

    与 handlers/combat_handlers.py:_calculate_equipment_bonus 对齐，
    仅统计武器的 atk、physical_damage、magic_damage。

    Args:
        player: 玩家对象
        config_manager: 配置管理器，包含武器数据

    Returns:
        装备提供的总攻击力加成，无配置或装备时返回0
    """
    if not config_manager:
        return 0

    total_atk = 0

    # 武器
    if player.weapon and player.weapon in config_manager.weapons_data:
        data = config_manager.weapons_data[player.weapon]
        total_atk += data.get("atk", 0)
        total_atk += data.get("physical_damage", 0)
        total_atk += data.get("magic_damage", 0)

    return total_atk


def calculate_equipment_defense(player: Player, config_manager) -> int:
    """
    计算装备提供的防御力

    与 handlers/combat_handlers.py:_calculate_equipment_bonus 对齐，
    仅统计防具的 physical_defense 和 magic_defense。

    Args:
        player: 玩家对象
        config_manager: 配置管理器，包含物品数据

    Returns:
        装备提供的总防御力，无配置或装备时返回0
    """
    if not config_manager:
        return 0

    total_defense = 0

    # 防具
    if player.armor and player.armor in config_manager.items_data:
        data = config_manager.items_data[player.armor]
        total_defense += data.get("physical_defense", 0)
        total_defense += data.get("magic_defense", 0)

    return total_defense


class PVECombatManager:
    """PVE战斗管理器 - 处理战斗触发、敌人选择、奖励计算和结果格式化"""

    def __init__(
        self, combat_mgr: CombatManager, enemy_mgr: EnemyManager, config_manager=None
    ):
        """
        初始化PVE战斗管理器

        Args:
            combat_mgr: 战斗系统管理器，用于执行战斗计算
            enemy_mgr: 敌人管理器，用于生成敌人
            config_manager: 配置管理器，可选，用于读取装备数据
        """
        self.combat_mgr = combat_mgr
        self.enemy_mgr = enemy_mgr
        self.config_manager = config_manager

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

    async def _build_player_combat_stats(self, player: Player) -> CombatStats:
        """
        构建玩家战斗属性

        从Player对象计算完整的CombatStats，包括传承加成和装备防御。

        Args:
            player: 玩家对象

        Returns:
            玩家的CombatStats对象
        """
        # Import logger inside method to avoid import issues
        from astrbot.api import logger

        # 获取传承信息用于buff加成
        # 由于PVECombatManager不直接持有db引用，这里使用config_manager获取传承信息
        # 如果config_manager可用且有相关方法，则调用；否则使用默认值
        hp_buff = 0.0
        mp_buff = 0.0
        atk_buff = 0.0
        crit_rate = 0

        # 尝试从config_manager获取传承信息（如果支持）
        if self.config_manager and hasattr(self.config_manager, "db"):
            try:
                impart_info = await self.config_manager.db.ext.get_impart_info(
                    player.user_id
                )
                if impart_info:
                    hp_buff = getattr(impart_info, "impart_hp_per", 0.0) or 0.0
                    mp_buff = getattr(impart_info, "impart_mp_per", 0.0) or 0.0
                    atk_buff = getattr(impart_info, "impart_atk_per", 0.0) or 0.0
                    # impart_know_per 以小数存储（0.1 = 10%），乘以 100 并四舍五入转为整数百分比
                    raw_crit = getattr(impart_info, "impart_know_per", 0.0) or 0.0
                    crit_rate = int(round(raw_crit * 100))
            except Exception as e:
                logger.warning(f"获取传承信息失败: {e}")

        # 计算最大HP/MP（按修为计算）
        max_hp, max_mp = self.combat_mgr.calculate_hp_mp(
            player.experience, hp_buff, mp_buff
        )

        # 计算基础攻击力
        base_atk = self.combat_mgr.calculate_atk(
            player.experience, player.atkpractice, atk_buff
        )

        # 计算装备攻击加成（与 _prepare_combat_stats 对齐）
        equipment_atk_bonus = calculate_equipment_atk_bonus(player, self.config_manager)
        final_atk = base_atk + equipment_atk_bonus

        # 计算装备防御（仅防具，与 _prepare_combat_stats 对齐）
        equipment_defense = calculate_equipment_defense(player, self.config_manager)

        return CombatStats(
            user_id=player.user_id,
            name=player.user_name if player.user_name else f"道友{player.user_id}",
            hp=player.hp,
            max_hp=max_hp,
            mp=player.mp,
            max_mp=max_mp,
            atk=final_atk,
            defense=equipment_defense,
            crit_rate=crit_rate,
            exp=player.experience,
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
        # In player_vs_boss: winner = player.user_id if player wins, else boss.user_id
        # Enemy user_id starts with "enemy_", so we check that to determine if enemy won
        is_enemy_winner = isinstance(winner, str) and winner.startswith("enemy_")
        is_draw = winner == "平局"

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
        is_draw = winner == "平局"

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

        完整的战斗流程：判定触发 → 选择敌人 → 生成敌人 → 构建玩家属性 → 执行战斗 → 计算奖励 → 格式化结果

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

        # 4. 构建玩家战斗属性
        player_stats = await self._build_player_combat_stats(player)

        # 5. 将敌人转换为 CombatStats
        enemy_stats = CombatStats(
            user_id=enemy.user_id,
            name=enemy.name,
            hp=enemy.hp,
            max_hp=enemy.max_hp,
            mp=enemy.mp,
            max_mp=enemy.max_mp,
            atk=enemy.atk,
            defense=enemy.defense,
            crit_rate=enemy.crit_rate,
            exp=enemy.exp,
        )

        # 6. 执行战斗
        result = self.combat_mgr.player_vs_boss(player_stats, enemy_stats)

        # 7. 将战斗后的当前 HP/MP 写回玩家对象
        player.hp = player_stats.hp
        player.mp = player_stats.mp

        # 8. 计算奖励
        if base_rewards is None:
            base_rewards = {"exp": 100, "gold": 50}
        rewards = self._calculate_rewards(result, base_rewards, enemy)

        # 9. 格式化并返回结果
        msg = self._format_combat_result(result, enemy, rewards)
        return msg, rewards

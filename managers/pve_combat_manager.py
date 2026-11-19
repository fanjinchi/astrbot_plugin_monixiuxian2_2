"""PVE战斗管理器 - 处理玩家vs环境的战斗触发、奖励计算和结果格式化。

现版本已接入统一 CombatEngine：敌人与玩家均被转换为 FighterState 后调用
``resolve_combat``，胜负判定与奖励规则保持不变。
"""

import importlib.util
import os
import random
import sys
from dataclasses import asdict
from typing import NamedTuple


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
    from ..managers.enemy_catalog import build_enemy_fighter
    from ..managers.enemy_manager import Enemy, EnemyManager
    from ..models import Player
except ImportError:
    # Standalone execution (for testing)
    _ec = _load_module("pve_combat_manager_enemy_catalog", "managers/enemy_catalog.py")
    build_enemy_fighter = _ec.build_enemy_fighter

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


class RiftBeastResult(NamedTuple):
    """Combat-only outcome of an optional rift beast challenge (design D5).

    Reward assembly (enemy exp credit, drop roll) stays in
    ``RiftManager.accept_beast_challenge``; this layer only reports what the
    fight decided. ``draw`` is reported separately so the caller can treat it
    as a failed challenge (与传承口径一致).
    """

    won: bool  # True only when the engine winner is the player (explicit compare)
    draw: bool  # 平局单列：调用方视同挑战失败
    battle_msg: str  # 战报（无奖励结算内容）
    enemy_exp: int  # 敌人修为，胜利时由调用方入账


class PreparedEncounter(NamedTuple):
    """An encounter whose enemy is locked but not yet fought (child C R1).

    ``enemy`` is the spawned :class:`Enemy`; the adventure settlement serializes
    it into ``adventure_settlements.snapshot`` (``dataclasses.asdict`` is
    JSON-safe here: every field is a number, string or list of dicts) so a
    later 迎战 — even after a process restart — fights *this* enemy instead of
    re-rolling a new one.
    """

    enemy: Enemy
    category: str  # normal / elite / boss（审计与文案用）
    difficulty: str  # low / mid / high / extreme


class EncounterOutcome(NamedTuple):
    """Result of running the engine over a locked encounter (child C design §2.2).

    ``rewards``/``message`` are the same shapes ``trigger_pve_combat`` has always
    returned; ``player_final_hp`` is exposed separately because the adventure
    settlement writes it back through the Health Domain inside its own short
    transaction (defeat floor included), not here.
    """

    message: str  # 战报文案
    rewards: dict  # 含 exp/gold/bonus_exp/hp_penalty/pve_won
    player_final_hp: int  # 引擎给出的玩家终值气血（未套败场地板）
    winner: str  # 引擎胜者 user_id，平局为 "draw"
    enemy_defeated: bool  # 敌方被击败（写 adventure_settlements.defeated）


class PVECombatManager:
    """PVE战斗管理器 - 处理战斗触发、敌人选择、奖励计算和结果格式化"""

    def __init__(
        self,
        combat_mgr: CombatManager,
        enemy_mgr: EnemyManager,
        config_manager=None,
        health_service=None,
        catalog=None,
    ):
        """
        初始化PVE战斗管理器

        Args:
            combat_mgr: 统一战斗引擎或其 Legacy 适配器。
            enemy_mgr: 敌人管理器，用于生成敌人
            config_manager: 配置管理器，可选，用于读取装备与战斗配置。
            health_service: Health Domain，负责败场地板与战斗气血持久化。
            catalog: 固定名册 ``EnemyCatalog``（D 装配、E2 注入）。非 ``None``
                时普通 PVE 默认出怪走固定名册；``None``（未 sync / 回滚）保持
                旧动态派生，不半切。
        """
        # 兼容直接传入 CombatEngine 或 Legacy CombatManager
        self.combat_engine = getattr(combat_mgr, "engine", combat_mgr)
        self.enemy_mgr = enemy_mgr
        self.config_manager = config_manager
        self.health_service = health_service
        self.catalog = catalog

    def _difficulty_multiplier(self) -> float:
        """Read ``game_config["pve"]["difficulty_multiplier"]`` once per spawn.

        The global knob was previously read inside ``EnemyManager.spawn_enemy``;
        the fixed-roster path needs it passed explicitly so the knob keeps
        affecting every normal PVE encounter. Missing config / ``None`` falls
        back to 1.0 (same contract as the legacy manager).

        Returns:
            The configured multiplier, or 1.0 when absent/unreadable.
        """
        config_manager = getattr(self, "config_manager", None)
        game_config = getattr(config_manager, "game_config", None)
        if isinstance(game_config, dict):
            pve = game_config.get("pve", {})
            if isinstance(pve, dict):
                value = pve.get("difficulty_multiplier", 1.0)
                if value is not None:
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        return 1.0
        return 1.0

    def _spawn_default_enemy(self, player_level: int, category: str):
        """Spawn a normal PVE enemy from the fixed roster or the legacy path.

        This is the single cutover seam for ordinary encounters: ``catalog``
        present means the 28-entry roster; absent means the legacy dynamic
        derivation stays authoritative (v1 fallback, no half cutover).

        Args:
            player_level: Player's ``level_index`` (1-based).
            category: ``normal`` / ``elite`` / ``boss``.

        Returns:
            An ``Enemy`` carrier ready for the combat engine.
        """
        if self.catalog is not None:
            return self.catalog.spawn_enemy(
                player_level,
                category,
                difficulty_multiplier=self._difficulty_multiplier(),
            )
        return self.enemy_mgr.spawn_enemy(player_level, category)

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
        """Build a FighterState via the single fixed-roster mapper (Child B R3).

        映射逻辑收敛到 ``managers/enemy_catalog.build_enemy_fighter``：名册、
        动态临时路径、秘境兽/传承守护共用同一个 Enemy→Fighter 口径。
        普通 PVE 的缺省暴击只从 ConfigManager 读取；测试替身或 None/缺键
        回退 0.15，不能从形态不固定的 combat_engine 读取。
        """
        base_crit_rate = 0.15
        config_manager = getattr(self, "config_manager", None)
        game_config = getattr(config_manager, "game_config", None)
        if isinstance(game_config, dict):
            combat = game_config.get("combat", {})
            if isinstance(combat, dict):
                configured = combat.get("base_crit_rate")
                if configured is not None:
                    base_crit_rate = configured
        return build_enemy_fighter(enemy, base_crit_rate=base_crit_rate)

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
            "pve_won": False,  # 玩家是否获胜（师承任务链 win_pve 计数依据）
        }

        winner = result.get("winner", "")
        # Explicit equality against the enemy's own user_id (engine winner is
        # player.user_id or enemy.user_id; never prefix-matching, spec D6).
        is_enemy_winner = winner == enemy.user_id
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
            rewards["pve_won"] = True

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
        is_enemy_winner = winner == enemy.user_id
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
        触发PVE战斗的主入口（一次性同步路径：秘境以外的旧调用方）

        完整的战斗流程：判定触发 → 选择敌人 → 生成敌人 → 构建双方 FighterState
        → 调用统一 CombatEngine → 计算奖励 → 格式化结果。历练结算不再走这里：
        它需要把「锁定敌人」与「开打」拆到两个时刻，见 :meth:`prepare_encounter`
        与 :meth:`fight_prepared`。

        Args:
            player: 玩家对象
            scene: 场景类型，"adventure"（历练）或 "rift"（秘境）
            difficulty: 难度等级，"low" / "mid" / "high" / "extreme"
            base_rewards: 基础奖励字典，可选，默认{"exp": 100, "gold": 50}

        Returns:
            战斗结果消息字符串，未触发战斗时返回None
        """
        prepared = self.prepare_encounter(player, scene, difficulty)
        if prepared is None:
            return None

        outcome = await self.fight_prepared(player, prepared.enemy, base_rewards)
        # 6. 将战斗后的当前 HP 写回玩家对象
        # child A：写回的是 current_hp 层（引擎已在 fighter 动态上限内给出终值）
        player.current_hp = outcome.player_final_hp
        return outcome.message, outcome.rewards

    def prepare_encounter(
        self, player: Player, scene: str, difficulty: str
    ) -> PreparedEncounter | None:
        """Lock an encounter without rolling any combat randomness.

        历练结算状态机（child C）在「完成历练」那一刻调用本方法：敌人身份必须
        与战斗分开持久化，之后迎战/逃跑失败/replay 都复用同一只敌人，绝不重掷
        （PRD R1）。本方法只消耗触发判定与类别选择的随机数，不打战斗。

        Args:
            player: 参战玩家（用其境界决定怪物档位）.
            scene: ``"adventure"`` / ``"rift"``.
            difficulty: ``low`` / ``mid`` / ``high`` / ``extreme``.

        Returns:
            :class:`PreparedEncounter`；未触发战斗或敌人生成失败时 ``None``。

        The default spawn goes through :meth:`_spawn_default_enemy`: a loaded
        catalog serves the fixed 28-entry roster (difficulty multiplier passed
        explicitly), otherwise the legacy dynamic path is kept intact.
        """
        from astrbot.api import logger

        if not self._should_trigger_combat(scene, difficulty):
            return None
        category = self._select_enemy_category(scene, difficulty)
        try:
            enemy = self._spawn_default_enemy(player.level_index, category)
        except Exception as exc:
            logger.error(f"生成敌人失败: {exc}")
            return None
        return PreparedEncounter(enemy=enemy, category=category, difficulty=difficulty)

    @staticmethod
    def enemy_to_record(enemy: Enemy) -> dict:
        """Serialize a locked enemy into JSON-safe snapshot form.

        Enemy 是扁平 dataclass，字段全是数字/字符串/list[dict]，``asdict`` 可直接
        JSON 往返；历练结算把它塞进 ``adventure_settlements.snapshot``，重启后仍能
        重建同一只怪（PRD R1「锁定一次」）。序列化形状属于战斗层，故由本模块提供，
        历练层不 import ``Enemy``。

        Args:
            enemy: 已生成的敌人。

        Returns:
            可 JSON 序列化的字段字典。
        """
        return asdict(enemy)

    @staticmethod
    def enemy_from_record(record: dict) -> Enemy:
        """Rebuild a locked enemy from its snapshot record.

        Args:
            record: :meth:`enemy_to_record` 写出的字典。

        Returns:
            等价于锁定时刻的 :class:`Enemy`。
        """
        return Enemy(**record)

    async def fight_prepared(
        self,
        player: Player,
        enemy: Enemy,
        base_rewards: dict | None = None,
        *,
        rng_seed: int | None = None,
    ) -> EncounterOutcome:
        """Run the combat engine over a locked enemy and shape its rewards.

        纯计算侧：不写回玩家气血（那是调用方结算边界的事，child C 要在同一个短
        事务里经 Health Domain 写，见 design §2.2）。

        Args:
            player: 参战玩家；只读，不写 ``current_hp``。
            enemy: 已锁定的敌人（可来自 settlement snapshot 重建）。
            base_rewards: 路线基础收益，缺省 ``{"exp": 100, "gold": 50}``。
            rng_seed: 确定性重算用的种子（settlement ``snapshot.rng_seed``）。
                给定时在引擎计算前后保存/还原全局 RNG 状态，使同一 snapshot 重放
                出同一结果；省略时沿用现网的全局随机流（秘境等一次性路径）。

        Returns:
            :class:`EncounterOutcome`（战报文案、奖励、引擎终值气血、胜负）。
        """
        if base_rewards is None:
            base_rewards = {"exp": 100, "gold": 50}

        player_fighter = await self.combat_engine.build_fighter_from_player(player)
        enemy_fighter = self._build_enemy_fighter(enemy)
        result = self._roll_combat(player_fighter, enemy_fighter, rng_seed)

        legacy_result = {
            "winner": result.winner_id if result.winner_side != "draw" else "draw",
            "combat_log": result.combat_log,
            "player_final_hp": result.fighter1_final_hp,
            "player_final_mp": result.fighter1_final_hp,
            "reward": 0,
        }
        rewards = self._calculate_rewards(legacy_result, base_rewards, enemy)
        msg = self._format_combat_result(legacy_result, enemy, rewards)
        return EncounterOutcome(
            message=msg,
            rewards=rewards,
            player_final_hp=int(result.fighter1_final_hp),
            winner=legacy_result["winner"],
            enemy_defeated=result.winner_side == "fighter1",
        )

    def _roll_combat(
        self,
        player_fighter: FighterState,
        enemy_fighter: FighterState,
        rng_seed: int | None,
    ):
        """Call the engine, optionally pinned to a reproducible RNG stream.

        CombatEngine 用的是进程全局 ``random``（不改引擎签名，那是 child D/E 的
        共享面），所以确定性重放靠「保存→按 seed 重置→计算→还原」实现。整段
        没有 await 点，单线程事件循环内不会被别的协程插入，restore 之后全局流与
        结算前一致（与 :meth:`CombatEngine._narrative` 同一手法）。

        Args:
            player_fighter: 玩家战斗对象。
            enemy_fighter: 敌方战斗对象。
            rng_seed: 锁定在 snapshot 里的种子；None 表示不干预全局流。

        Returns:
            ``CombatResult``。
        """
        if rng_seed is None:
            return self.combat_engine.resolve_combat(
                player_fighter, enemy_fighter, combat_type="pve"
            )
        saved = random.getstate()
        try:
            random.seed(rng_seed)
            return self.combat_engine.resolve_combat(
                player_fighter, enemy_fighter, combat_type="pve"
            )
        finally:
            random.setstate(saved)

    async def challenge_rift_beast(
        self, player: Player, enemy_group_key: str | None = None
    ) -> RiftBeastResult | None:
        """Fight the rift beast of a pending encounter (combat only, design D5).

        只负责战斗：敌人选择 + 引擎结算 + HP 写回；修为/掉落奖励组装留在
        RiftManager.accept_beast_challenge，本方法不反向依赖 rift 管理器。

        Args:
            player: 应战的玩家。
            enemy_group_key: 秘境条目配置的定向怪物组 key；None 时回落按玩家
                境界匹配的全局怪物池（spec「缺省回落全局池」）。

        Returns:
            RiftBeastResult；敌人生成失败（配置缺失等异常）时返回 None。
        """
        from astrbot.api import logger

        # 1. 生成妖兽：有组 key 走定向生成（user_id 为 guardian_ 前缀，绕开普通
        #    分组匹配）；无则回落全局池，类别沿用秘境 low 难度分布
        #    （normal 80%/elite 20%，即旧结算自动 PvE low 档的选择口径）
        try:
            if enemy_group_key:
                enemy = self.enemy_mgr.spawn_enemy_from_group(
                    enemy_group_key, player.level_index
                )
            else:
                category = self._select_enemy_category("rift", "low")
                enemy = self._spawn_default_enemy(player.level_index, category)
        except Exception as e:
            logger.error(f"生成秘境妖兽失败: {e}")
            return None

        # 2. 构建双方 FighterState 并结算
        player_fighter = await self.combat_engine.build_fighter_from_player(player)
        enemy_fighter = self._build_enemy_fighter(enemy)
        result = self.combat_engine.resolve_combat(
            player_fighter, enemy_fighter, combat_type="pve"
        )

        # 3. 胜负必须显式比较 user_id（design D5）：接口已结构化
        #    （winner_id/winner_side），定向组敌人 user_id 是 guardian_ 前缀，
        #    前缀判定不可复活。平局单列，调用方视同挑战失败。
        won = result.winner_id == player.user_id
        is_draw = result.winner_side == "draw"

        # 4. Health Domain owns the write: wins keep the engine final value;
        #    losses/draws use the shared 1% dynamic-max floor.
        final_hp = result.fighter1_final_hp
        if not won:
            final_hp = max(final_hp, self.health_service.defeat_hp_floor(player))
        final_hp = await self.health_service.set_current_hp(player, final_hp)

        # 5. 组织战报（无奖励结算；奖励由 RiftManager 组装）
        lines = list(result.combat_log or [])
        lines.append("")
        lines.append(f"🐺 拦路妖兽：{enemy.name}")
        if is_draw:
            lines.append("⚖️ 你与妖兽战成平手，它咆哮着退回了密林。")
        elif won:
            lines.append("🏆 你击败了拦路妖兽！")
        else:
            lines.append("💀 你不敌妖兽，被重创而退（气血受损，需休养恢复）。")
        lines.append(f"💚 剩余气血：{final_hp}")
        return RiftBeastResult(won, is_draw, "\n".join(lines), enemy.exp)

    async def challenge_legacy_guardian(self, player: Player) -> tuple[bool, str]:
        """发起传承之地守护 NPC 挑战（获取传承的前置门槛）。

        独立函数而非复用 trigger_pve_combat：无概率触发、无修为/灵石/
        掉落结算；败场/平局经 Health Domain 套用 1% 动态上限地板，胜场不保底。

        Args:
            player: 发起挑战的玩家。

        Returns:
            (是否获胜, 战斗结果消息)。
        """
        from astrbot.api import logger

        # 1. 生成守护 NPC（强度与玩家境界匹配；组 key 由
        #    IMPART_CONFIG.guardian.enemy_group 配置驱动）
        try:
            enemy = self.enemy_mgr.spawn_enemy_from_group(
                self.enemy_mgr.get_guardian_group_key(), player.level_index
            )
        except Exception as e:
            logger.error(f"生成传承守护者失败: {e}")
            return False, "❌ 传承之地异常，请稍后再试。"

        # 2. 构建双方 FighterState 并结算
        player_fighter = await self.combat_engine.build_fighter_from_player(player)
        enemy_fighter = self._build_enemy_fighter(enemy)
        result = self.combat_engine.resolve_combat(
            player_fighter, enemy_fighter, combat_type="pve"
        )

        # 3. Persist through HealthService so direct rift and sect-claim callers
        #    share exactly the same defeat floor and restart-safe write.
        final_hp = result.fighter1_final_hp
        is_draw = result.winner_side == "draw"
        won = result.winner_id == player.user_id
        if not won:
            final_hp = max(final_hp, self.health_service.defeat_hp_floor(player))
        final_hp = await self.health_service.set_current_hp(player, final_hp)

        # 4. 组织结果消息（无奖励结算）
        lines = list(result.combat_log or [])
        lines.append("")
        lines.append(f"🗿 传承之地守护者：{enemy.name}")
        if is_draw:
            lines.append("⚖️ 与守护者战成平手，传承之地暂时关闭，请择日再来。")
        elif won:
            lines.append("🏆 你战胜了守护者，传承之地为你开启！")
        else:
            lines.append("💀 你不敌守护者，被送出传承之地（气血未竭，可再次尝试）。")
        lines.append(f"💚 剩余气血：{final_hp}")
        return won, "\n".join(lines)

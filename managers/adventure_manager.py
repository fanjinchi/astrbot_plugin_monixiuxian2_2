# managers/adventure_manager.py
"""
历练系统管理器 - 可配置路线、风险与奖励
"""

import hashlib
import importlib.util
import json
import math
import os
import random
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from astrbot.api import logger

try:
    from ..core.encounter_store import KIND_LEGACY, EncounterStore
    from ..data.data_manager import DataBase
    from ..data.default_configs import ADVENTURE_CONFIG
    from ..data.pve_repository import (
        CONSUMER_ADVENTURE_SETTLEMENT,
        EFFECT_BASE_REWARD,
        EFFECT_LEGACY_TRIGGER,
        EFFECT_ROUTE_DROPS,
        STATE_ADVENTURING,
        STATE_PENDING_CHOICE,
        STATE_READY_COMBAT,
        STATE_RESOLVED_FLED,
        STATE_RESOLVED_LOSS,
        STATE_RESOLVED_WIN,
        TERMINAL_STATES,
        AdventureRepository,
        settlement_outcome,
        snapshot_text,
    )
    from ..managers.pve_combat_manager import PVECombatManager
    from ..models import Player
    from ..models_extended import UserStatus
    from ..utils.narrative_text import select_narrative_pool
except ImportError:
    # 独立运行（测试）时降级加载依赖
    def _load_module(name, rel_path):
        """Import a plugin module by file path so this file can run standalone under tests."""
        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(plugin_root, rel_path)
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    def _load_default_configs():
        """Load data/default_configs.py under a synthetic package.

        default_configs relatively imports its narrative_defaults package, so
        the plain file-path loader above cannot satisfy it; a synthetic parent
        package gives the relative import a resolution context.
        """
        import types

        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pkg_name = "adventure_manager_standalone_data"
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = [os.path.join(plugin_root, "data")]
            sys.modules[pkg_name] = pkg
        full_name = f"{pkg_name}.default_configs"
        if full_name in sys.modules:
            return sys.modules[full_name]
        path = os.path.join(plugin_root, "data", "default_configs.py")
        spec = importlib.util.spec_from_file_location(full_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = mod
        spec.loader.exec_module(mod)
        return mod

    DataBase = object
    _pve = _load_module("pve_combat_manager", "managers/pve_combat_manager.py")
    PVECombatManager = _pve.PVECombatManager
    _md = _load_module("models", "models.py")
    Player = _md.Player
    _mde = _load_module("models_extended", "models_extended.py")
    UserStatus = _mde.UserStatus
    _nt = _load_module("narrative_text", "utils/narrative_text.py")
    select_narrative_pool = _nt.select_narrative_pool
    ADVENTURE_CONFIG = _load_default_configs().ADVENTURE_CONFIG
    _es = _load_module("encounter_store", "core/encounter_store.py")
    EncounterStore = _es.EncounterStore
    KIND_LEGACY = _es.KIND_LEGACY
    # 结算状态机基座（child P 仓储）：standalone 加载时同样按文件路径取
    _pr = _load_module("pve_repository", "data/pve_repository.py")
    AdventureRepository = _pr.AdventureRepository
    settlement_outcome = _pr.settlement_outcome
    snapshot_text = _pr.snapshot_text
    CONSUMER_ADVENTURE_SETTLEMENT = _pr.CONSUMER_ADVENTURE_SETTLEMENT
    EFFECT_BASE_REWARD = _pr.EFFECT_BASE_REWARD
    EFFECT_ROUTE_DROPS = _pr.EFFECT_ROUTE_DROPS
    EFFECT_LEGACY_TRIGGER = _pr.EFFECT_LEGACY_TRIGGER
    STATE_ADVENTURING = _pr.STATE_ADVENTURING
    STATE_PENDING_CHOICE = _pr.STATE_PENDING_CHOICE
    STATE_READY_COMBAT = _pr.STATE_READY_COMBAT
    STATE_RESOLVED_FLED = _pr.STATE_RESOLVED_FLED
    STATE_RESOLVED_LOSS = _pr.STATE_RESOLVED_LOSS
    STATE_RESOLVED_WIN = _pr.STATE_RESOLVED_WIN
    TERMINAL_STATES = _pr.TERMINAL_STATES

if TYPE_CHECKING:
    from ..core import BusyState, StorageRingManager

# GM「时间快进」覆盖条目（openspec change: gm-time-skip-registry）：声明即覆盖，
# 只前移参与到期/冷却判定的时间戳。由 core/time_skip_registry.py 装配汇总。
# v39 历练休整（child C，乙案全局窗口）：adventure_fatigue.fatigue_until 是**跨路线
# 通用**的休整到期时刻；历练忙碌本身走 user_cd（core/busy_state 已覆盖），此处只登记疲劳表。
TIME_SKIP_ENTRIES: tuple[tuple[str, str], ...] = (
    (
        "历练休整到期时间",
        "UPDATE adventure_fatigue "
        "SET fatigue_until = fatigue_until - ? "
        "WHERE fatigue_until > 0",
    ),
)

# 逃跑成功率公式（design §3）。系数**已封板**（2026-10-19 用户拍板，bd `-9hq`
# 零改动收口）：语义 = 后路可靠性基准，不再以「压回有痛感区间」为目标——风险纹理
# 只由 遇敌率 × 战斗难度 × 败场代价 承载，逃跑率不进风险公式（设计权威见
# design_docs/content-design/pve-enemy-design.md §Q4）。
DEFAULT_FLEE_PARAMS: dict[str, object] = {
    "enabled": True,
    "base_rate": 0.95,  # 身法与敌相当
    "slope_up": 0.05,  # 领先侧：每领先 1 倍身法加成
    "slope_down": 0.35,  # 落后侧：敌每快 1 倍身法扣减
    "floor": 0.60,  # 保底（再慢也不破）
    "cap": 1.00,  # 封顶
}
# 逃跑成功的收益系数（§Q4 2026-10-19 重拍：「白跑大半趟」——修为/灵石只留快照
# 基础收益的 ×0.3，且不掉落、不滚传承机缘，代价全在收益侧）。取整口径对标败场
# 修为的 int 截断（managers/pve_combat_manager.py:272）；注意口径差：败场灵石是
# **归零**，逃跑灵石 ×0.3 比败场宽——这是「逃跑严格落在胜负之间」的原意，不是偏差。
FLED_REWARD_RATIO = 0.3

# 每张终态结算单必然产生的三项效果（claim 表按此判断「补发是否已做完」）。
SETTLEMENT_EFFECTS: tuple[str, ...] = (
    EFFECT_BASE_REWARD,
    EFFECT_ROUTE_DROPS,
    EFFECT_LEGACY_TRIGGER,
)
# 战败气血地板：1% 动态 max_hp（PRD R3/§Q4，全局统一口径，非历练私有）
DEFEAT_HP_FLOOR_RATIO = 0.01
# 败场额外休整（design §4：只有 resolved_loss 追加，injury 事件分支已删除）
DEFEAT_FATIGUE_EXTRA_SECONDS = 600
# 结算行 risk_level 列（int）与 PVE 难度档的对应，供内容审计与报表用
RISK_LEVEL_BY_DIFFICULTY = {"low": 1, "mid": 2, "high": 3, "extreme": 4}


def compute_flee_chance(
    agility_self: float,
    agility_enemy: float,
    params: dict | None = None,
) -> float:
    """Return the flee success probability for a 身法 ratio (design §3).

    两段式（领先侧 ``ratio−1``、落后侧 ``1/ratio−1``）而不是单一直线：用户锚点
    「同速 95% / 我快敌一倍 100% / 慢很多保底 60%」三点无法由一条直线同时满足
    ——前两点定出斜率 0.05 后，落后侧要 ``ratio ≤ −6`` 才碰得到地板，``floor``
    会退化成死参数。

    Args:
        agility_self: Player ``FighterState.agility``（身法，非迅捷 speed）.
        agility_enemy: Enemy ``FighterState.agility``.
        params: Configured ``flee`` coefficients; defaults to
            :data:`DEFAULT_FLEE_PARAMS` when a slot is missing.

    Returns:
        Probability in ``[floor, cap]``. 敌人身法 ≤ 0 时直接取 ``cap``：名册里
        低/零身法怪合法存在，除法必须有确定分支；自身身法 ≤ 0 时取 ``floor``
        （负装备/心法加成把身法压到 0 时，下面的 ``1/ratio`` 会除零）。
    """
    cfg = dict(DEFAULT_FLEE_PARAMS)
    cfg.update(params or {})
    cap = float(cfg["cap"])
    floor = float(cfg["floor"])
    if agility_enemy <= 0:
        return cap
    if agility_self <= 0:
        return floor
    ratio = agility_self / agility_enemy
    if ratio >= 1:
        p = float(cfg["base_rate"]) + (ratio - 1) * float(cfg["slope_up"])
    else:
        p = float(cfg["base_rate"]) - (1 / ratio - 1) * float(cfg["slope_down"])
    return max(floor, min(cap, p))


def _seed_stream(rng_seed: int, label: str) -> int:
    """Derive a stable per-purpose sub-seed from the locked settlement seed.

    用 ``hashlib`` 而不是内建 ``hash()``：后者按进程加盐（PYTHONHASHSEED），跨
    重启不稳定，会让 replay 重算出不同的结果，正好违背本任务要的确定性。

    Args:
        rng_seed: Seed persisted in the settlement snapshot at lock time.
        label: Purpose tag (``"combat"`` / ``"flee"``) keeping the two rolls
            independent so the flee decision never shifts the combat stream.

    Returns:
        A 63-bit integer suitable for ``random.seed``.
    """
    digest = hashlib.sha256(f"{rng_seed}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


class AdventureManager:
    """历练系统管理器"""

    # 宗门专属事件组追加进路线抽取池时使用的固定权重
    SECT_EVENT_GROUP_WEIGHT = 15

    CONFIG_FILE = (
        Path(__file__).resolve().parents[1] / "config" / "adventure_config.json"
    )
    # fallback 默认值单源在 data/default_configs.py（externalize-narrative-texts
    # D4 收敛，消除内嵌副本与 config 文件的漂移）
    DEFAULT_CONFIG = ADVENTURE_CONFIG

    def __init__(
        self,
        db: DataBase,
        storage_ring_manager: "StorageRingManager" = None,
        pve_combat_mgr: PVECombatManager = None,
        impart_mgr=None,
        config_manager=None,
        encounter_store=None,
        *,
        busy_state: "BusyState",
        health_service=None,
    ):
        self.db = db
        self.storage_ring_manager = storage_ring_manager
        self.pve_combat_mgr = pve_combat_mgr
        self.busy_state = busy_state
        # 传承管理器：可选注入（main.py 装配后），用于历练触发传承机缘
        self.impart_mgr = impart_mgr
        # 配置管理器：可选注入（当前仅保留接口位；叙事选择走模块级 select_narrative_pool）
        self.config_manager = config_manager
        # 遭遇存储：可选注入共享单例（main.py 装配，与 RiftManager 共用，
        # design D8）；默认自建，保证既有测试/独立使用不炸
        self.encounter_store = (
            encounter_store if encounter_store is not None else EncounterStore()
        )
        # 气血写回必须走 Health Domain（AGENTS §13：core 服务由装配段注入，
        # 由 main.py 传入；standalone 测试可为 None 并退化为直接写）
        self.health_service = health_service
        self.routes: dict[str, dict] = {}
        self.route_alias_index: dict[str, str] = {}
        self.event_groups: dict[str, list[dict]] = {}
        self.drop_tables: dict[str, list[dict]] = {}
        self.default_route_key: str = "scout"
        # 传承机缘触发概率与传承类型（config 顶层 legacy_chance/legacy_type）
        self.legacy_chance: float = 0.0
        self.legacy_type: str = "adventure"
        # 战前逃跑系数（config 的 flee 段；缺失整段回退封板默认，见 §3）
        self.flee_params: dict[str, object] = dict(DEFAULT_FLEE_PARAMS)
        self.reload_config()

    # -------- 结算基座 --------

    @property
    def settlements(self) -> AdventureRepository:
        """Adventure settlement repository bound to the *current* connection.

        必须是每次取用重建的属性，而不是 ``__init__`` 里存一个实例：
        ``DataBase.connect()`` 重连时会替换 ``conn``，存实例会永久持住旧连接并
        在旧句柄上写库。仓储自身不开事务（叶子提交按 ``_txn_depth`` 门控）。
        """
        return AdventureRepository(self.db.conn)

    # -------- 配置加载 --------

    def reload_config(self):
        """重新加载配置文件"""
        config = self._load_config_file()
        self.routes = {route["key"]: route for route in config.get("routes", [])}
        self.default_route_key = next(iter(self.routes.keys()), "scout")
        self.legacy_chance = float(config.get("legacy_chance", 0.0))
        self.legacy_type = config.get("legacy_type", "adventure")

        self.route_alias_index = {}
        for key, route in self.routes.items():
            aliases = set(route.get("aliases", []))
            aliases.add(route["key"])
            aliases.add(route["name"])
            # 兼容旧指令
            if route["key"] == "scout":
                aliases.update({"short", "短途"})
            elif route["key"] == "journey":
                aliases.update({"medium", "中途"})
            elif route["key"] == "peril":
                aliases.update({"long", "长途"})
            for alias in aliases:
                self.route_alias_index[alias.lower()] = key

        self.event_groups = config.get(
            "event_groups", self.DEFAULT_CONFIG["event_groups"]
        )
        self.drop_tables = config.get("drop_tables", self.DEFAULT_CONFIG["drop_tables"])
        self.flee_params = self._parse_flee_params(config)

    @staticmethod
    def _parse_flee_params(config: dict) -> dict:
        """Read the ``flee`` coefficient section, falling back wholesale to defaults.

        任一数值槽缺失/非数值 → **整段**回退封板默认（design §3：不做部分启用，
        半套系数会让概率公式的含义不可预期）；整段缺失额外写一条 warning，但
        **不**按 disabled 处理、不报错给玩家。

        Args:
            config: Loaded adventure config mapping.

        Returns:
            Coefficient dict with all six slots present.
        """
        section = config.get("flee")
        if not isinstance(section, dict):
            logger.warning(
                "adventure_config.json 缺少 flee 段，战前逃跑按封板系数启用"
                "（2026-10-19 拍板，见 pve-enemy-design.md §Q4）"
            )
            return dict(DEFAULT_FLEE_PARAMS)
        params: dict[str, object] = {"enabled": bool(section.get("enabled", True))}
        for slot in ("base_rate", "slope_up", "slope_down", "floor", "cap"):
            value = section.get(slot)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                logger.warning(
                    f"adventure_config.json flee.{slot} 缺失或非数值，整段回退封板系数"
                )
                return dict(DEFAULT_FLEE_PARAMS)
            params[slot] = float(value)
        return params

    def _load_config_file(self) -> dict:
        """加载配置文件并在失败时回退到默认配置"""
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info("已加载 adventure_config.json")
                    return data
            except Exception as exc:
                logger.error(f"加载 adventure_config.json 失败，将使用默认配置: {exc}")
        return self.DEFAULT_CONFIG

    def get_route_overview(self) -> list[dict]:
        """暴露给指令层的路线概览"""
        overview = []
        for route in self.routes.values():
            overview.append(
                {
                    "key": route["key"],
                    "name": route["name"],
                    "risk": route.get("risk", "未知"),
                    "duration": route.get("duration", 0),
                    "min_level": route.get("min_level", 0),
                    "description": route.get("description", ""),
                }
            )
        return overview

    # -------- 核心流程 --------

    async def start_adventure(
        self, user_id: str, route_token: str = ""
    ) -> tuple[bool, str]:
        """Start a route adventure: global 休整 gate, busy claim, opening settlement row.

        v39 起本方法多做两件事（不止「开始历练」）：先按**全局**休整窗口拦人
        （乙案，每人一份，不分成败），再在同一个忙碌写入里落一条 ``adventuring``
        结算单——敌人此刻尚未锁定，只有 run id 与路线入册（PRD R1）。
        """
        # 忙碌守卫（统一走 BusyState；无 user_cd 行视为空闲，无需懒创建）
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        busy_msg = await self.busy_state.assert_idle(
            user_id, template="❌ 你当前正{status}，无法开始历练！"
        )
        if busy_msg:
            return False, busy_msg

        route_key = self._resolve_route(route_token)
        route = self.routes.get(route_key)
        if not route:
            return False, "❌ 未找到对应的历练路线，请先发送 /历练信息 查看可选路线。"

        if player.level_index < route.get("min_level", 0):
            return False, "❌ 你的境界还不足以踏上这条路线，先提升境界吧！"

        cooldown_end = await self._fatigue_until(user_id)
        now = int(time.time())
        if cooldown_end > now:
            remaining = cooldown_end - now
            minutes = remaining // 60 or 1
            return False, f"⚠️ 你刚历练回来，还需休整 {minutes} 分钟。"

        duration = route.get("duration", 3600)
        scheduled_time = now + duration
        # 每次历练一个全局唯一 run id：结算单靠它幂等，崩溃后也能找回未完成的 run
        adventure_run_id = f"adventure:{user_id}:{uuid.uuid4().hex}"
        extra = {"route_key": route_key, "adventure_run_id": adventure_run_id}
        # 状态写统一走 owner：user_cd upsert + 镜像（ADVENTURING → "空闲"）
        ok, race_msg = await self.busy_state.set_busy(
            player, UserStatus.ADVENTURING, scheduled_time, extra_data=extra
        )
        if not ok:
            # 仅预检-写入间并发插入时可达（race loser）
            return False, race_msg

        await self._open_run_row(user_id, adventure_run_id, route_key, now)

        fatigue = route.get("fatigue_cooldown", 0)
        hint = [
            f"✨ 你选择了「{route['name']}」——{route.get('description', '未知冒险')}",
            f"路线风险：{route.get('risk', '未知')} | 历练时长：{duration // 60} 分钟",
        ]
        if route.get("min_level", 0):
            hint.append(f"建议境界：{route['min_level']} 阶以上")
        if fatigue:
            hint.append(f"（完成后你需要休整 {fatigue // 60} 分钟，休整期内不能历练）")

        return True, "\n".join(hint)

    async def _fatigue_until(self, user_id: str) -> int:
        """Return the player's global 休整 deadline (0 when not resting).

        乙案（2026-10-12 拍板）：休整不按路线分别计，读 ``adventure_fatigue``
        这一条全局窗口；进程内 ``_route_cooldowns`` 字典已删除（重启即丢，且
        「按路线休整」从未被授权）。

        Args:
            user_id: 玩家 id。

        Returns:
            休整到期的 unix 秒；无疲劳返回 0。
        """
        row = await self.settlements.get_fatigue(user_id)
        return int((row or {}).get("fatigue_until") or 0)

    async def _open_run_row(
        self, user_id: str, adventure_run_id: str, route_key: str, now: int
    ) -> None:
        """Persist the ``adventuring`` settlement row when a run starts (PRD R1).

        开始时落单，崩溃后凭它找回未完成的历练；插入失败只记日志，不阻断玩家
        开始——``finish_adventure`` 会按 run id 补建，绝不产生第二条事实。

        Args:
            user_id: 玩家 id。
            adventure_run_id: 本次历练的全局唯一 run id（同存 ``user_cd`` extra）。
            route_key: 路线 key。
            now: 当前 unix 秒。
        """
        try:
            async with self.db.transaction():
                await self.settlements.insert_settlement(
                    settlement_id=f"settlement:{adventure_run_id}",
                    adventure_run_id=adventure_run_id,
                    user_id=user_id,
                    now=now,
                    state=STATE_ADVENTURING,
                    route_key=route_key,
                )
        except Exception as exc:
            logger.error(
                f"历练结算单创建失败（完成时补建）run={adventure_run_id}: {exc}"
            )

    async def finish_adventure(self, user_id: str) -> tuple[bool, str, dict | None]:
        """Advance the persisted settlement state machine for 「完成历练」.

        一次调用可能停在两个地方：``pending_choice``（全风险段遇敌的战前抉择，此时
        **不发任何奖励**、保留 ``ADVENTURING`` 忙碌）或终态（``resolved_*``，奖励
        与疲劳在同一边界提交）。重复调用只会重放同一张结算单。

        Args:
            user_id: 玩家 id。

        Returns:
            ``(成功, 消息, reward_data)``；``reward_data`` 仅在进入终态时有值
            （悬赏/师承继续在 ``main.py`` 结算外推进，design §2.3）。
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None

        now = int(time.time())
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd or user_cd.type != UserStatus.ADVENTURING:
            return await self._recover_or_reject(player, now)

        if now < user_cd.scheduled_time:
            remaining = user_cd.scheduled_time - now
            minutes = remaining // 60
            seconds = remaining % 60
            return False, f"❌ 历练尚未完成！还需 {minutes}分{seconds}秒。", None

        extra = self._read_extra(user_cd)
        route = self.routes.get(
            extra.get("route_key", self.default_route_key)
        ) or self.routes.get(self.default_route_key)
        if not route:
            return False, "❌ 未找到历练路线配置，请联系管理员。", None

        try:
            row = await self._ensure_run_row(user_id, user_cd, route, now)
        except Exception as exc:  # noqa: BLE001 - 落库失败必须回中文提示，不外抛
            # 结算单是本次历练唯一的落库事实；写不进去就没有可信的结算，
            # 只能拒绝（继续走下去会发奖无痕、也无法 CAS 防双击）。
            logger.error(f"历练结算单写入失败 user_id={user_id}: {exc}")
            return False, "❌ 历练结算记录写入失败，请稍后再试或联系管理员。", None
        if row["state"] == STATE_ADVENTURING:
            row = await self._lock_encounter(player, row, route, user_cd, now)

        if row["state"] == STATE_PENDING_CHOICE:
            return True, self._render_pending(row, route, player), None
        if row["state"] == STATE_READY_COMBAT:
            return await self._settle_combat(player, row, route, user_cd, now)
        return await self._replay_terminal(player, row, route, user_cd, now)

    async def _recover_or_reject(
        self, player: Player, now: int
    ) -> tuple[bool, str, dict | None]:
        """Answer 「完成历练」 when no 历练忙碌行 is held: backfill effects or refuse.

        正常路径下忙碌行随终态在同一事务里清掉，所以「结算完又点一次」应该听到
        普通的「不在历练中」；重复发奖本来就由 claim 兜住。唯一值得再走一步的
        是 design §2.2 的崩溃点 3——终态已提交、效果 claim 还没写完就断了：那条
        奖励除了这里没有别的入口能补发（``迎战/逃跑`` 只看未终结的单子）。

        Args:
            player: 玩家对象。
            now: 当前 unix 秒。

        Returns:
            ``(成功, 消息, reward_data)``；补发时 ``reward_data`` 恒为 ``None``
            （重放不推进悬赏/师承进度，PRD AC5）。
        """
        row = await self.settlements.get_latest_settlement(player.user_id)
        if (
            row is None
            or row["state"] not in TERMINAL_STATES
            or await self._effects_complete(row["settlement_id"])
        ):
            return False, "❌ 你当前不在历练中！", None

        route = self._route_of(row) or self.routes.get(self.default_route_key)
        if not route:
            return False, "❌ 未找到历练路线配置，请联系管理员。", None
        logger.warning(
            f"历练结算效果待补发 settlement_id={row['settlement_id']} "
            f"state={row['state']}"
        )
        return await self._replay_terminal(player, row, route, None, now)

    async def _effects_complete(self, settlement_id: str) -> bool:
        """Whether every settlement effect already owns a claim row."""
        claimed = {
            c["effect_type"]
            for c in await self.settlements.list_effect_claims(settlement_id)
        }
        return set(SETTLEMENT_EFFECTS) <= claimed

    async def resolve_adventure_choice(
        self, user_id: str, *, flee: bool
    ) -> tuple[bool, str, dict | None]:
        """Consume one pre-combat choice: 「迎战」 or 「逃跑」 (PRD R2).

        只能从 ``pending_choice`` 出发。逃跑成功 → ``resolved_fled``（不进战斗、
        气血零损耗——但按 R6 全时段恢复落定后的实时值记账，见 :meth:`_finalize`；
        收益只留基础收益 ×``FLED_REWARD_RATIO``、不掉落、不滚传承机缘，不产生击败事实
        与败场疲劳——§Q4 2026-10-19 重拍）；逃跑失败或
        迎战 → ``ready_combat`` 后立即用**同一只锁定敌人**结算，不得再次逃跑。

        Args:
            user_id: 玩家 id。
            flee: ``True`` 表示尝试逃跑，``False`` 表示迎战。

        Returns:
            ``(成功, 消息, reward_data)``，形状与 :meth:`finish_adventure` 一致。
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None

        action = "逃跑" if flee else "迎战"
        # 归属闸门：终态行根本不会被 _owned_open_run 返回，所以「已经结算过了」不需要
        # 额外分支——重复点「迎战/逃跑」听到的就是下面这句「当前没有待抉择的历练
        # 遭遇」，且拿不到任何奖励；GM 清冷却留下的孤儿单同样走这句。
        owned = await self._owned_open_run(user_id)
        if not owned:
            return False, f"❌ 当前没有待抉择的历练遭遇，无法{action}。", None
        row, user_cd = owned
        state = row["state"]
        if state == STATE_ADVENTURING:
            return False, "❌ 你的历练还没有完成，先等历练结束吧。", None
        if state == STATE_READY_COMBAT:
            # 崩溃恢复：状态已推进但没打完，视同迎战续算（同一 snapshot，不重掷）
            route = self._route_of(row)
            if not route:
                return False, "❌ 未找到历练路线配置，请联系管理员。", None
            return await self._settle_combat(
                player, row, route, user_cd, int(time.time())
            )

        route = self._route_of(row)
        if not route:
            return False, "❌ 未找到历练路线配置，请联系管理员。", None
        snapshot = self._read_snapshot(row)

        if flee and self._flee_succeeded(snapshot):
            return await self._finalize(
                player,
                row,
                route,
                user_cd,
                snapshot,
                event=snapshot.get("event") or {},
                state=STATE_RESOLVED_FLED,
                fled=True,
                defeated=False,
                combat_msg=(
                    "💨 你趁乱抽身，遁走了——这一趟白跑大半："
                    "收益只留三成，无掉落、无传承机缘。"
                ),
                rewards=self._fled_rewards(snapshot),
                # 脱身不进战斗，零气血损失；hp_after 终值由 _finalize 按结算
                # 时刻落定后写入（pending 期间恢复照走），这里只给兜底值。
                hp_final=int(player.current_hp or row["hp_before"]),
                now=int(time.time()),
            )

        # 迎战 / 逃跑失败：先把 pending 推进到 ready_combat（同 CAS 防双击），
        # 推进失败方直接续跑赢家的状态——绝不重掷敌人。
        advanced = await self._advance_state(
            row, STATE_PENDING_CHOICE, STATE_READY_COMBAT
        )
        return await self._settle_combat(
            player, advanced, route, user_cd, int(time.time())
        )

    # ---------------- 状态机内部：推进 / 锁定 / 结算 ----------------

    async def _ensure_run_row(
        self, user_id: str, user_cd, route: dict, now: int
    ) -> dict:
        """Return the settlement row for this run, creating it when absent.

        开始时（:meth:`start_adventure`）已经落过 ``adventuring`` 行；这里的补建
        只为覆盖两类真实缺口：改动前就挂在 ``user_cd`` 里的旧忙碌行（没有
        run id），以及开始时插入失败的降级路径。

        mint 出的 run id 是**确定性**的（由 ``user_cd.create_time`` 派生），并且
        **必须与落单在同一笔事务里写回** ``user_cd.extra_data``（经
        ``BusyState.stamp_extra``，且只有**真正插入成功**那一路才写回——见该方法
        的调用方契约）：归属校验
        （:meth:`awaits_combat_choice` / :meth:`resolve_adventure_choice`）比对
        的就是 extra 里的 run id 与单据的 run id，不落回则永远对不上——升级那一刻
        就在途的历练会被永久锁死（「迎战/逃跑」全被拒、忙碌解不开、AC11 的出路
        提示变成谎话），且每点一次「完成历练」都会再补建一张新单并重掷敌人；用
        uuid 而非确定性 id，则并发双击会各 mint 一张、各发一份掉落与传承。

        Args:
            user_id: 玩家 id。
            user_cd: 本次历练的忙碌行（extra 里可能还没有 run id）。
            route: 本次历练路线配置。
            now: 当前 unix 秒。

        Returns:
            结算行 dict。落库失败直接抛异常，由调用方 :meth:`finish_adventure`
            转成中文提示——不存在「返回 None 走无记录旧行为」这条路，child C
            起每次历练都必须有结算单。
        """
        extra = self._read_extra(user_cd)
        run_id = extra.get("adventure_run_id") or ""
        minted = False
        if run_id:
            row = await self.settlements.get_settlement_by_run(run_id)
            if row:
                return row
        else:
            # 确定性 run id（不用 uuid）：升级窗口里这种旧忙碌行可能被连点，或
            # GM 与玩家同刻动手，各自并发补建。uuid 会各 mint 一张单、各发一份
            # 掉落与传承；确定性 id 靠 adventure_run_id 的 UNIQUE + 冲突回读收敛
            # 成**一条事实**（落败方拿到既有行后按重放走，claim 已守护进度不推)。
            # create_time 由 set_user_busy 写 int(time.time())，同一次历练唯一。
            run_id = f"adventure:{user_id}:legacy:{int(user_cd.create_time or 0)}"
            minted = True
        async with self.db.transaction():
            row, created = await self.settlements.insert_settlement(
                settlement_id=f"settlement:{run_id}",
                adventure_run_id=run_id,
                user_id=user_id,
                now=now,
                route_key=route["key"],
                state=STATE_ADVENTURING,
            )
            # 只有**真正插入成功**那一路才落回 extra。闸门是第一道防线：落败方若也
            # stamp 一次，会把本场单据的 run id 挂到别人后来开的忙碌行上（身份串线）。
            # 历史上它还兼防更重的一类故障：早期 `stamp_extra` 按调用方快照**整行
            # 回写**（含 `type`），落败方晚写一步会排在赢家 `_finalize` 的 clear 之后，
            # 把已结束的忙碌复活成「历练中」——而落败方随后只走 `_replay_terminal`，
            # 修复前该分支不收尾忙碌，玩家就永久卡死、只能靠 GM「清除CD」弃单（第六轮
            # 已把「终态 ⇒ 不持有该场忙碌」补成重放的兜底收尾，见 design §2.4-8）。
            # 2026-10-15 起 `stamp_extra` 收窄为只写 `extra_data`，那条复活路径不复
            # 存在；闸门因 run id 串线仍然保留。赢家这笔 stamp 与
            # insert 同事务，任何 clear 都只能在该行存在之后发生（跨事务串行），所以
            # stamp 永远排在 clear 之前。
            if minted and created:
                await self.busy_state.stamp_extra(
                    user_cd,
                    {"route_key": route["key"], "adventure_run_id": run_id},
                )
        return row

    async def _lock_encounter(
        self, player: Player, row: dict, route: dict, user_cd, now: int
    ) -> dict:
        """Lock enemy, RNG, event and base rewards at 完成时刻, then advance the state.

        锁定时点唯一（PRD R1）：敌人、事件、基础收益、rng_seed 全部在这一刻写进
        不可变 ``snapshot``；此后迎战/逃跑/重放只读这份快照，绝不重掷。

        Args:
            player: 玩家对象。
            row: ``adventuring`` 结算行。
            route: 路线配置。
            user_cd: 历练忙碌行（用于算有效时长）。
            now: 当前 unix 秒。

        Returns:
            推进后的结算行（``pending_choice`` / ``ready_combat``；CAS 冲突时返回
            赢家写入的行）。
        """
        adventure_duration = now - user_cd.create_time
        scheduled_duration = max(1, user_cd.scheduled_time - user_cd.create_time)
        effective_duration = min(adventure_duration, scheduled_duration)
        faction_id = await self._get_player_faction_id(player)
        event = self._trigger_route_event(route, faction_id)
        base_rewards = self._calculate_rewards(player, route, effective_duration, event)

        risk_map = {"低": "low", "中": "mid", "高": "high", "极高": "extreme"}
        difficulty = risk_map.get(route.get("risk", "低"), "low")
        prepared = None
        if self.pve_combat_mgr is not None:
            prepared = self.pve_combat_mgr.prepare_encounter(
                player, "adventure", difficulty
            )

        snapshot: dict = {
            "locked_at": now,
            "route_key": route["key"],
            "difficulty": difficulty,
            "effective_duration": effective_duration,
            "event": event,
            "base_reward": base_rewards,
            # 一次性消耗的全局随机流里取一个种子存进单据：战斗与逃跑各自的 roll
            # 由它派生（_seed_stream），重放时不需要全局流处于同一位置。
            "rng_seed": random.getrandbits(63),
            "hp_before": int(player.current_hp or 0),
        }
        if prepared is not None:
            enemy = prepared.enemy
            snapshot["category"] = prepared.category
            snapshot["enemy"] = {
                "name": enemy.name,
                "level_index": enemy.level_index,
                "profile_id": getattr(enemy, "profile_id", "") or "",
                "profile_version": getattr(enemy, "profile_version", 0) or 0,
            }
            # Enemy 是扁平 dataclass（字段全是数字/字符串/list[dict]），asdict 可
            # 直接 JSON 往返；重放时据此重建同一只怪。玩家侧只留审计与逃跑公式要
            # 用的稳定输入（AC3：概率只消费快照中的身法，不读实时对象）。
            player_fighter = (
                await self.pve_combat_mgr.combat_engine.build_fighter_from_player(
                    player
                )
            )
            snapshot["combat"] = {
                "player": {
                    "name": player_fighter.name,
                    "hp": int(player_fighter.hp),
                    "max_hp": int(player_fighter.max_hp),
                    "agility": int(player_fighter.agility),
                },
                "enemy": self.pve_combat_mgr.enemy_to_record(enemy),
            }
            snapshot["hp_before"] = int(player_fighter.hp)
        enemy_info = snapshot.get("enemy") or {}
        return await self._advance_state(
            row,
            STATE_ADVENTURING,
            STATE_PENDING_CHOICE
            if self._offers_choice(snapshot)
            else STATE_READY_COMBAT,
            snapshot=snapshot,
            encounter_id=self._legacy_encounter_id(enemy_info, snapshot),
            profile_id=str(enemy_info.get("profile_id") or ""),
            profile_version=int(enemy_info.get("profile_version") or 0),
            risk_level=RISK_LEVEL_BY_DIFFICULTY.get(snapshot["difficulty"], 1),
            hp_before=int(snapshot["hp_before"]),
        )

    async def _advance_state(
        self, row: dict, from_state: str, to_state: str, **values: Any
    ) -> dict:
        """CAS one state edge and return the row as it now stands.

        并发双击只有赢家写得进去：``cas_update_settlement`` 同时校验
        ``state=<前态>`` 与 ``cas_version``，输家在这里读回赢家提交的行，随后照
        那份 snapshot 继续走，绝不重掷敌人（design §2.2）。

        Args:
            row: 当前结算行。
            from_state: 期望前态。
            to_state: 目标态。
            values: 附加列（``snapshot`` 允许传 dict，自动序列化）。

        Returns:
            最新结算行；行读不到时退回原行（调用方按无进展处理）。
        """
        payload = dict(values)
        if "snapshot" in payload:
            payload["snapshot"] = snapshot_text(payload["snapshot"])
        # CAS 与读回必须在同一笔事务里：叶子裸写的提交门控会被并发结算抢到的
        # 事务归属跳过（隐式事务悬空 → 对手方 BEGIN IMMEDIATE 直接失败），
        # 见 :meth:`_grant_effects` 里的同一处说明。
        async with self.db.transaction():
            moved = await self.settlements.cas_update_settlement(
                row["settlement_id"],
                expected_cas_version=int(row["cas_version"]),
                expected_state=from_state,
                state=to_state,
                **payload,
            )
            latest = await self.settlements.get_settlement(row["settlement_id"])
        if not moved:
            logger.info(
                f"历练结算 {row['settlement_id']} {from_state}->{to_state} 未命中，"
                "改用已提交状态"
            )
        return latest or row

    async def _settle_combat(
        self, player: Player, row: dict, route: dict, user_cd, now: int
    ) -> tuple[bool, str, dict | None]:
        """Run the locked encounter deterministically and commit its terminal state.

        计算（战斗引擎 + 奖励）全在事务外，事务里只写状态、气血、休整与清忙
        （design §2.2：不用长事务包住随机数与外部 IO）。

        Args:
            player: 玩家对象。
            row: 处于 ``ready_combat`` 的结算行。
            route: 路线配置。
            user_cd: 历练忙碌行。
            now: 当前 unix 秒。

        Returns:
            ``(成功, 消息, reward_data)``。
        """
        snapshot = self._read_snapshot(row)
        computed = await self._compute_locked(player, snapshot)

        return await self._finalize(
            player,
            row,
            route,
            user_cd,
            snapshot,
            event=computed["event"],
            state=computed["state"],
            fled=False,
            defeated=computed["defeated"],
            combat_msg=computed["combat_msg"],
            rewards=computed["rewards"],
            hp_final=computed["hp_final"],
            now=now,
        )

    async def _compute_locked(self, player: Player, snapshot: dict) -> dict:
        """Derive the fight outcome from the locked snapshot without writing anything.

        确定性只来自锁定输入：敌人从 snapshot 重建、战斗流由 ``rng_seed`` 派生，
        所以结算与崩溃后的重放算出的是同一份结果（design §2.2「事务外确定性计
        算」）。逃跑脱身与未触发战斗都不打，直接落 ``resolved_win``/基础收益。

        Args:
            player: 玩家对象（只读；构建 fighter 会顺带惰性落定恢复锚点）。
            snapshot: 锁定快照。

        Returns:
            ``{event, state, rewards, defeated, hp_final, combat_msg}``。
        """
        event = snapshot.get("event") or {}
        base_rewards = dict(snapshot.get("base_reward") or {"exp": 0, "gold": 0})
        enemy_record = (snapshot.get("combat") or {}).get("enemy")
        result = {
            "event": event,
            "state": STATE_RESOLVED_WIN,
            "rewards": base_rewards,
            "defeated": False,
            "hp_final": int(player.current_hp or 0),
            "combat_msg": "",
        }
        if not enemy_record or self.pve_combat_mgr is None:
            # 未触发战斗＝无遭遇地顺利完成：不扣血、不产生击败事实（PRD R4）
            return result

        outcome = await self.pve_combat_mgr.fight_prepared(
            player,
            self.pve_combat_mgr.enemy_from_record(enemy_record),
            base_rewards,
            # 战斗流由锁定种子派生：同一 snapshot 重放出同一份战报
            rng_seed=_seed_stream(int(snapshot.get("rng_seed") or 0), "combat"),
        )
        rewards = dict(outcome.rewards)
        result["rewards"] = rewards
        result["defeated"] = outcome.enemy_defeated
        result["combat_msg"] = outcome.message
        result["hp_final"] = outcome.player_final_hp
        if rewards.get("hp_penalty"):
            # 战败：负场事实 + 1% 动态上限地板（§Q4，全局统一口径）
            result["state"] = STATE_RESOLVED_LOSS
            result["hp_final"] = max(
                outcome.player_final_hp, self._defeat_hp_floor(player)
            )
        return result

    def _defeat_hp_floor(self, player: Player) -> int:
        """1% of the dynamic 气血上限, rounded up (PRD R3 / pve-enemy §Q4).

        战败不会把玩家打到残血 1 点：地板按动态上限算（含装备加成）。
        standalone 测试装配没有 Health Domain 时退回 ``base_hp``。

        Args:
            player: 玩家对象。

        Returns:
            气血地板（至少 1）。
        """
        if self.health_service is not None:
            max_hp = self.health_service.compute_max_hp(player)
        else:
            max_hp = int(getattr(player, "base_hp", 1) or 1)
        return max(1, math.ceil(max_hp * DEFEAT_HP_FLOOR_RATIO))

    async def _finalize(
        self,
        player: Player,
        row: dict,
        route: dict,
        user_cd,
        snapshot: dict,
        *,
        event: dict,
        state: str,
        fled: bool,
        defeated: bool,
        combat_msg: str,
        rewards: dict,
        hp_final: int,
        now: int,
    ) -> tuple[bool, str, dict | None]:
        """Commit the terminal fact, then run claim-guarded effects.

        一个短事务里原子写：终态 + 派生 ``outcome`` + 气血 + 休整 + 清忙（PRD
        R1/R4 要求终态与忙碌清除同边界）。提交后逐项 ``claim_effect``：每个效果
        只可能执行一次；claim 成功而执行失败**不回滚**终态，改为玩家可见提示 +
        error 日志（design §2.3）。

        Args:
            player: 玩家对象。
            row: 非终态结算行。
            route: 路线配置。
            user_cd: 历练忙碌行（重放时可能为 ``None``）。
            snapshot: 锁定快照。
            event: 快照里的事件。
            state: 终态（``resolved_*``）。
            fled: 是否逃跑成功。
            defeated: 是否击败敌人。
            combat_msg: 战报片段（可为空）。
            rewards: 本次结算的修为/灵石（已含战斗修正）。
            hp_final: 气血终值（已套地板）。逃跑成功时**本方法会覆写它**：
                事务内先 ``health_service.settle()`` 落定 pending 期间的全时段
                恢复，再按结算时刻的真实气血记账（PRD R2「气血不变」指零战斗
                损耗，不是回退到锁定值）。
            now: 当前 unix 秒。

        Returns:
            ``(成功, 消息, reward_data)``。
        """
        # 前态守护：**已是终态的行一律不得二次写入**。并发败者（`_advance_state`
        # 的 CAS 输家）拿到的是赢家已提交的行，若赢家已打完并落终态，败者会带着
        # 这张终态行走到这里；`expected_state=row["state"]` 那时是同态覆盖，双条件
        # CAS 拦不住——实测 6/6 命中：cas_version 多跳一级（3 步而非 2 步）、
        # settled_at/hp_after/outcome 被二次覆写、两个调用方都收到「全新结算」文案。
        # 终态即既成事实，这里与 `if not moved` 分支同语义，直接走重放。
        if row["state"] in TERMINAL_STATES:
            return await self._replay_terminal(player, row, route, user_cd, now)

        settlements = self.settlements
        hp_before = int(snapshot.get("hp_before") or player.current_hp or 0)
        fatigue_seconds = self._fatigue_seconds(route, state)

        async with self.db.transaction():
            if fled:
                # 逃跑不进战斗、一滴血不掉（PRD R2），但「气血不变」不等于「气血
                # 等于锁定值」：R6 起恢复全时段按真实时间走，挂 pending 那几分钟
                # 照样在回血。所以先落定恢复，事实列的 hp_after 记**结算时刻的
                # 真实气血**，child E/报表读它才不会拿到锁定时的过期数字。
                #
                # 战斗路径**不需要**这一步：`build_fighter_from_player` 内部走
                # `get_health_snapshot`（同样会 settle），所以引擎本来就是拿回血后的
                # 值参战，终值是真实的战后剩余；胜场可以远低于战前（打到残血也是赢），
                # 不能再对终值取 max 去「保底」（那会与 AC4「胜场按引擎实际剩余写回」
                # 冲突，tests 的 win/final_hp=7 用例正是钉这条）。
                if self.health_service is not None:
                    hp_final = await self.health_service.settle(player.user_id, now)
                else:
                    hp_final = int(player.current_hp or hp_final)
                player.current_hp = hp_final  # 与已落库的值同步，供渲染取用
            moved = await settlements.cas_update_settlement(
                row["settlement_id"],
                expected_cas_version=int(row["cas_version"]),
                expected_state=row["state"],
                state=state,
                outcome=settlement_outcome(state),
                hp_before=hp_before,
                hp_after=int(hp_final),
                fled=1 if fled else 0,
                defeated=1 if defeated else 0,
                settled_at=now,
            )
            if not moved:
                # 并发输家：赢家已提交终态，本次不重复写，只读回既成事实
                latest = await settlements.get_settlement(row["settlement_id"])
                return await self._replay_terminal(
                    player, latest or row, route, user_cd, now
                )
            if not fled:
                await self._write_hp(player, hp_final)
            # 逃跑分支的气血已在 CAS 前落定（settle 同时写库与推进锚点），
            # 这里不再重复写。
            if fatigue_seconds > 0:
                await self._write_fatigue(
                    player.user_id, route, row["settlement_id"], fatigue_seconds, now
                )
            await self.busy_state.clear(player)

        notes, dropped_items = await self._grant_effects(
            player, row, route, event, rewards, snapshot, now, state
        )
        reward_data = {
            "route_key": route["key"],
            "route_name": route.get("name", route["key"]),
            "event_key": event.get("key", ""),
            "event_desc": self._select_event_desc(event, player),
            "exp_reward": int(rewards.get("exp", 0)),
            "gold_reward": int(rewards.get("gold", 0)),
            "items": dropped_items,
            "duration": int(snapshot.get("effective_duration") or 0),
            "bounty_tag": route.get("bounty_tag", "adventure"),
            "bounty_progress": max(
                1, route.get("bounty_progress", 1) + event.get("bonus_progress", 0)
            ),
            "pve_won": defeated,
        }
        msg = self._render_result(
            route,
            event,
            player,
            rewards,
            combat_msg,
            state,
            fatigue_seconds,
            notes,
            duration=int(snapshot.get("effective_duration") or 0),
        )
        return True, msg, reward_data

    async def _write_hp(self, player: Player, hp_final: int) -> None:
        """Write the post-fight 气血 through the Health Domain."""
        if self.health_service is not None:
            await self.health_service.set_current_hp(player, int(hp_final))
        else:
            # standalone 测试装配没有 core 服务：退化为直接写（生产不走这里）
            player.current_hp = int(hp_final)
            await self.db.update_player(player)

    def _fatigue_seconds(self, route: dict, state: str) -> int:
        """Total 休整 seconds = route base + the loss-only extra (PRD R4 / design §4).

        Args:
            route: 路线配置（``fatigue_cooldown`` 秒）。
            state: 终态；只有 ``resolved_loss`` 追加战败休整，``resolved_fled``
                没打就没有败场事实，不加。

        Returns:
            总休整秒数。
        """
        seconds = int(route.get("fatigue_cooldown", 0) or 0)
        if state == STATE_RESOLVED_LOSS:
            seconds += DEFEAT_FATIGUE_EXTRA_SECONDS
        return seconds

    async def _write_fatigue(
        self, user_id: str, route: dict, settlement_id: str, seconds: int, now: int
    ) -> None:
        """Extend the global 休整 window to ``max(existing, now + seconds)``.

        乙案（2026-10-12 拍板）：休整是全局窗口，不按路线分别计；仓储
        ``set_fatigue`` 是纯 upsert（没有 max 语义），所以取大在这里做，并且必须
        在调用方事务内读——写锁已持有，不会被别的结算夹进来。

        Args:
            user_id: 玩家 id。
            route: 路线配置（``route_id`` 只作归属审计）。
            settlement_id: 触发休整的结算单。
            seconds: 本次休整秒数。
            now: 当前 unix 秒。
        """
        existing = await self.settlements.get_fatigue(user_id)
        current_until = int((existing or {}).get("fatigue_until") or 0)
        await self.settlements.set_fatigue(
            user_id=user_id,
            route_id=route["key"],
            fatigue_until=max(current_until, now + seconds),
            settlement_id=settlement_id,
        )

    async def _owned_open_run(self, user_id: str) -> tuple[dict, object] | None:
        """Return ``(settlement row, user_cd)`` for the player's CURRENT run.

        归属判定（AGENTS.md §2：忙碌一律以 ``user_cd`` 为权威）：未终结的结算单
        必须同时满足「玩家现在正历练中」且「忙碌 extra 里的 run id 与单据一致」。
        少一道校验都会出实事：GM「清除CD / 清除全部冷却」只复位忙碌、**不终结**
        结算单，孤儿 ``pending_choice`` 会留在账上，玩家之后的任一次忙碌都可能被
        这张不相干的旧单消费——真打一场、按旧单发奖，并被结算边界的
        ``busy_state.clear`` 抹掉当前忙碌。

        Args:
            user_id: 玩家 id。

        Returns:
            命中则 ``(row, user_cd)``；无单、不在历练中、或单据不属于本次历练时
            返回 ``None``。
        """
        row = await self.settlements.get_open_settlement(user_id)
        if not row:
            return None
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd or user_cd.type != UserStatus.ADVENTURING:
            return None
        if self._read_extra(user_cd).get("adventure_run_id") != row["adventure_run_id"]:
            return None
        return row, user_cd

    async def awaits_combat_choice(self, user_id: str) -> bool:
        """Whether the player's current run awaits a pre-combat decision.

        覆盖 ``pending_choice``（等玩家选）与 ``ready_combat``（已选定、战斗尚未
        落账的崩溃恢复态）：这两种单子都不能被 GM「触发历练结算」跳过，必须真打
        一场。结算单是权威，不看内存字典也不读 ``player.state`` 镜像。判定与
        :meth:`resolve_adventure_choice` 共用 :meth:`_owned_open_run`，否则 GM 会
        在一句话里先说「正等待战前抉择」、随后代打时又说「没有待抉择的遭遇」。

        Args:
            user_id: 玩家 id。

        Returns:
            本次历练是否挂着一张需要应战的结算单。
        """
        owned = await self._owned_open_run(user_id)
        if not owned:
            return False
        return str(owned[0]["state"]) in (STATE_PENDING_CHOICE, STATE_READY_COMBAT)

    async def clear_fatigue(self, user_id: str) -> bool:
        """Clear a player's 休整 window (GM 清冷却 / 强制结算入口).

        GM 层不直接持有仓储（装配边界在 manager），所以走这个 API；CAS 版本
        条件沿用疲劳行读到的 ``cas_version``，与清忙同款语义。

        Args:
            user_id: 玩家 id。

        Returns:
            是否真的清掉了一条**生效中**的休整；已过期的行返回 ``False``，
            免得 GM 收到「历练休整冷却：1 条」这种凭空多出来的战果。
        """
        existing = await self.settlements.get_fatigue(user_id)
        if not existing or int(existing["fatigue_until"] or 0) <= int(time.time()):
            return False
        return await self.settlements.cas_clear_fatigue(
            user_id, expected_cas_version=int(existing["cas_version"])
        )

    async def _grant_effects(
        self,
        player: Player,
        row: dict,
        route: dict,
        event: dict,
        rewards: dict,
        snapshot: dict,
        now: int,
        state: str,
    ) -> tuple[list[str], list]:
        """Execute the three settlement effects, each behind an inline claim.

        三项效果各自 ``claim_effect`` 后才执行本体：同一张结算单永远只发放一次
        （重放、并发、崩溃后的补发都靠这张 claim 表，design §2.2/§2.3）。本体写
        入收在**第二笔短事务**里，理由见实现内注释。

        Args:
            player: 玩家对象。
            row: 终态结算行。
            route: 路线配置。
            event: 快照事件（掉落按事件加权）。
            rewards: 修为/灵石数额。
            snapshot: 锁定快照。
            now: 当前 unix 秒。
            state: 本次终态。**必须由调用方显式传入**：``row`` 是终态**之前**的行
                （``_finalize`` 传的是待提交的 CAS 前态行），读 ``row["state"]``
                只会拿到 ``ready_combat``/``pending_choice``——fled 的掉落门控因此
                失效（逃跑照样掉落），胜场的传承 roll 也被误杀；fled/loss 的传承门控
                恰好仍会跳过（前态≠resolved_win），别被这点掩盖真问题。

        Returns:
            ``(需要拼进结算消息的片段, 本次掉落清单)``；掉落清单供 ``reward_data``
            的悬赏/师承进度消费。
        """
        notes: list[str] = []
        dropped_items: list = []
        settlement_id = row["settlement_id"]
        settlements = self.settlements
        # 第二笔短事务：终态事务已提交，这里把「claim + 效果本体」原子写进去。
        # 为什么不能留成一条条评论式的裸写（叶子提交）：并发双击时，另一路
        # 结算可能在这两次调用之间抢到事务归属，令本路的 ``_txn_depth`` 门控
        # 读到非 0 而**跳过 commit**——sqlite 隐式事务就悬在那儿，下一笔
        # ``BEGIN IMMEDIATE`` 直接报 "cannot start a transaction within a
        # transaction"（tests/test_adventure_settlement_state_machine.py 的
        # 并发用例真实复现过）。写全部收进 CM 后，两路只会在事务上排队。
        # 效果本体抛出的异常仍被逐项吞掉（design §2.3：失败可见、不回滚终态），
        # 所以这里的 commit 不会被失败效果回滚掉。
        async with self.db.transaction():
            # 写锁内重读（bd -546）：入口对象是 finish_adventure 开头读的，早于战斗
            # 与终态事务；直接整行回写会把并发窗口里别人写入的列覆盖回去。三个效果
            # 必须共用这份最新行——`_grant_route_drops` 的储物戒入库写的也是它。
            fresh = await self.db.get_player_by_id(player.user_id) or player
            # 终态由两个效果本体自己门控（fled/败场不掉落、非胜场不滚传承）：claim 照记
            # 三件套、本体按终态跳过，沿用 hp_penalty 的既有先例（见 _grant_route_drops
            # docstring）——改成状态相关效果集会动 claim 表语义与重放路径，不值。
            effects = (
                (EFFECT_BASE_REWARD, lambda: self._grant_base_reward(fresh, rewards)),
                (
                    EFFECT_ROUTE_DROPS,
                    lambda: self._grant_route_drops(
                        fresh, route, event, rewards, state
                    ),
                ),
                (
                    EFFECT_LEGACY_TRIGGER,
                    lambda: self._grant_legacy_trigger(fresh, snapshot, state),
                ),
            )
            for effect_type, runner in effects:
                claimed = await settlements.claim_effect(
                    consumer_name=CONSUMER_ADVENTURE_SETTLEMENT,
                    settlement_id=settlement_id,
                    effect_type=effect_type,
                    now=now,
                )
                if not claimed:
                    continue  # 已发放过（重放/并发）：claim 挡住重复执行
                try:
                    note = await runner()
                except Exception as exc:
                    logger.error(
                        f"历练结算效果执行失败 settlement_id={settlement_id} "
                        f"effect={effect_type}: {exc}"
                    )
                    notes.append(
                        f"\n⚠️ 部分奖励发放失败，请联系管理员（结算单 {settlement_id}）"
                    )
                    continue
                if isinstance(note, tuple):
                    dropped_items = list(note[1] or [])
                    note = note[0] or ""
                if note:
                    notes.append(note)
            # 效果改动同步回调用方对象（只对齐内存，不额外写库）：随后
            # `_finalize`/`_replay_terminal` 还要用同一对象渲染与**整行写回**。
            # 不变式：本清单必须覆盖所有效果可能改动的 Player 列——漏一列，后续那次
            # 整行回写就会用入口快照把它刷掉（storage_ring_items 漏过一次：重放补发的
            # 掉落消息说发了、库里被抹掉）。新增效果动到别的列时必须同步加进来。
            player.gold = fresh.gold
            player.experience = fresh.experience
            player.storage_ring = fresh.storage_ring
            player.storage_ring_items = fresh.storage_ring_items
        return notes, dropped_items

    async def _grant_base_reward(self, player: Player, rewards: dict) -> str:
        """Credit 修为/灵石 (claim-guarded effect body).

        ``bonus_exp``（战胜利害的额外修为）与 ``exp`` 同笔入账，沿用现网口径。
        """
        player.experience = (
            int(player.experience or 0)
            + int(rewards.get("exp", 0))
            + int(rewards.get("bonus_exp", 0))
        )
        player.gold = int(player.gold or 0) + int(rewards.get("gold", 0))
        await self.db.update_player(player)
        return ""

    async def _grant_route_drops(
        self, player: Player, route: dict, event: dict, rewards: dict, state: str
    ) -> tuple[str, list]:
        """Roll route drops (claim-guarded effect body).

        掉落内容不追求重放一致：claim 保证的是**恰好一次**，不是同内容重发，
        所以沿用全局随机流，与现网口径相同。战败（``hp_penalty``）与逃跑
        （``resolved_fled``）都什么都不掉——§Q4 2026-10-19：逃跑代价全在收益侧，
        掉落也归零。但这次机会同样被 claim 消耗掉，重放不会补发。

        Args:
            player: 玩家对象。
            route: 路线配置（掉落表来源）。
            event: 快照事件（``item_chance`` 加权）。
            rewards: 结算收益；``hp_penalty`` 为真表示战败。
            state: 终态；``resolved_fled`` 不掉落。

        Returns:
            ``(掉落文案, 掉落清单)``。
        """
        if rewards.get("hp_penalty") or state == STATE_RESOLVED_FLED:
            return "", []
        items, item_msg = await self._handle_drops(player, route, event)
        return item_msg or "", items

    async def _grant_legacy_trigger(
        self, player: Player, snapshot: dict, state: str
    ) -> str:
        """Roll the 上古传承 chance from the locked seed (effect body).

        传承机缘 = 「走完全程的人」的专属彩头：只有 ``resolved_win``（含未遇敌完成）
        才 roll，``resolved_loss`` / ``resolved_fled`` 一律跳过（2026-10-20 拍板）。
        连 roll 都不做，省一次子流派生。

        传承机会每单只可能兑现一次，判定用 ``rng_seed`` 派生的固定子流，重放不会
        重新博概率。

        Args:
            player: 玩家对象。
            snapshot: 锁定快照。
            state: 终态；非 ``resolved_win`` 直接跳过。

        Returns:
            传承触发文案；未触发或跳过时为空串。
        """
        if state != STATE_RESOLVED_WIN:
            return ""
        roll = random.Random(_seed_stream(int(snapshot.get("rng_seed") or 0), "legacy"))
        return await self._maybe_trigger_legacy(player, roll_value=roll.random())

    async def _replay_terminal(
        self,
        player: Player,
        row: dict,
        route: dict,
        user_cd,
        now: int,
    ) -> tuple[bool, str, dict | None]:
        """Render an already committed settlement instead of repeating it.

        崩溃/重连后的找回路径：终态行是既成事实，这里只补发「已提交但未 claim」
        的效果（claim 保证不重复），并按快照数字重述结果。战斗会用同一份
        ``rng_seed`` 确定性重演一次**只为你看到同样的数字**——**战斗气血**不再写回
        （``_finalize`` 的 CAS 是战斗结果的唯一写入口），所以不存在二次扣血；而
        收尾那一笔经 :meth:`BusyState.clear` 把截止到此刻的**分钟级时间恢复**落定
        并同步进内存，随清忙一并落库——这是 2026-10-12 取消「恢复忙碌闸门」之后的
        预期口径，不是二次结算。忙碌本身则**必须收尾**：能走到这里说明玩家仍持着
        这张**已结束**历练的忙碌（只可能是别处拿陈旧整行快照把它复活了），见返回
        前的注释与归属判定。

        Args:
            player: 玩家对象。
            row: 终态结算行。
            route: 路线配置。
            user_cd: 忙碌行（重放时可能已清）。
            now: 当前 unix 秒。

        Returns:
            ``(成功, 消息, reward_data)``；重放不返回 ``reward_data``，避免悬赏/
            师承进度被重复推进（design §2.3）。副作用：把被复活的历练忙碌清回空闲
            （不变式「终态 ⇒ 不持有该场忙碌」）。
        """
        snapshot = self._read_snapshot(row)
        state = row["state"]
        event = snapshot.get("event") or {}
        # 重放读的是**已提交的权威事实列**：调用方的 `player` 是进函数前读的，并发败者
        # 手里那份早于赢家 `_write_hp`。不只用它渲染会显示陈旧气血（实测并发迎战 10 次
        # 命中 1 次：消息显示 1,000 而库/账本是 500）——更要紧的是本方法末尾会
        # `busy_state.clear` + `db.update_player`（Player 全列回写），这份陈旧值会**真的
        # 落库**（对照探针：陈旧 10499 被写进 players.current_hp，账本真值 500）。
        # 先对齐终态行的 hp_after，随后 clear 内的 settle 再从库里推进，结果恒等于账本。
        # 真值判断而非 `is not None`：`hp_after` 列是 NOT NULL DEFAULT 0，用真值顺带跳过
        # 0（终态行 hp_after=0 经代码路径分析不可达，这里只是零成本的顺带保险）。
        if row.get("hp_after"):
            player.current_hp = int(row["hp_after"])
        combat_msg = ""
        if state == STATE_RESOLVED_FLED:
            # 逃跑没打：收益 = 锁定的基础收益 × FLED_REWARD_RATIO（与结算路径同源）
            rewards = self._fled_rewards(snapshot)
        else:
            computed = await self._compute_locked(player, snapshot)
            rewards = computed["rewards"]
            combat_msg = computed["combat_msg"]
        notes, _items = await self._grant_effects(
            player, row, route, event, rewards, snapshot, now, state
        )
        msg = self._render_result(
            route,
            event,
            player,
            rewards,
            combat_msg,
            state,
            self._fatigue_seconds(route, state),
            notes,
            duration=int(snapshot.get("effective_duration") or 0),
            replayed=True,
        )
        # 终态即收尾（不变式：**单据终态 ⇒ 不持有该场历练的忙碌**）。正常流程到
        # 不了这里——`_finalize` 在提交终态的同笔事务里就 clear 了；能走进重放分支
        # 说明 `user_cd` 仍是 `ADVENTURING`，只可能是别处拿**陈旧整行快照**把忙碌
        # 复活了（`update_user_cd` 是全列 UPDATE；GM 强制结算在 2026-10-15 收窄前
        # 走的正是这条直写，现已成为只写 `scheduled_time` 的
        # `db.ext.update_user_cd_fields`）。复活态下
        # 三个出口原本全断：迎战/逃跑被归属闸门正确拒绝、重放不碰忙碌，而
        # `assert_idle` 与 `@player_required` 都不看 `scheduled_time` ⇒ 永久「历练
        # 中」、重启不自愈，只能管理员「清除CD」弃单。补这一次收尾让玩家点一次
        # 「完成历练」即自愈；重复发奖由 claim 挡着，与重放语义一致。
        # 判定读**库里当下**的忙碌行而非调用方快照（同 `_owned_open_run`）：若本次
        # 调用期间玩家已经开了**更新的一场**历练（extra 是别的 run id），绝不能把
        # 新忙碌清掉——那正是本轮刚修掉的那类陈旧写入。extra 没有 run id 的行属于
        # 升级前的老忙碌（就是本场），照常收尾。
        fresh = await self.db.ext.get_user_cd(player.user_id)
        if fresh and int(fresh.type) == int(UserStatus.ADVENTURING):
            current_run = self._read_extra(fresh).get("adventure_run_id")
            if not current_run or current_run == row["adventure_run_id"]:
                await self.busy_state.clear(player)
                await self.db.update_player(player)
        return True, msg, None

    def _render_pending(self, row: dict, route: dict, player: Player) -> str:
        """Build the 战前抉择 message（甲案：内联敌人身份 + 两条出路）."""
        snapshot = self._read_snapshot(row)
        enemy = snapshot.get("enemy") or {}
        combat = snapshot.get("combat") or {}
        my_agility = int((combat.get("player") or {}).get("agility") or 0)
        enemy_agility = int((combat.get("enemy") or {}).get("agility") or 0)
        chance = compute_flee_chance(my_agility, enemy_agility, self.flee_params)
        event = snapshot.get("event") or {}
        return (
            f"⚔️ 历练遭遇劲敌！\n"
            f"路线：{route.get('name', route['key'])}（{route.get('risk', '')}风险）\n"
            f"敌方：{enemy.get('name', '不明来路')}\n"
            f"我方身法 {my_agility} / 敌方身法 {enemy_agility}\n"
            f"📜 {self._select_event_desc(event, player)}\n\n"
            f"此次遭遇已经锁定，机会只能博一次：\n"
            f"· 发送「迎战」立即开打（逃跑失败后也直接开打，不再给第二次退路）\n"
            f"· 发送「逃跑」尝试脱离，成算约 {chance * 100:.0f}%（脱身后这趟白跑大半：收益只留三成，无掉落、无传承机缘）\n"
            f"⚠️ 未做出选择前本次历练不会结算，历练中的你无法开始新的历练。"
        )

    def _render_result(
        self,
        route: dict,
        event: dict,
        player: Player,
        rewards: dict,
        combat_msg: str,
        state: str,
        fatigue_seconds: int,
        notes: list[str],
        *,
        duration: int = 0,
        replayed: bool = False,
    ) -> str:
        """Assemble the settlement message (same shape as the pre-v39 output).

        Args:
            route: 路线配置。
            event: 快照事件。
            player: 玩家对象（显示气血）。
            rewards: 修为/灵石。
            combat_msg: 战报片段。
            state: 终态；决定标题（归来/受挫/脱身）。
            fatigue_seconds: 本次休整秒数。
            notes: 效果片段（掉落、传承、失败提示）。
            duration: 本次历练实际历时秒数（快照里的有效时长）。
            replayed: True 表示重放既成事实，文案要挑明不会重复发放。

        Returns:
            结算消息。
        """
        title = {
            STATE_RESOLVED_WIN: "🚶 历练归来",
            STATE_RESOLVED_LOSS: "💥 历练受挫",
            STATE_RESOLVED_FLED: "💨 历练脱身",
        }.get(state, "🚶 历练归来")
        # 宗门专属事件（带 sect_id）在结算消息中显性标记，普通事件文案不变（现网口径）
        event_desc = self._select_event_desc(event, player)
        event_line = (
            f"🏯 宗门际遇 · {event.get('name', '')}\n{event_desc}"
            if event.get("sect_id")
            else f"📜 {event_desc}"
        )
        lines = [
            f"{title} · {route.get('name', route['key'])}",
            "━━━━━━━━━━━━━━━",
            event_line,
        ]
        if replayed:
            lines.append("ℹ️ 本次历练此前已结算，以下为既成事实，不会重复发放奖励。")
        if combat_msg:
            lines.append(combat_msg.strip("\n"))
        if duration > 0:
            lines.append(f"本次历练：{duration // 60} 分钟")
        lines.append(f"获得修为：+{int(rewards.get('exp', 0)):,}")
        lines.append(f"获得灵石：+{int(rewards.get('gold', 0)):,}")
        for note in notes:
            lines.append(note.strip("\n"))
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(f"当前修为：{int(player.experience or 0):,}")
        lines.append(f"当前灵石：{int(player.gold or 0):,}")
        lines.append(f"❤️ 当前气血：{int(player.current_hp or 0):,}")
        if fatigue_seconds > 0:
            lines.append(
                f"⏳ 历练休整：{fatigue_seconds // 60} 分钟（期间无法开始新历练）"
            )
        return "\n".join(lines)

    def _read_extra(self, user_cd) -> dict:
        """Decode ``user_cd.extra_data`` into a dict (tolerating legacy rows)."""
        if hasattr(user_cd, "get_extra_data"):
            try:
                return user_cd.get_extra_data() or {}
            except Exception:  # noqa: BLE001 - 脏 extra_data 不该打断结算
                return {}
        try:
            return json.loads(getattr(user_cd, "extra_data", "{}") or "{}") or {}
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _read_snapshot(row: dict) -> dict:
        """Decode the immutable lock snapshot of a settlement row."""
        raw = row.get("snapshot") or "{}"
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw) or {}
        except Exception:  # noqa: BLE001 - 坏 snapshot 退回空输入，不崩结算
            logger.error(f"历练结算 snapshot 解析失败：{str(raw)[:120]}")
            return {}

    @staticmethod
    def _legacy_encounter_id(enemy_info: dict, snapshot: dict) -> str:
        """Encounter identity for a run whose enemy profile is not approved yet.

        PRD R3：名册未获批期间 ``profile_id`` 合法留空，此时 ``encounter_id``
        记 legacy 身份（敌人名称 + 境界 + 锁定 seed），而不是抄路线 key——
        key 会诱导读表方把它当成 encounter 定义。三段都取自快照，所以同一张
        单子重放得到同一个字符串，可当稳定身份用；留空不是 bug。
        """
        profile_id = str(enemy_info.get("profile_id") or "")
        if profile_id:
            return profile_id
        name = str(enemy_info.get("name") or "unknown")
        level_index = int(enemy_info.get("level_index") or 0)
        seed = int(snapshot.get("rng_seed") or 0)
        return f"legacy:{name}@L{level_index}#S{seed:x}"

    def _route_of(self, row: dict) -> dict | None:
        """Resolve the route config a settlement belongs to (route_key first)."""
        key = row.get("route_key") or self._read_snapshot(row).get("route_key") or ""
        return self.routes.get(key) or self.routes.get(self.default_route_key)

    def _offers_choice(self, snapshot: dict) -> bool:
        """Whether this locked encounter should stop at ``pending_choice``.

        **全风险段遇敌都给一次战前选择**（§Q4 2026-10-19 重拍：低风险也有残血玩家
        撞普通怪败到 1% 地板的情形，后路需求由玩家状态而非敌人档位驱动）。
        ``flee.enabled=false``（人工 kill switch）时不产生 pending，避免玩家多发一条
        「迎战」却没有任何选择收益（design §1）。

        注意 ``snapshot.get("combat")`` 的存在性判定是**承重**的，不是保险：
        :meth:`_lock_encounter` 对每个完成的 run 都调本方法，未遇敌 run 的快照没有
        ``combat``——「未遇敌直通 ``resolved_win``」全靠这一条。删掉它，未遇敌完成的
        历练也会挂 pending，契约直接崩。
        """
        if not self.flee_params.get("enabled", True):
            return False
        return bool(snapshot.get("combat"))

    def _flee_succeeded(self, snapshot: dict) -> bool:
        """Roll the flee check deterministically from the locked snapshot.

        概率只消费快照里的双方身法（AC3），随机数来自 ``rng_seed`` 派生的
        ``flee`` 子流并走局部 ``Random``：既不扰动全局战斗流，也让「先逃跑失败
        再被打死」与「重放」看到同一个判定——反复发「逃跑」博概率是不可能的，
        因为失败后状态就推进到 ``ready_combat``，不再给第二次机会。

        Args:
            snapshot: 锁定快照。

        Returns:
            逃跑是否成功。
        """
        combat = snapshot.get("combat") or {}
        chance = compute_flee_chance(
            int((combat.get("player") or {}).get("agility") or 0),
            int((combat.get("enemy") or {}).get("agility") or 0),
            self.flee_params,
        )
        roll = random.Random(_seed_stream(int(snapshot.get("rng_seed") or 0), "flee"))
        return roll.random() < chance

    def _fled_rewards(self, snapshot: dict) -> dict:
        """Shape the 收益 of a successful 逃跑: base_reward × ``FLED_REWARD_RATIO``.

        §Q4 2026-10-19 重拍「白跑大半趟」的唯一实现点：``resolved_fled`` 的修为/灵石
        都按快照基础收益（已含事件倍率）乘以系数后 int 截断。fled 不含 ``bonus_exp``，
        因为快照的 ``base_reward`` 只有 exp/gold，bonus_exp 仅战胜 outcome 产生
        （managers/pve_combat_manager.py:281），维持现状。

        Args:
            snapshot: 锁定快照。

        Returns:
            ``{"exp": int, "gold": int}``。结算与重放两条路径共用，避免两处各自算。
        """
        base = snapshot.get("base_reward") or {}
        return {
            "exp": int(int(base.get("exp", 0) or 0) * FLED_REWARD_RATIO),
            "gold": int(int(base.get("gold", 0) or 0) * FLED_REWARD_RATIO),
        }

    async def _maybe_trigger_legacy(
        self, player: Player, *, roll_value: float | None = None
    ) -> str:
        """按配置概率触发传承机缘：挂起传承之地 pending 遭遇（应邀制，design D8）。

        不再内联挑战守护者；玩家经「探索秘境 传承」应邀（探索秘境为遭遇响应
        枢纽，含历练来源——命名取舍见 design D8）。

        Args:
            player: 触发机缘的玩家。
            roll_value: 传承判定用的 [0,1) 随机数。历练结算必须传由
                ``snapshot.rng_seed`` 派生的固定值（每单只博一次，重放不改判）；
                省略时沿用全局随机流（秘境等一次性路径）。

        Returns:
            追加到结算消息的提示文本（未触发时为空串）。
        """
        chance_roll = random.random() if roll_value is None else roll_value
        if chance_roll >= self.legacy_chance:
            return ""
        if self.encounter_store is None:
            return ""
        # TTL 不显式传：用 store 默认值——装配时（main.py）已注入
        # encounter_ttl_seconds 配置值，历练/秘境两条路径时限语义一致
        self.encounter_store.pend(
            player.user_id,
            KIND_LEGACY,
            {"legacy_type": self.legacy_type, "source": "adventure"},
        )
        # 提示文案与 RiftManager._pend_legacy_encounter 保持逐字一致
        # （两处各写一份，避免为单行文案引入跨管理器依赖）
        return (
            "\n\n🗿 你偶遇上古传承之地，传承禁制悄然开启。\n"
            "💡 发送「探索秘境 传承」应邀挑战守护者（不响应则机缘自行消散，无任何惩罚）"
        )

    async def check_adventure_status(self, user_id: str) -> tuple[bool, str]:
        """Report 历练 status, including a parked pre-combat choice and its two exits."""
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd or user_cd.type != UserStatus.ADVENTURING:
            return False, "❌ 你当前不在历练中！"
        player = await self.db.get_player_by_id(user_id)

        now = int(time.time())
        route_name = "未知路线"
        extra = {}
        if hasattr(user_cd, "get_extra_data"):
            extra = user_cd.get_extra_data()
        else:
            try:
                extra = json.loads(getattr(user_cd, "extra_data", "{}") or "{}")
            except Exception:
                extra = {}
        route = self.routes.get(extra.get("route_key", self.default_route_key))
        if route:
            route_name = route["name"]

        if now >= user_cd.scheduled_time:
            row = await self.settlements.get_open_settlement(user_id)
            if row and row["state"] == STATE_PENDING_CHOICE and player and route:
                return True, self._render_pending(row, route, player)
            return True, f"✅ {route_name} 已完成！使用 /完成历练 领取奖励。"

        remaining = user_cd.scheduled_time - now
        elapsed = now - user_cd.create_time
        minutes = remaining // 60
        seconds = remaining % 60
        elapsed_minutes = elapsed // 60

        msg = (
            f"📍 历练进度 · {route_name}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"已历练：{elapsed_minutes} 分钟\n"
            f"剩余时间：{minutes}分{seconds}秒\n"
            f"请耐心等待历练完成..."
        )
        return True, msg

    # -------- 内部工具 --------

    def _resolve_route(self, token: str) -> str:
        """Map a user token (route key, name, or alias) to a route key, falling back to the default route."""
        if not token:
            return self.default_route_key
        normalized = token.strip().lower()
        return self.route_alias_index.get(normalized, self.default_route_key)

    async def _get_player_faction_id(self, player: Player) -> str | None:
        """Resolve the faction_id of the player's sect (None when sectless or a player-built sect)."""
        sect_id = getattr(player, "sect_id", 0)
        if not isinstance(sect_id, int) or not sect_id:
            return None
        if self.db is None or getattr(self.db, "ext", None) is None:
            return None
        sect = await self.db.ext.get_sect_by_id(sect_id)
        if sect is None:
            return None
        return getattr(sect, "faction_id", None)

    def _filter_group_events(
        self, events: list[dict], faction_id: str | None
    ) -> list[dict]:
        """Keep events with no sect attribution plus events matching the player's sect faction."""
        return [
            event
            for event in events
            if isinstance(event, dict)
            and (not event.get("sect_id") or event.get("sect_id") == faction_id)
        ]

    def _select_event_desc(self, event: dict, player: Player) -> str:
        """Pick the event's narrative copy for the player.

        ``desc_variants`` (design D7) is normalized by the shared
        ``select_narrative_pool`` helper: bucketed pools merge the player's
        current realm-segment bucket with the 通用 bucket and filter
        route-tagged entries by the player's cultivation route. An empty pool
        (no variants configured, uncovered segment, or everything filtered)
        falls back to the verbatim ``desc`` field.
        """
        pool = select_narrative_pool(
            event.get("desc_variants"),
            route=getattr(player, "cultivation_type", None),
            level_index=getattr(player, "level_index", None),
            scene_label="adventure.desc_variants",
        )
        if pool:
            return random.choice(pool)
        return event["desc"]

    def _build_event_weight_pool(
        self, route: dict, faction_id: str | None
    ) -> dict[str, int]:
        """Build the effective event-group weight pool for a route and player faction.

        Groups whose events all carry a mismatched ``sect_id`` are dropped.
        Sect groups (any event carrying ``sect_id``) not referenced by the
        route are appended with ``SECT_EVENT_GROUP_WEIGHT`` when the player
        belongs to that sect.
        """
        weights: dict[str, int] = {}
        for key, weight in (route.get("event_weights", {}) or {}).items():
            group = self.event_groups.get(key)
            if group is None:
                weights[key] = weight
                continue
            if self._filter_group_events(group, faction_id):
                weights[key] = weight
        if faction_id:
            for key, events in self.event_groups.items():
                if key in weights:
                    continue
                if not any(
                    isinstance(event, dict) and event.get("sect_id") for event in events
                ):
                    continue
                if self._filter_group_events(events, faction_id):
                    weights[key] = self.SECT_EVENT_GROUP_WEIGHT
        return weights

    def _trigger_route_event(self, route: dict, faction_id: str | None = None) -> dict:
        """Weighted-random pick an event group for the route, then uniformly pick one event from it.

        Sect-attributed groups/events only enter the pool when the player's
        sect faction matches; everything else is unchanged.
        """
        weights = self._build_event_weight_pool(route, faction_id)
        if not weights:
            group_key = "standard"
        else:
            total_weight = sum(max(0, w) for w in weights.values()) or 1
            roll = random.randint(1, total_weight)
            upto = 0
            group_key = "standard"
            for key, weight in weights.items():
                upto += max(0, weight)
                if roll <= upto:
                    group_key = key
                    break

        group = (
            self.event_groups.get(group_key)
            or self.event_groups.get("standard")
            or self.DEFAULT_CONFIG["event_groups"]["standard"]
        )
        eligible = self._filter_group_events(group, faction_id)
        if not eligible:
            eligible = self._filter_group_events(
                self.event_groups.get("standard")
                or self.DEFAULT_CONFIG["event_groups"]["standard"],
                faction_id,
            )
        return random.choice(eligible)

    def _calculate_rewards(
        self, player: Player, route: dict, duration: int, event: dict
    ) -> dict[str, int]:
        """Compute exp/gold from route per-minute rates, level bonus, completion bonus, and the event multiplier."""
        duration_minutes = max(1, duration // 60)
        base_exp = duration_minutes * route.get("base_exp_per_min", 40)
        base_gold = duration_minutes * route.get("base_gold_per_min", 10)

        level_bonus_exp = player.level_index * route.get("level_bonus_exp", 10)
        level_bonus_gold = player.level_index * route.get("level_bonus_gold", 2)

        completion_bonus = route.get("completion_bonus", {})
        exp_total = base_exp + level_bonus_exp + completion_bonus.get("exp", 0)
        gold_total = base_gold + level_bonus_gold + completion_bonus.get("gold", 0)

        final_exp = max(0, int(exp_total * event.get("exp_mult", 1.0)))
        final_gold = max(0, int(gold_total * event.get("gold_mult", 1.0)))
        return {"exp": final_exp, "gold": final_gold}

    async def _handle_drops(
        self, player: Player, route: dict, event: dict
    ) -> tuple[list[tuple[str, int]], str]:
        """Roll an item drop (event item_chance) from the tier drop table and store it in the storage ring."""
        dropped_items: list[tuple[str, int]] = []
        if not self.storage_ring_manager:
            return dropped_items, ""

        item_chance = event.get("item_chance", 40)
        if random.randint(1, 100) > item_chance:
            return dropped_items, ""

        tier = event.get("drop_tier") or route.get("drop_tier") or "low"
        drop_table = self.drop_tables.get(
            tier, self.DEFAULT_CONFIG["drop_tables"]["low"]
        )
        total_weight = sum(item["weight"] for item in drop_table)
        roll = random.randint(1, total_weight)
        upto = 0
        chosen = drop_table[0]
        for item in drop_table:
            upto += item["weight"]
            if roll <= upto:
                chosen = item
                break

        count = random.randint(chosen["min"], chosen["max"])
        dropped_items.append((chosen["name"], count))

        item_lines = []
        for item_name, qty in dropped_items:
            success, _ = await self.storage_ring_manager.store_item(
                player, item_name, qty, silent=True
            )
            if success:
                item_lines.append(f"  · {item_name} x{qty}")
            else:
                item_lines.append(f"  · {item_name} x{qty}（储物戒已满，丢失）")

        if item_lines:
            return dropped_items, "\n\n📦 获得物品：\n" + "\n".join(item_lines)
        return dropped_items, ""

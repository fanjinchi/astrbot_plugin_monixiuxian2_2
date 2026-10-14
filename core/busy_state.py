"""Player busy/cooldown state owner (openspec change: busy-state-owner).

Single write path for the two-layer busy state:
- ``players.state`` mirror string ("空闲" / "修炼中" / ...)
- ``user_cd`` table row (``UserStatus`` enum)

Before this module, the two layers had no owner: runtime code wrote
``player.state`` in 4 places (3 of them non-atomic double writes) and
adventure/rift wrote ``user_cd`` without maintaining the mirror.  All
busy/cooldown writes are routed through ``BusyState`` from now on.

Design references: openspec/changes/busy-state-owner/{proposal,design,tasks}.md
"""

import importlib.util
import os
import sys

try:
    from ..data import DataBase
    from ..data.pve_repository import STATE_PENDING_CHOICE, AdventureRepository
    from ..models import Player
    from ..models_extended import UserStatus
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

    # 在独立测试环境中这些类仅用于类型标注，使用 object 占位
    DataBase = object

    _models = _load_module("models", "models.py")
    Player = _models.Player
    _models_extended = _load_module("models_extended", "models_extended.py")
    UserStatus = _models_extended.UserStatus

    # 历练结算状态机（child C）：忙碌拒绝文案需要发现「挂战前抉择」的单子。
    _pve_repository = _load_module("pve_repository", "data/pve_repository.py")
    AdventureRepository = _pve_repository.AdventureRepository
    STATE_PENDING_CHOICE = _pve_repository.STATE_PENDING_CHOICE

# GM「时间快进」覆盖条目（openspec change: gm-time-skip-registry）：声明即覆盖，
# 只前移参与到期/冷却判定的时间戳。由 core/time_skip_registry.py 装配汇总。
TIME_SKIP_ENTRIES: tuple[tuple[str, str], ...] = (
    (
        "历练/秘境/宗门任务计划完成时间",
        "UPDATE user_cd SET scheduled_time = scheduled_time - ? "
        "WHERE type != 0 AND scheduled_time > 0",
    ),
)

# 默认忙碌报错模板（sect 系守卫的支配文案，10+ 站点的原文；"你当前正{status}"）。
# assert_idle 的 template 形参默认值；战斗/炼丹/双修等站点在调用处传专属模板。
DEFAULT = "❌ 你当前正{status}，无法进行此操作！"

# 挂战前抉择（pending_choice）时忙碌文案追加的出路提示（design §1 甲案②、
# PRD AC11）。pending 是唯一「被锁住却看不见出口」的窗口：玩家既不发送「迎战」
# 也不发送「逃跑」，本次历练就无限期不结算，所以**每一条**忙碌拒绝都必须自带
# 两条出路。两条渲染路径（本类 assert_idle 的 18 处自定义模板 + handlers/utils
# 的 @player_required 拦截器）共用这个常量，测试逐字钉住防漂移。
PENDING_CHOICE_HINT = "\n💡 可发送「迎战」或「逃跑」结束本次历练。"


async def pending_choice_hint(db, user_id: str) -> str:
    """Return :data:`PENDING_CHOICE_HINT` when that player is stuck on a choice.

    只有「数据库里真有一张挂着待抉择的结算单」才追加提示：非历练忙碌、还在
    战斗中（``adventuring``/``ready_combat``）或已结算的玩家拿到空串，原有
    忙碌文案逐字不变（PRD AC11 后半句）。

    本函数**只看账本，不看忙碌**：调用方必须自己确认 ``user_cd.type ==
    UserStatus.ADVENTURING`` 再调用。管理员「清除CD」只复位忙碌、不终结结算
    单，孤儿 pending 行会留在账上；不加门控就会给闭关/修炼玩家递上一句
    「发迎战吧」，而那次迎战并不属于他当前的历练。

    Args:
        db: The plugin DataBase (``self.db``); only ``db.conn`` is used.
        user_id: Player being blocked by the busy gate.

    Returns:
        以换行开头的提示片段，或空串。
    """
    # 每次现建仓储：DataBase.connect() 会替换 conn，持有实例会拿到死连接，
    # 所以这里（以及全项目）都不把 AdventureRepository 缓存成单例。
    row = await AdventureRepository(db.conn).get_open_settlement(user_id)
    if row and row["state"] == STATE_PENDING_CHOICE:
        return PENDING_CHOICE_HINT
    return ""


class BusyState:
    """Sole write path for player busy/cooldown state (design D1/D2).

    Dual semantics:
    - ``set_busy`` = activity state (闭关/历练/秘境): writes ``user_cd`` AND
      maintains the ``player.state`` mirror.  The mirror only recognizes
      CULTIVATING ("修炼中"); every other activity resets it to "空闲" —
      this faithfully preserves the pre-owner semantics where ``player.state``
      was a pure mirror of ``user_cd.type == CULTIVATING``.
    - ``set_cooldown`` = pure timestamp cooldown (SECT_TASK): writes
      ``user_cd`` only, no mirror, no clear entry, no lock recheck.  Status
      quo preserved: the sect write already happened inside
      ``perform_sect_task``'s own transaction and R1 race control does not
      extend to the cooldown path.

    Race semantics (R1): ``set_busy`` re-reads the current ``user_cd`` row
    inside its ``BEGIN IMMEDIATE`` transaction (the write lock is held, so the
    read is a recheck, not a TOCTOU snapshot).  A concurrent loser aborts the
    transaction and receives the default busy message instead of silently
    overwriting the winner's state.  ``txn.abort()`` only marks the shared
    TxnState: the owner rolls back on clean exit without re-raising (design D1
    abort contract of add-transaction-unit-of-work).

    Explicit exception to the single-write path: GM force-settle in
    ``core/gm_manager.py`` (:997/:1071) keeps direct ``update_user_cd`` calls
    (scheduled_time bump only — not a regular busy-state write).  Everything
    else must go through this class.

    Args:
        db: The plugin DataBase instance (assembly-injected; never
            self-constructed by consumers).
        health_service: Optional HealthService (child A player-health
            foundation).  Every authoritative user_cd write settles the OLD
            state and advances the recovery anchor inside the SAME outer
            transaction before the new status is written.  Recovery itself is
            time-based and ignores the busy flag (2026-10-12: the busy gate
            was removed, so a busy player keeps healing); the settle here only
            keeps anchor + status atomic and syncs the in-memory mirror.
            None only in unit-test fixtures that do not wire the health domain.
    """

    def __init__(self, db: "DataBase", health_service=None):
        self._db = db
        self._health = health_service

    async def set_busy(
        self,
        player: Player,
        status: int,
        scheduled_time: int = 0,
        extra_data: dict | None = None,
    ) -> tuple[bool, str | None]:
        """Mark an activity state (闭关/历练/秘境) with a lock-in recheck.

        Inside a transaction (holding BEGIN IMMEDIATE) the current ``user_cd``
        row is re-read: if the player is already busy the transaction is
        aborted and ``(False, message)`` is returned, where message is the
        default template formatted with the player's CURRENT busy status —
        this closes the concurrent start-race that previously let two commands
        both pass an IDLE precheck (last write wins).  On success the
        ``user_cd`` row is upserted (``set_user_busy``) and the ``player.state``
        mirror is maintained (CULTIVATING → "修炼中", any other activity →
        "空闲").  Per-caller fancy messages are NOT accepted here: callers
        should precheck with ``assert_idle`` and pass their own template; the
        default message is only visible in the race window.

        Args:
            player: Player object; ``user_id`` (persistence), ``state``
                (mirror) and ``current_hp`` (settle 结算值同步，防止后续
                update_player 陈旧回写) are touched.
            status: Activity status (UserStatus member / int value).
            scheduled_time: Planned completion timestamp; 0 for indefinite.
            extra_data: Optional payload (e.g. adventure route_key, rift
                id/level) forwarded to ``set_user_busy``.

        Returns:
            (True, None) on success; (False, busy_message) when the player is
            already busy at recheck time.
        """
        async with self._db.transaction() as txn:
            user_cd = await self._db.ext.get_user_cd(player.user_id)
            if user_cd is not None and user_cd.type != UserStatus.IDLE:
                # Race loser: abort the whole transaction (marker only — the
                # owner rolls back on clean exit), report the current status.
                txn.abort()
                return False, DEFAULT.format(status=UserStatus.get_name(user_cd.type))
            # 健康域结算点（child A AC4）：同一事务内先结算旧状态并前移
            # 恢复锚点，再写新忙碌状态；败者分支保持纯只读、零写入。
            # settle 的返回值回写内存 current_hp：本流程后续的
            # update_player 才不会把已结算的回血用陈旧值刷掉。
            if self._health is not None:
                player.current_hp = await self._health.settle(player.user_id)
            await self._db.ext.set_user_busy(
                player.user_id, int(status), scheduled_time, extra_data or {}
            )
            player.state = "修炼中" if status == UserStatus.CULTIVATING else "空闲"
            return True, None

    async def set_cooldown(
        self, user_id: str, status: int, scheduled_time: int
    ) -> None:
        """Write a pure timestamp cooldown (SECT_TASK) without a mirror.

        Cooldown semantics: only ``user_cd`` is written, the state expires
        when ``scheduled_time`` passes (checked by the caller) and there is no
        ``clear`` entry — a cooldown can only be overwritten or left to
        expire.  No lock recheck is performed (R1 race control does not extend
        to the cooldown path); the call joins a caller's outer transaction
        when nested (same-task no-op join).

        Args:
            user_id: Target player user id.
            status: Cooldown type (UserStatus member / int value).
            scheduled_time: Cooldown expiry timestamp.
        """
        async with self._db.transaction():
            if self._health is not None:
                # 同事务结算旧状态 + 前移锚点（AC4，与 set_busy 同规则）。
                await self._health.settle(user_id)
            await self._db.ext.set_user_busy(user_id, int(status), scheduled_time)

    async def stamp_extra(self, user_cd, extra_data: dict) -> None:
        """Rewrite ``extra_data`` on a busy row the player already holds.

        身份字段补写，不是常态忙碌写入：``type``/``create_time``/``scheduled_time``
        一律按**调用方持有的那份快照**整行回写，只换 ``extra_data``。不在事务内
        重读：这一路径只在升级那一刻被走到（老忙碌行没有 run id），而真在那个微秒
        间隙被别的任务清了忙碌、或被管理员 bump 过到期时间，盖回原值同样自洽
        ——extra 与单据始终一致，「迎战/逃跑」或再点「完成历练」都能收尾，多一次
        查库换不来实际安全。走 owner（本类）而不是让业务模块裸调
        ``db.ext.update_user_cd``，是为了守住 AGENTS.md §2「忙碌读写由 BusyState
        承接」——GM 强制结算的 ``scheduled_time`` bump 是文档里唯一的例外。

        Args:
            user_cd: 调用方已读到的忙碌行（对象本身会被就地更新）。
            extra_data: 新的 extra 载荷（如 ``{"route_key", "adventure_run_id"}``）。
        """
        async with self._db.transaction():
            user_cd.set_extra_data(extra_data)
            await self._db.ext.update_user_cd(user_cd)

    async def clear(self, player: Player) -> None:
        """Unconditionally reset a player to idle (user_cd + mirror).

        ``set_user_free`` is an idempotent upsert, so clearing a player with
        no ``user_cd`` row is a no-op write; the mirror is set to "空闲".
        Whether the target WAS busy is the caller's concern (e.g. GM
        ``cmd_clear_cd`` keeps its own precheck) — this method never rejects.

        Args:
            player: Player object whose state mirror is reset in memory.
        """
        async with self._db.transaction():
            if self._health is not None:
                # 转空闲前结算：把到此刻为止的分钟级恢复入账并前移锚点。
                # 忙碌期不再冻结回血（2026-10-12 取消闸门），所以这里结算的
                # 就是整段窗口内应得的血。返回值同步内存 current_hp，避免
                # 调用方后续 update_player 陈旧回写。
                player.current_hp = await self._health.settle(player.user_id)
            await self._db.ext.set_user_free(player.user_id)
            player.state = "空闲"

    async def assert_idle(self, user_id: str, template: str = DEFAULT) -> str | None:
        """Read-side busy guard: return a message when the user is busy.

        A missing ``user_cd`` row counts as idle (None), matching the legacy
        ``user_cd and user_cd.type != UserStatus.IDLE`` semantics.  When busy,
        the given template is formatted with the user's current busy status
        name (via ``UserStatus.get_name``) and returned.

        Args:
            user_id: Target player user id.
            template: Message template containing a ``{status}`` placeholder
                (default: the generic sect-family message).

        Returns:
            None when idle; the formatted busy message otherwise.  历练忙碌且
            挂战前抉择时，消息尾部自带「迎战/逃跑」出路提示（PRD AC11）；其它
            忙碌状态逐字不变。
        """
        user_cd = await self._db.ext.get_user_cd(user_id)
        if user_cd is None or user_cd.type == UserStatus.IDLE:
            return None
        message = template.format(status=UserStatus.get_name(user_cd.type))
        if user_cd.type == UserStatus.ADVENTURING:
            # 只有历练才可能挂 pending：其余忙碌状态不额外查库，文案零变化。
            message += await pending_choice_hint(self._db, user_id)
        return message

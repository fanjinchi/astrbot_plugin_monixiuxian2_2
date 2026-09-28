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
    """

    def __init__(self, db: "DataBase"):
        self._db = db

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
            player: Player object; only ``user_id`` (persistence) and
                ``state`` (mirror) are touched.
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
            await self._db.ext.set_user_busy(user_id, int(status), scheduled_time)

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
            None when idle; the formatted busy message otherwise.
        """
        user_cd = await self._db.ext.get_user_cd(user_id)
        if user_cd is None or user_cd.type == UserStatus.IDLE:
            return None
        return template.format(status=UserStatus.get_name(user_cd.type))

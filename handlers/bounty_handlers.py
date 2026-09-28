# handlers/bounty_handlers.py
"""悬赏令处理器"""

from astrbot.api.event import AstrMessageEvent

from ..data import DataBase
from ..managers.bounty_manager import BountyManager
from ..models import Player
from .utils import player_required

__all__ = [
    "BountyHandlers",
    "format_bounty_entry",
    "render_bounty_list",
    "render_bounty_action",
]


def format_bounty_entry(b: dict) -> str:
    """Render one bounty entry as a multi-line display block.

    Stateless: pure formatting of a single list-entry dict, no manager or DB
    access. Shared by the global and sect bounty list entries so the per-entry
    layout stays identical on both sides.

    Args:
        b: A bounty list-entry dict (from ``BountyManager.get_bounty_list``).

    Returns:
        The multi-line entry text (no leading/trailing blank lines).
    """
    reward = b.get("reward", {})
    return (
        f"[{b['id']}] {b['name']}（{b.get('difficulty_name', '未知')}·{b.get('category', '任务')}）\n"
        f"  - 目标：完成 {b.get('count')} 次 | 时限：{b.get('time_limit', 0) // 60} 分钟\n"
        f"  - 奖励：{reward.get('stone', 0):,} 灵石 + {reward.get('exp', 0):,} 修为\n"
        f"  - 说明：{b.get('description', '')}"
    )


async def render_bounty_list(
    bounty_mgr: BountyManager, player: Player, scope: str
) -> str:
    """Render the bounty list, shared by the global and sect entries.

    Stateless: only orchestrates ``bounty_mgr.get_bounty_list`` (scope is
    always passed explicitly) and formats text via ``format_bounty_entry``.
    Title, footer, and empty-state behavior branch by ``scope``: the global
    entry never short-circuits on an empty list, while the sect entry renders
    a dedicated empty block without a footer.

    Args:
        bounty_mgr: The manager to load the list from.
        player: The requesting player.
        scope: "global" or "sect".

    Returns:
        The fully rendered list text.
    """
    if scope == "sect":
        title = "🏯 宗门悬赏 · 本宗委托"
        footer = "💡 使用 /宗门 悬赏 接取 <编号> 接取任务"
    else:
        title = "📜 悬赏令 · 今日委托"
        footer = "💡 使用 /接取悬赏 <编号> 接取任务；宗门悬赏请使用 /宗门 悬赏"

    bounties = await bounty_mgr.get_bounty_list(player, scope=scope)
    if scope == "sect" and not bounties:
        return "🏯 宗门悬赏\n━━━━━━━━━━━━━━━\n本宗当前无可接取的宗门悬赏。"

    lines = [title, "━━━━━━━━━━━━━━━"]
    lines.extend(format_bounty_entry(b) for b in bounties)
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(footer)
    return "\n".join(lines)


async def render_bounty_action(
    bounty_mgr: BountyManager,
    player: Player,
    action: str,
    args: list[str],
    scope: str,
) -> tuple[bool, str] | None:
    """Execute one bounty action, shared by the global and sect entries.

    Stateless: only orchestrates the matching BountyManager method (always
    passing ``scope=scope`` explicitly — the manager default is global
    semantics and must not be relied on here) and never decorates the returned
    message (status emoji comes from the manager itself, AGENTS.md §8).
    ``args`` holds the tokens AFTER ``action``: global delegates pass
    ``[str(bounty_id)]``, the sect dispatcher passes ``args[1:]``. Bounty-id
    validation (missing / non-numeric / <=0) is centralized here for both
    entries; the defensive hint's example branches by ``scope``. ``action``
    accepts the canon sect names 接取/进度/完成/放弃 plus their English aliases
    accept/status/complete/abandon used by the global delegates.

    Args:
        bounty_mgr: The manager to operate on.
        player: The requesting player.
        action: The canon action name (or its English alias).
        args: Tokens after the action; the accept branch treats ``args[0]``
            as the bounty-id candidate.
        scope: "global" or "sect".

    Returns:
        The manager's ``(success, msg)`` tuple (msg already carries the
        manager's own status emoji), or None when ``action`` is unrecognized.
    """
    if action in ("接取", "accept"):
        bounty_id = int(args[0]) if args and args[0].isdecimal() else 0
        if bounty_id <= 0:
            hint = "/接取悬赏 1" if scope == "global" else "/宗门 悬赏 接取 307"
            return False, f"❌ 请指定悬赏编号，例如：{hint}"
        return await bounty_mgr.accept_bounty(player, bounty_id, scope=scope)
    if action in ("进度", "status"):
        return await bounty_mgr.check_bounty_status(player, scope=scope)
    if action in ("完成", "complete"):
        return await bounty_mgr.complete_bounty(player, scope=scope)
    if action in ("放弃", "abandon"):
        return await bounty_mgr.abandon_bounty(player, scope=scope)
    return None


class BountyHandlers:
    """悬赏令处理器。

    约定：manager 消息自带 ❌/✅/⚠️/🎯 状态符，handler 一律裸渲染 msg、
    不加前缀——同一 manager 方法被全局/宗门两个入口消费，只有 manager 侧
    自带 emoji 才能保证各入口输出一致（见 AGENTS.md §8）。全局入口均为
    薄委托：文本编排统一走模块级共享函数（scope="global"）。
    """

    def __init__(self, db: DataBase, bounty_mgr: BountyManager):
        self.db = db
        self.bounty_mgr = bounty_mgr

    @player_required
    async def handle_bounty_list(self, player: Player, event: AstrMessageEvent):
        """委托 `render_bounty_list` 渲染全局悬赏列表。"""
        msg = await render_bounty_list(self.bounty_mgr, player, "global")
        yield event.plain_result(msg)

    @player_required
    async def handle_accept_bounty(
        self, player: Player, event: AstrMessageEvent, bounty_id: int = 0
    ):
        """委托 `render_bounty_action` 接取悬赏（编号防御在共享函数内）。"""
        _, msg = await render_bounty_action(
            self.bounty_mgr, player, "accept", [str(bounty_id)], "global"
        )
        yield event.plain_result(msg)

    @player_required
    async def handle_bounty_status(self, player: Player, event: AstrMessageEvent):
        """委托 `render_bounty_action` 查看悬赏状态。"""
        _, msg = await render_bounty_action(
            self.bounty_mgr, player, "status", [], "global"
        )
        yield event.plain_result(msg)

    @player_required
    async def handle_complete_bounty(self, player: Player, event: AstrMessageEvent):
        """委托 `render_bounty_action` 完成悬赏。"""
        _, msg = await render_bounty_action(
            self.bounty_mgr, player, "complete", [], "global"
        )
        yield event.plain_result(msg)

    @player_required
    async def handle_abandon_bounty(self, player: Player, event: AstrMessageEvent):
        """委托 `render_bounty_action` 放弃悬赏。"""
        _, msg = await render_bounty_action(
            self.bounty_mgr, player, "abandon", [], "global"
        )
        yield event.plain_result(msg)

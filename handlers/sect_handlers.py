# handlers/sect_handlers.py
from typing import TYPE_CHECKING

from astrbot.api.all import *
from astrbot.api.event import AstrMessageEvent

from ..data.data_manager import DataBase
from ..managers.bounty_manager import BountyManager
from ..managers.sect_manager import SectManager
from ..models import Player
from .bounty_handlers import render_bounty_action, render_bounty_list
from .utils import player_required

if TYPE_CHECKING:
    from ..core.busy_state import BusyState
    from ..managers.ranking_manager import RankingManager


class SectHandlers:
    """Handlers for sect (宗门) commands: unified /宗门 entry dispatcher plus all sub-command implementations."""

    # 缺参子命令的用法提示（spec：缺参时输出该子命令的用法示例）
    _USAGE_HINTS = {
        "创建": "请输入宗门名称，例如：/宗门 创建 逍遥门",
        "加入": "请输入要加入的宗门名称，例如：/宗门 加入 逍遥门",
        "捐献": "请输入捐献数量，例如：/宗门 捐献 1000",
        "踢出": "请指定要踢出的成员，例如：/宗门 踢出 @某人（或成员ID）",
        "传位": "请指定传位目标，例如：/宗门 传位 @某人（或成员ID）",
        "职位": "请输入目标和职位ID(0-4)，例如：/宗门 职位 @某人 1",
    }

    def __init__(
        self,
        db: DataBase,
        sect_mgr: SectManager,
        bounty_mgr: BountyManager | None = None,
        *,
        busy_state: "BusyState",
        rank_mgr: "RankingManager | None" = None,
    ):
        self.db = db
        self.sect_mgr = sect_mgr
        self.bounty_mgr = bounty_mgr
        self.busy_state = busy_state
        self.rank_mgr = rank_mgr

    # ===== 统一入口分发器 =====

    def _navigation_text(self) -> str:
        """Build the /宗门 sub-command navigation help."""
        return (
            "🏯 宗门 · 指令导航\n"
            "━━━━━━━━━━━━━━━\n"
            "入门：宗门 创建 <名称>｜宗门 加入 <名称>｜宗门 退出\n"
            "信息：宗门 信息｜宗门 列表｜宗门 排行｜宗门 贡献排行\n"
            "成长：宗门 任务｜宗门 师承｜宗门 捐献 <数量>｜宗门 晋升\n"
            "建筑：宗门 建设 [洞天/丹房]｜宗门 丹房 [领取]｜宗门 镇派功法 [功法]\n"
            "传承：宗门 宝库 [名称]｜宗门 商店 [购买 <名称>]\n"
            "悬赏：宗门 悬赏 [接取 <编号>|进度|完成|放弃]\n"
            "管理：宗门 踢出 <@成员|ID>｜宗门 传位 <@成员|ID>｜宗门 职位 <@成员|ID> <0-4>"
        )

    @player_required
    async def handle_sect_entry(self, player: Player, event: AstrMessageEvent):
        """/宗门 统一入口：解析首个参数为子命令并分发；无参数或未知子命令输出导航帮助。

        从原始消息文本自行解析参数（AstrBot 指令参数不含子命令路由所需的完整尾部），
        剥离唤醒前缀与指令名本身后，首个 token 为子命令，其余为该子命令的参数。
        """
        text = event.get_message_str().strip()
        # 剥离唤醒前缀（如 / 或 #）与指令名「宗门」本身，剩余为子命令与参数
        tokens = text.lstrip("/#／ ").split()
        if tokens and tokens[0] == "宗门":
            tokens = tokens[1:]

        if not tokens:
            yield event.plain_result(self._navigation_text())
            return

        sub, args = tokens[0], tokens[1:]
        handler = {
            "创建": self._sub_create,
            "加入": self._sub_join,
            "退出": self._sub_leave,
            "信息": self._sub_info,
            "列表": self._sub_list,
            "捐献": self._sub_donate,
            "任务": self._sub_task,
            "丹房": self._sub_elixir,
            "建设": self._sub_construction,
            "镇派功法": self._sub_mainbuff,
            "晋升": self._sub_promote,
            "宝库": self._sub_treasury,
            "师承": self._sub_master,
            "踢出": self._sub_kick,
            "传位": self._sub_transfer,
            "职位": self._sub_position,
            "排行": self._sub_rank,
            "贡献排行": self._sub_rank_contribution,
            "悬赏": self._sub_bounty,
            "商店": self._sub_shop,
        }.get(sub)

        if handler is None:
            yield event.plain_result(
                f"❌ 未识别的宗门子命令「{sub}」。\n\n{self._navigation_text()}"
            )
            return

        async for result in handler(player, event, args):
            yield result

    async def _sub_create(self, player, event, args):
        if not args:
            yield event.plain_result(f"❌ {self._USAGE_HINTS['创建']}")
            return
        async for r in self.handle_create_sect(event, args[0]):
            yield r

    async def _sub_join(self, player, event, args):
        if not args:
            yield event.plain_result(f"❌ {self._USAGE_HINTS['加入']}")
            return
        async for r in self.handle_join_sect(event, args[0]):
            yield r

    async def _sub_leave(self, player, event, args):
        async for r in self.handle_leave_sect(event):
            yield r

    async def _sub_info(self, player, event, args):
        async for r in self.handle_my_sect(event):
            yield r

    async def _sub_list(self, player, event, args):
        async for r in self.handle_sect_list(event):
            yield r

    async def _sub_donate(self, player, event, args):
        # isdecimal 而非 isdigit：上标数字（如 ²）isdigit() 为 True 但 int() 会抛 ValueError
        if not args or not args[0].isdecimal():
            yield event.plain_result(f"❌ {self._USAGE_HINTS['捐献']}")
            return
        async for r in self.handle_donate(event, int(args[0])):
            yield r

    async def _sub_task(self, player, event, args):
        async for r in self.handle_sect_task(event):
            yield r

    async def _sub_elixir(self, player, event, args):
        async for r in self.handle_sect_elixir(event, args[0] if args else ""):
            yield r

    async def _sub_construction(self, player, event, args):
        async for r in self.handle_sect_construction(event, args[0] if args else ""):
            yield r

    async def _sub_mainbuff(self, player, event, args):
        async for r in self.handle_sect_mainbuff(event, args[0] if args else ""):
            yield r

    async def _sub_promote(self, player, event, args):
        async for r in self.handle_sect_promote(event):
            yield r

    async def _sub_treasury(self, player, event, args):
        async for r in self.handle_sect_treasury(event, args[0] if args else ""):
            yield r

    async def _sub_master(self, player, event, args):
        async for r in self.handle_master_task(event):
            yield r

    async def _sub_kick(self, player, event, args):
        if not args:
            yield event.plain_result(f"❌ {self._USAGE_HINTS['踢出']}")
            return
        async for r in self.handle_kick_member(event, args[0]):
            yield r

    async def _sub_transfer(self, player, event, args):
        if not args:
            yield event.plain_result(f"❌ {self._USAGE_HINTS['传位']}")
            return
        async for r in self.handle_transfer(event, args[0]):
            yield r

    async def _sub_position(self, player, event, args):
        # 目标可能来自 At 消息段（由 handle_position_change 解析），也兼容数字成员ID：
        # 取最后一个数字 token 为职位ID、其余为目标，避免「职位 12345 1」把成员ID误当职位
        pos = next((a for a in reversed(args) if a.isdecimal()), None)
        if pos is None:
            yield event.plain_result(f"❌ {self._USAGE_HINTS['职位']}")
            return
        target = next((a for a in args if a != pos), "")
        async for r in self.handle_position_change(event, target, int(pos)):
            yield r

    async def _sub_rank(self, player, event, args):
        if not self.rank_mgr:
            yield event.plain_result("❌ 排行功能不可用！")
            return
        _, msg = await self.handle_sect_rank(player)
        yield event.plain_result(msg)

    async def _sub_rank_contribution(self, player, event, args):
        if not self.rank_mgr:
            yield event.plain_result("❌ 排行功能不可用！")
            return
        _, msg = await self.handle_sect_contribution_rank(player)
        yield event.plain_result(msg)

    async def handle_sect_rank(self, player: Player) -> tuple[bool, str]:
        """Sect ranking (by construction scale), delegated to RankingManager.

        Called by ``_sub_rank`` with the player already injected (the
        dispatcher entry is guarded by @player_required).

        Args:
            player: The requesting player.

        Returns:
            (success, msg) from ``RankingManager.get_sect_ranking``.
        """
        return await self.rank_mgr.get_sect_ranking()

    async def handle_sect_contribution_rank(self, player: Player) -> tuple[bool, str]:
        """Sect contribution ranking for the player's current sect.

        Called by ``_sub_rank_contribution`` with the player already injected;
        the player-existence branch is unreachable here (@player_required
        guards the dispatcher), so only the sect-membership rejection stays.

        Args:
            player: The requesting player; ``sect_id`` decides the ranking
                scope.

        Returns:
            (success, msg); players without a sect get a rejection message.
        """
        if not player.sect_id or player.sect_id == 0:
            return False, "❌ 你尚未加入任何宗门，无法查看宗门贡献排行。"
        return await self.rank_mgr.get_contribution_ranking(player.sect_id)

    # ===== 悬赏子命令组（宗门悬赏独立入口，scope="sect"） =====

    async def _sub_bounty(self, player, event, args):
        """宗门 悬赏 [接取 <编号>|进度|完成|放弃]：仅本宗专属悬赏，与全局悬赏完全分流。"""
        if not self.bounty_mgr:
            yield event.plain_result("❌ 悬赏功能不可用！")
            return
        if not getattr(player, "sect_id", 0):
            yield event.plain_result(
                "❌ 你还未加入宗门！加入宗门后可使用「宗门 悬赏」。"
            )
            return

        action = args[0] if args else ""
        if action:
            result = await render_bounty_action(
                self.bounty_mgr, player, action, args[1:], "sect"
            )
            if result is None:
                yield event.plain_result(
                    f"❌ 未识别的悬赏操作「{action}」。可用：接取 <编号>｜进度｜完成｜放弃"
                )
                return
            _, msg = result
            yield event.plain_result(msg)
        else:
            msg = await render_bounty_list(self.bounty_mgr, player, "sect")
            yield event.plain_result(msg)

    # ===== 商店子命令组（宗门藏宝阁，贡献点结算） =====

    async def _sub_shop(self, player, event, args):
        """宗门 商店 [购买 <名称>]：查看本宗商店或以贡献点购买商品。"""
        action = args[0] if args else ""
        if action == "购买":
            if len(args) < 2:
                yield event.plain_result(
                    "❌ 请指定要购买的商品，例如：/宗门 商店 购买 青云天剑"
                )
                return
            success, msg = await self.sect_mgr.buy_sect_shop_item(
                event.get_sender_id(), " ".join(args[1:])
            )
        elif action:
            yield event.plain_result(
                f"❌ 未识别的商店操作「{action}」。可用：购买 <名称>"
            )
            return
        else:
            success, msg = await self.sect_mgr.get_sect_shop_info(event.get_sender_id())
        yield event.plain_result(msg)

    async def handle_create_sect(self, event: AstrMessageEvent, name: str):
        """创建宗门"""
        user_id = event.get_sender_id()
        busy_msg = await self.busy_state.assert_idle(user_id)
        if busy_msg:
            yield event.plain_result(busy_msg)
            return
        success, msg = await self.sect_mgr.create_sect(user_id, name)
        yield event.plain_result(msg)

    async def handle_join_sect(self, event: AstrMessageEvent, name: str):
        """加入宗门"""
        user_id = event.get_sender_id()
        busy_msg = await self.busy_state.assert_idle(user_id)
        if busy_msg:
            yield event.plain_result(busy_msg)
            return
        success, msg = await self.sect_mgr.join_sect(user_id, name)
        yield event.plain_result(msg)

    async def handle_leave_sect(self, event: AstrMessageEvent):
        """退出宗门"""
        user_id = event.get_sender_id()
        busy_msg = await self.busy_state.assert_idle(user_id)
        if busy_msg:
            yield event.plain_result(busy_msg)
            return
        success, msg = await self.sect_mgr.leave_sect(user_id)
        yield event.plain_result(msg)

    async def handle_my_sect(self, event: AstrMessageEvent):
        """我的宗门"""
        user_id = event.get_sender_id()
        success, msg, _ = await self.sect_mgr.get_sect_info(user_id)
        yield event.plain_result(msg)

    async def handle_sect_list(self, event: AstrMessageEvent):
        """宗门列表"""
        success, msg = await self.sect_mgr.list_all_sects()
        yield event.plain_result(msg)

    async def handle_donate(self, event: AstrMessageEvent, amount: int):
        """宗门捐献"""
        user_id = event.get_sender_id()
        busy_msg = await self.busy_state.assert_idle(user_id)
        if busy_msg:
            yield event.plain_result(busy_msg)
            return
        success, msg = await self.sect_mgr.donate_to_sect(user_id, amount)
        yield event.plain_result(msg)

    async def handle_kick_member(
        self, event: AstrMessageEvent, target: str
    ):  # target 可能是 at 或者是 id
        """踢出宗门成员"""
        user_id = event.get_sender_id()
        # 处理可能的 At 对象，获取目标 user_id
        # 这里简单假设传入的是纯数字字符串或者包含在 At 中
        # AstrBot 的 At 解析通常在 filter 或者 message chain 中
        # 这里简化处理，假设用户输入的是 user_id 或者是通过 At 获取到的

        # 实际 AstrBot 开发中，如果是指令参数带 At，通常需要解析 metadata 或者 message chain
        # 暂时只支持纯 ID 或依靠 AstrBot 的参数解析

        # 尝试从 message chain 中获取 at
        target_id = None
        for component in event.message_obj.message:
            if isinstance(component, At):
                target_id = str(component.qq)  # 假设是 QQ 适配器
                break

        if not target_id:
            # 尝试直接解析 text 参数
            if target.isdigit():
                target_id = target

        if not target_id:
            yield event.plain_result("❌ 请指定要踢出的成员（At或输入ID）")
            return

        success, msg = await self.sect_mgr.kick_member(user_id, target_id)
        yield event.plain_result(msg)

    async def handle_transfer(self, event: AstrMessageEvent, target: str):
        """宗主传位"""
        user_id = event.get_sender_id()
        target_id = None
        for component in event.message_obj.message:
            if isinstance(component, At):
                target_id = str(component.qq)
                break

        if not target_id and target.isdigit():
            target_id = target

        if not target_id:
            yield event.plain_result("❌ 请指定传位目标（At或输入ID）")
            return

        success, msg = await self.sect_mgr.transfer_ownership(user_id, target_id)
        yield event.plain_result(msg)

    async def handle_position_change(
        self, event: AstrMessageEvent, target: str, position: int
    ):
        """职位变更"""
        user_id = event.get_sender_id()
        target_id = None
        for component in event.message_obj.message:
            if isinstance(component, At):
                target_id = str(component.qq)
                break

        if not target_id and target.isdigit():
            target_id = target

        if not target_id:
            yield event.plain_result("❌ 请指定目标（At或输入ID）")
            return

        success, msg = await self.sect_mgr.change_position(user_id, target_id, position)
        yield event.plain_result(msg)

    async def handle_sect_task(self, event: AstrMessageEvent):
        """执行宗门任务"""
        user_id = event.get_sender_id()
        success, msg = await self.sect_mgr.perform_sect_task(user_id)
        yield event.plain_result(msg)

    async def _get_busy_message(self, user_id: str) -> str | None:
        """Return a busy-state notice for the sender, or None when idle."""
        return await self.busy_state.assert_idle(user_id)

    async def handle_sect_elixir(self, event: AstrMessageEvent, action: str = ""):
        """宗门丹房（查看状态/领取丹药，仅领取分支做忙碌拦截）"""
        user_id = event.get_sender_id()
        if (action or "").strip() == "领取":
            busy_msg = await self._get_busy_message(user_id)
            if busy_msg:
                yield event.plain_result(busy_msg)
                return
            success, msg = await self.sect_mgr.claim_elixir(user_id)
        else:
            success, msg = await self.sect_mgr.get_elixir_room_status(user_id)
        yield event.plain_result(msg)

    async def handle_sect_construction(
        self, event: AstrMessageEvent, building: str = ""
    ):
        """宗门建设（查看建筑状态/升级建筑，仅升级分支做忙碌拦截）"""
        user_id = event.get_sender_id()
        if (building or "").strip():
            busy_msg = await self._get_busy_message(user_id)
            if busy_msg:
                yield event.plain_result(busy_msg)
                return
            success, msg = await self.sect_mgr.upgrade_building(user_id, building)
        else:
            success, msg = await self.sect_mgr.get_construction_status(user_id)
        yield event.plain_result(msg)

    async def handle_sect_mainbuff(self, event: AstrMessageEvent, skill_ref: str = ""):
        """镇派功法（查看/镶嵌镇派功法）"""
        busy_msg = await self._get_busy_message(event.get_sender_id())
        if busy_msg:
            yield event.plain_result(busy_msg)
            return
        user_id = event.get_sender_id()
        success, msg = await self.sect_mgr.manage_sect_buff(user_id, skill_ref)
        yield event.plain_result(msg)

    async def handle_sect_promote(self, event: AstrMessageEvent):
        """宗门晋升（贡献+境界双门槛校验）"""
        busy_msg = await self._get_busy_message(event.get_sender_id())
        if busy_msg:
            yield event.plain_result(busy_msg)
            return
        user_id = event.get_sender_id()
        success, msg = await self.sect_mgr.promote_position(user_id)
        yield event.plain_result(msg)

    async def handle_sect_treasury(self, event: AstrMessageEvent, item_ref: str = ""):
        """宗门宝库（查看传承/领取宝物心法，仅领取分支做忙碌拦截）"""
        user_id = event.get_sender_id()
        if (item_ref or "").strip():
            busy_msg = await self._get_busy_message(user_id)
            if busy_msg:
                yield event.plain_result(busy_msg)
                return
            success, msg = await self.sect_mgr.claim_treasure(user_id, item_ref)
        else:
            success, msg = await self.sect_mgr.get_treasury_info(user_id)
        yield event.plain_result(msg)

    async def handle_master_task(self, event: AstrMessageEvent):
        """师承任务（查看当前任务链与阶段进度，查看类指令不做忙碌拦截）"""
        success, msg = await self.sect_mgr.get_master_task_status(event.get_sender_id())
        yield event.plain_result(msg)

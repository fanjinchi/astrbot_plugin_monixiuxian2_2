# handlers/rift_handlers.py
from astrbot.api.event import AstrMessageEvent

from ..data.data_manager import DataBase
from ..managers.rift_manager import RiftManager

# 「探索秘境」子命令用法提示（add-rift-encounters design D2）：分发失败或
# 缺参数时统一回复；迎战由 main.py 拦截直调 manager，不经过本分发，
# 但用法提示仍列出它，保证玩家能看到全部子命令
_EXPLORE_USAGE = (
    "❓ 用法：\n"
    "  探索秘境 <ID> → 进入秘境探险\n"
    "  探索秘境 破阵 <答案> → 回应当前古阵谜题\n"
    "  探索秘境 迎战 → 接受妖兽挑战\n"
    "  探索秘境 传承 → 应邀挑战传承之地"
)


class RiftHandlers:
    """Handlers for secret realm (秘境) commands: list, explore, and settle."""

    def __init__(self, db: DataBase, rift_mgr: RiftManager):
        self.db = db
        self.rift_mgr = rift_mgr

    async def handle_rift_list(self, event: AstrMessageEvent):
        """秘境列表"""
        success, msg = await self.rift_mgr.list_rifts(event.get_sender_id())
        yield event.plain_result(msg)

    async def handle_rift_explore(
        self, event: AstrMessageEvent, action: str = "", value: str = ""
    ):
        """Dispatch the 探索秘境 subcommands (add-rift-encounters design D2).

        A pure-digit action enters the rift with that ID (legacy behavior);
        破阵 answers the pending puzzle with ``value`` (a missing answer yields
        the usage hint without touching attempts); 传承 accepts the pending
        legacy challenge; anything else (including empty) yields the usage
        hint. 迎战 is intercepted in main.py (pve_won consumption lives at
        that layer) and never reaches this dispatch.
        """
        user_id = event.get_sender_id()
        action = str(action or "").strip()
        value = str(value or "").strip()

        if action.isdigit():
            success, msg = await self.rift_mgr.enter_rift(user_id, int(action))
            yield event.plain_result(msg)
            return
        if action == "破阵":
            if not value:
                # 未携带答案：只给用法提示，不调 answer_puzzle、不耗尝试次数
                yield event.plain_result(_EXPLORE_USAGE)
                return
            success, msg = await self.rift_mgr.answer_puzzle(user_id, value)
            yield event.plain_result(msg)
            return
        if action == "传承":
            success, msg = await self.rift_mgr.accept_legacy_challenge(user_id)
            yield event.plain_result(msg)
            return
        yield event.plain_result(_EXPLORE_USAGE)

    async def handle_rift_complete(self, event: AstrMessageEvent):
        """完成探索"""
        user_id = event.get_sender_id()
        success, msg, _ = await self.rift_mgr.finish_exploration(user_id)
        yield event.plain_result(msg)

    async def handle_rift_exit(self, event: AstrMessageEvent):
        """退出秘境"""
        user_id = event.get_sender_id()
        success, msg = await self.rift_mgr.exit_rift(user_id)
        yield event.plain_result(msg)

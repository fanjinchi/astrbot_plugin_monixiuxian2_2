# handlers/alchemy_handlers.py
from typing import TYPE_CHECKING

from astrbot.api.event import AstrMessageEvent

from ..data.data_manager import DataBase
from ..managers.alchemy_manager import AlchemyManager

if TYPE_CHECKING:
    from ..core.busy_state import BusyState


class AlchemyHandlers:
    """Handlers for alchemy (炼丹) commands: recipe list and pill crafting."""

    def __init__(
        self,
        db: DataBase,
        alchemy_mgr: AlchemyManager,
        busy_state: "BusyState",
    ):
        self.db = db
        self.alchemy_mgr = alchemy_mgr
        self.busy_state = busy_state

    async def handle_recipes(self, event: AstrMessageEvent):
        """丹药配方"""
        user_id = event.get_sender_id()
        success, msg = await self.alchemy_mgr.get_available_recipes(user_id)
        yield event.plain_result(msg)

    async def handle_craft(self, event: AstrMessageEvent, pill_id: int):
        """炼丹"""
        user_id = event.get_sender_id()

        # 检查玩家是否存在
        player = await self.db.get_player_by_id(user_id)
        if not player:
            yield event.plain_result("❌ 你还未踏入修仙之路！")
            return

        # 检查玩家状态
        busy_msg = await self.busy_state.assert_idle(
            user_id, template="❌ 你当前正{status}，无法炼丹！"
        )
        if busy_msg:
            yield event.plain_result(busy_msg)
            return

        if not pill_id:
            yield event.plain_result("❌ 请输入丹药配方ID")
            return
        success, msg, _ = await self.alchemy_mgr.craft_pill(user_id, int(pill_id))
        yield event.plain_result(msg)

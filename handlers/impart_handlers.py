# handlers/impart_handlers.py
from astrbot.api.event import AstrMessageEvent

from ..data.data_manager import DataBase
from ..managers.impart_manager import ImpartManager


class ImpartHandlers:
    """Handlers for the impart (传承) system commands: legacy info and inheritance actions."""

    def __init__(self, db: DataBase, impart_mgr: ImpartManager):
        self.db = db
        self.impart_mgr = impart_mgr

    async def handle_impart_info(self, event: AstrMessageEvent):
        """传承信息"""
        user_id = event.get_sender_id()
        success, msg, _ = await self.impart_mgr.get_impart_info(user_id)
        yield event.plain_result(msg)

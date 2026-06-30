# handlers/gm_handler.py
# GM 命令处理器

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..core.gm_manager import GMManager

__all__ = ["GMHandler"]


class GMHandler:
    """GM 命令处理器 - 处理修仙GM 统一入口"""

    def __init__(
        self,
        db,
        gm_manager: GMManager,
    ):
        self.db = db
        self.gm_manager = gm_manager

    async def handle_gm(self, event: AstrMessageEvent, args: str = ""):
        """处理修仙GM <子命令> [目标] [参数]"""
        gm_user_id = str(event.get_sender_id())

        # 解析子命令和剩余参数
        parts = args.split(None, 1)
        sub_command = parts[0].strip() if parts else ""
        remaining = parts[1].strip() if len(parts) > 1 else ""

        try:
            _, message = await self.gm_manager.dispatch(
                gm_user_id, event, sub_command, remaining
            )
        except Exception as e:
            logger.error(f"【GMHandler】处理命令失败: {e}")
            message = f"❌ GM 命令执行失败：{e}"

        yield event.plain_result(message)

    async def handle_gm_help(self, event: AstrMessageEvent):
        """处理修仙GM帮助"""
        async for result in self.handle_gm(event, "帮助"):
            yield result

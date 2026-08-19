# handlers/sect_handlers.py
from astrbot.api.all import *
from astrbot.api.event import AstrMessageEvent

from ..data.data_manager import DataBase
from ..managers.sect_manager import SectManager
from ..models_extended import UserStatus


class SectHandlers:
    """Handlers for sect (宗门) commands: create, join, leave, donate, and sect info."""

    def __init__(self, db: DataBase, sect_mgr: SectManager):
        self.db = db
        self.sect_mgr = sect_mgr

    async def handle_create_sect(self, event: AstrMessageEvent, name: str):
        """创建宗门"""
        user_id = event.get_sender_id()
        user_cd = await self.db.ext.get_user_cd(user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 你当前正{current_status}，无法进行此操作！")
            return
        success, msg = await self.sect_mgr.create_sect(user_id, name)
        yield event.plain_result(msg)

    async def handle_join_sect(self, event: AstrMessageEvent, name: str):
        """加入宗门"""
        user_id = event.get_sender_id()
        user_cd = await self.db.ext.get_user_cd(user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 你当前正{current_status}，无法进行此操作！")
            return
        success, msg = await self.sect_mgr.join_sect(user_id, name)
        yield event.plain_result(msg)

    async def handle_leave_sect(self, event: AstrMessageEvent):
        """退出宗门"""
        user_id = event.get_sender_id()
        user_cd = await self.db.ext.get_user_cd(user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 你当前正{current_status}，无法进行此操作！")
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
        user_cd = await self.db.ext.get_user_cd(user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 你当前正{current_status}，无法进行此操作！")
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
        user_cd = await self.db.ext.get_user_cd(user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            return f"❌ 你当前正{current_status}，无法进行此操作！"
        return None

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

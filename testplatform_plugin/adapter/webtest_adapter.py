"""webtest 平台适配器：把测试消息接入 AstrBot 真实消息管线。

- 入站：``build_abm()`` 构造 AstrBotMessage（身份语义与真实平台一致：
  玩家键 = sender.user_id，群白名单键 = group.group_id），``commit_event``
  进事件队列，后续处理（filter/Handler/白名单/数据库/定时任务）与真实平台
  消息完全一致。
- 出站两条路都被捕获进测试平台可见消息流：
  1. Handler 回复：``WebTestMessageEvent.send()/send_streaming()``（respond
     管线最终调 event.send）。
  2. 主动消息/定时广播：重写 ``send_by_session()``（StarContext.send_message
     按 umo 路由到平台）。
- 会话标识仿 webchat 风格：私聊 ``webtest!{user_id}!{conversation_id}``、
  群聊 ``webtest!group!{group_id}``；出站按会话标识路由回对应会话，未知
  会话自动创建（system-created）。
"""

import asyncio
import json
import uuid
from collections.abc import Coroutine
from typing import Any

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import File, Image, Json, Plain, Record
from astrbot.api.platform import (
    AstrBotMessage,
    Group,
    MessageMember,
    MessageType,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)

from ..server.app_state import app_state

ADAPTER_CONFIG_TMPL: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 8765,
    "access_token": "",
    "default_players": [
        {"nickname": "测试玩家1", "user_id": "test_player_001"},
        {"nickname": "测试玩家2", "user_id": "test_player_002"},
    ],
}


def chain_to_text(message: MessageChain) -> tuple[str, list[dict]]:
    """MessageChain → (纯文本, rich 段列表)。

    Plain 拼接为纯文本；Image/File/Record/Json 等非文本段转为描述写入 rich。
    """
    text_parts: list[str] = []
    rich: list[dict] = []
    for comp in message.chain:
        if isinstance(comp, Plain):
            text_parts.append(comp.text)
        elif isinstance(comp, Image):
            desc = "[图片]"
            rich.append({"type": "image", "text": desc})
            text_parts.append(desc)
        elif isinstance(comp, File):
            desc = f"[文件 {getattr(comp, 'name', '') or '未知'}]"
            rich.append({"type": "file", "text": desc})
            text_parts.append(desc)
        elif isinstance(comp, Record):
            desc = "[语音]"
            rich.append({"type": "record", "text": desc})
            text_parts.append(desc)
        elif isinstance(comp, Json):
            data = json.dumps(comp.data, ensure_ascii=False)
            rich.append({"type": "json", "text": data})
            text_parts.append(f"[Json]{data}")
        else:
            desc = f"[{getattr(comp, 'type', 'unknown')}]"
            rich.append({"type": getattr(comp, "type", "unknown"), "text": desc})
            text_parts.append(desc)
    return "".join(text_parts), rich


class WebTestMessageEvent(AstrMessageEvent):
    """webtest 事件：重写 send/send_streaming 捕获出站消息进测试平台 feed。"""

    def __init__(self, message_str, message_obj, platform_meta, session_id) -> None:
        super().__init__(message_str, message_obj, platform_meta, session_id)

    async def _capture(
        self, message: MessageChain | None, streaming: bool = False
    ) -> None:
        if message is None:
            return
        try:
            conv_id = await app_state.resolve_session(self.session_id)
            text, rich = chain_to_text(message)
            if text or rich:
                await app_state.capture_outbound(
                    conv_id, text, rich, streaming=streaming
                )
        except Exception as exc:  # 捕获失败不应阻断回复管线
            logger.warning(f"【测试平台】出站消息捕获失败: {exc}")

    async def send(self, message: MessageChain | None) -> None:
        await self._capture(message)
        await super().send(message)

    async def send_streaming(self, generator, use_fallback: bool = False) -> None:
        """流式分片：逐片追加进 feed（尽力呈现，不阻塞管线）。"""
        async for chain in generator:
            if getattr(chain, "type", None) == "audio_chunk":
                continue
            await self._capture(chain, streaming=True)
        await super().send_streaming(generator, use_fallback)


@register_platform_adapter(
    "webtest",
    "网页端测试平台适配器：模拟玩家消息走真实 AstrBot 管线，提供网页/API/CLI 双向可见消息流与自动化测试。",
    default_config_tmpl=ADAPTER_CONFIG_TMPL,
    adapter_display_name="网页测试平台 (webtest)",
)
class WebTestAdapter(Platform):
    """webtest 平台适配器。

    在 AstrBot Dashboard 平台设置中启用后，``run()`` 启动内置 aiohttp Web
    服务（REST + WebSocket + 静态前端），直至 ``terminate()`` 关闭。
    """

    def __init__(
        self,
        platform_config: dict,
        platform_settings: dict,
        event_queue: asyncio.Queue,
    ) -> None:
        super().__init__(platform_config, event_queue)
        self.settings = platform_settings
        self.metadata = PlatformMetadata(
            name="webtest",
            description="网页端测试平台",
            id="webtest",
            support_proactive_message=True,
        )
        self._shutdown_event = asyncio.Event()
        app_state.merge_platform_config(platform_config)
        app_state.register_adapter(self)
        logger.info(
            "【测试平台】webtest 适配器已实例化（数据目录: %s）", app_state.data_dir
        )

    def meta(self) -> PlatformMetadata:
        return self.metadata

    def create_event(self, message: AstrBotMessage) -> WebTestMessageEvent:
        """构造事件对象（重写 send 捕获回复）。"""
        return WebTestMessageEvent(
            message_str=message.message_str,
            message_obj=message,
            platform_meta=self.meta(),
            session_id=message.session_id,
        )

    def build_abm(
        self,
        conversation: dict,
        player: dict,
        text: str,
        players: list[dict] | None = None,
    ) -> AstrBotMessage:
        """构造 AstrBotMessage（身份语义与真实平台一致）。

        Args:
            conversation: 会话记录（kind/group_id/name/id）。
            player: 玩家记录（nickname/user_id）。
            text: 消息纯文本。
            players: 会话全部玩家（群聊时填入 Group.members）。
        """
        abm = AstrBotMessage()
        abm.self_id = "webtest"
        abm.sender = MessageMember(
            user_id=player["user_id"], nickname=player["nickname"]
        )
        abm.message = [Plain(text)]
        abm.message_str = text
        abm.raw_message = {"platform": "webtest", "conversation_id": conversation["id"]}
        abm.message_id = uuid.uuid4().hex
        if conversation["kind"] == "group":
            abm.type = MessageType.GROUP_MESSAGE
            abm.group = Group(
                group_id=str(conversation["group_id"]),
                group_name=conversation["name"],
                members=[
                    MessageMember(user_id=p["user_id"], nickname=p["nickname"])
                    for p in (players or [])
                ],
            )
            abm.session_id = f"webtest!group!{conversation['group_id']}"
        else:
            abm.type = MessageType.FRIEND_MESSAGE
            abm.session_id = f"webtest!{player['user_id']}!{conversation['id']}"
        return abm

    def run(self) -> Coroutine[Any, Any, None]:
        """启动 Web 服务并挂起直至关闭事件。"""

        async def _run() -> None:
            try:
                await app_state.ensure_db()
                await app_state.start_server()
                await self._shutdown_event.wait()
            finally:
                await app_state.stop_server()

        return _run()

    async def terminate(self) -> None:
        """关闭 Web 服务并释放数据库连接。"""
        self._shutdown_event.set()
        try:
            await app_state.shutdown()
        except Exception as exc:
            logger.warning(f"【测试平台】关闭清理失败: {exc}")

    async def send_by_session(self, session, message_chain: MessageChain) -> None:
        """主动消息/定时广播路由：按会话标识路由回模拟会话（未知自动创建）。"""
        try:
            conv_id = await app_state.resolve_session(session.session_id)
            text, rich = chain_to_text(message_chain)
            if text or rich:
                await app_state.capture_outbound(conv_id, text, rich)
        except Exception as exc:
            logger.warning(f"【测试平台】主动消息路由失败: {exc}")
        await super().send_by_session(session, message_chain)

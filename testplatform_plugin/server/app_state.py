"""全局共享状态：配置、数据库、适配器引用、WebSocket 客户端与消息注入入口。

模块级单例 ``app_state``，被 adapter（消息出入站）、server（REST/WS）与
main（插件生命周期）共用，避免循环 import：
adapter → app_state；server → app_state；main → adapter + app_state。
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from ..cases import runner as case_runner
from ..storage.db import Database

logger = logging.getLogger("astrbot")

DEFAULTS: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 8765,
    "access_token": "",
    "default_players": [
        {"nickname": "测试玩家1", "user_id": "test_player_001"},
        {"nickname": "测试玩家2", "user_id": "test_player_002"},
    ],
}

CONFIG_KEYS = ("host", "port", "access_token", "default_players")


class AppState:
    """测试平台共享状态（单例）。"""

    def __init__(self) -> None:
        self.plugin_config: dict | None = None
        self.data_dir: Path | None = None
        self.db: Database | None = None
        self.adapter: Any = None  # WebTestAdapter 实例（AstrBot 创建后注册）
        self._resolved: dict[str, Any] = dict(DEFAULTS)
        self.ws_clients: set[Any] = set()
        self._server_runner: Any = None
        self._server_site: Any = None
        self._start_lock = asyncio.Lock()

    # ---------- 生命周期 ----------

    def setup(self, plugin_config: dict, data_dir: Path) -> None:
        """插件加载时调用：记录插件配置与数据目录。"""
        self.plugin_config = plugin_config or {}
        self.data_dir = data_dir
        self._resolve_config({})

    def merge_platform_config(self, platform_config: dict | None) -> None:
        """适配器实例化时调用：Dashboard 平台配置覆盖插件配置。"""
        self._resolve_config(platform_config or {})

    def _resolve_config(self, platform_config: dict) -> None:
        resolved: dict[str, Any] = {}
        for key in CONFIG_KEYS:
            if key in platform_config and platform_config[key] not in (None, ""):
                resolved[key] = platform_config[key]
            elif isinstance(self.plugin_config, dict) and self.plugin_config.get(
                key
            ) not in (None, ""):
                resolved[key] = self.plugin_config[key]
            else:
                resolved[key] = DEFAULTS[key]
        if not resolved.get("default_players"):
            resolved["default_players"] = DEFAULTS["default_players"]
        self._resolved = resolved

    @property
    def config(self) -> dict[str, Any]:
        return dict(self._resolved)

    @property
    def cases_dir(self) -> Path:
        assert self.data_dir is not None, "app_state 未初始化"
        path = self.data_dir / "cases"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def register_adapter(self, adapter: Any) -> None:
        """适配器实例化时注册自身引用（注入消息走 commit_event）。"""
        self.adapter = adapter

    async def ensure_db(self) -> Database:
        """取数据库实例；连接缺失/失效时（重）连接，并确保数据目录存在。"""
        if self.db is None:
            assert self.data_dir is not None, "app_state 未初始化"
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.db = Database(str(self.data_dir / "test_platform.db"))
        if self.db.conn is None:
            await self.db.connect()
        return self.db

    # ---------- 服务器生命周期（adapter.run 驱动） ----------

    async def start_server(self) -> None:
        """启动 aiohttp 服务（幂等）。"""
        from .app import build_app

        async with self._start_lock:
            if self._server_site is not None:
                return
            from aiohttp import web

            cfg = self.config
            app = build_app(self)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, cfg["host"], int(cfg["port"]))
            await site.start()
            self._server_runner = runner
            self._server_site = site
            logger.info(
                "【测试平台】Web 服务已启动: http://%s:%s", cfg["host"], cfg["port"]
            )

    async def stop_server(self) -> None:
        if self._server_runner is not None:
            await self._server_runner.cleanup()
            self._server_runner = None
            self._server_site = None

    async def shutdown(self) -> None:
        """停服并关闭数据库（适配器 terminate 时调用，热重载不残留连接）。"""
        await self.stop_server()
        if self.db is not None:
            await self.db.close()
            self.db = None

    # ---------- 消息出入站 ----------

    async def inject_message(
        self, conversation_id: int, player_user_id: str, text: str
    ) -> dict:
        """注入玩家消息：构造 AstrBotMessage → commit_event 进真实管线 → 持久化。

        Raises:
            RuntimeError: 适配器未注册（平台未启用）。
            ValueError: 会话不存在/已归档/玩家不在会话中。
        """
        if self.adapter is None:
            raise RuntimeError(
                "webtest 适配器未注册——请在 AstrBot Dashboard 启用测试平台适配器"
            )
        db = await self.ensure_db()
        conv = await db.get_conversation(conversation_id)
        if conv is None:
            raise ValueError("会话不存在")
        if conv["archived"]:
            raise ValueError("会话已归档，不能注入消息")
        player = await db.get_player(conversation_id, player_user_id)
        if player is None:
            raise ValueError(
                f"玩家 {player_user_id!r} 不在该会话中；可选玩家："
                + ", ".join(p["user_id"] for p in conv["players"])
            )
        if not isinstance(text, str) or not text.strip():
            raise ValueError("消息文本不能为空")
        msg = await db.add_message(conversation_id, "in", player["user_id"], text)
        abm = self.adapter.build_abm(conv, player, text)
        self.adapter.commit_event(self.adapter.create_event(abm))
        return msg

    async def resolve_session(self, session_id: str) -> int:
        """出站路由：把 ``webtest!...`` 会话标识解析为会话 id；未知会话自动创建。"""
        db = await self.ensure_db()
        parts = session_id.split("!")
        if len(parts) == 3 and parts[0] == "webtest":
            if parts[1] == "group":
                group_id = parts[2]
                conv = await db.latest_group_conversation(group_id)
                if conv is None:
                    conv = await db.create_conversation(
                        "group",
                        group_id=group_id,
                        name=f"群 {group_id}",
                        system_created=True,
                    )
                return conv["id"]
            # 私聊：webtest!{user_id}!{conversation_id}
            user_id, conv_uid = parts[1], parts[2]
            try:
                conv = await db.get_conversation(int(conv_uid))
            except (TypeError, ValueError):
                conv = None
            if conv is None or conv["kind"] != "private":
                conv = await db.latest_private_conversation_for_user(user_id)
            if conv is None:
                conv = await db.create_conversation(
                    "private", name=f"私聊 {user_id}", system_created=True
                )
                await db.add_player(conv["id"], user_id, user_id)
            return conv["id"]
        # 未知格式：按原文查找/创建私聊
        conv = await db.latest_private_conversation_for_user(session_id)
        if conv is None:
            conv = await db.create_conversation(
                "private", name=f"私聊 {session_id}", system_created=True
            )
            await db.add_player(conv["id"], session_id, session_id)
        return conv["id"]

    async def capture_outbound(
        self, conversation_id: int, text: str, rich: Any = None, streaming: bool = False
    ) -> dict:
        """捕获机器人出站消息：持久化 + 推 WebSocket。"""
        db = await self.ensure_db()
        msg = await db.add_message(conversation_id, "out", "bot", text or "", rich)
        await self.broadcast(
            {
                "type": "message",
                "conversation_id": conversation_id,
                "message": msg,
            }
        )
        return msg

    # ---------- WebSocket ----------

    def add_ws(self, ws: Any) -> None:
        self.ws_clients.add(ws)

    def remove_ws(self, ws: Any) -> None:
        self.ws_clients.discard(ws)

    async def broadcast(self, event: dict) -> None:
        """向所有 WebSocket 客户端广播事件（静默丢弃断开的连接）。"""
        if not self.ws_clients:
            return
        payload = json.dumps(event, ensure_ascii=False)
        dead = []
        for ws in list(self.ws_clients):
            try:
                await ws.send_str(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove_ws(ws)

    # ---------- 用例运行 ----------

    async def run_case(self, case_name: str) -> dict:
        """运行用例（后台任务调用），返回 run 记录。"""
        db = await self.ensure_db()
        return await case_runner.run_case(
            case_name, cases_dir=self.cases_dir, db=db, inject=self.inject_message
        )


app_state = AppState()

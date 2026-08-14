"""aiohttp Web 应用：REST API + WebSocket + 静态前端。

- 令牌中间件：配置 access_token 后，所有 ``/api/*`` 与 ``/ws`` 必须携带令牌
  （``Authorization: Bearer <token>`` 或 ``?token=`` 查询参数），否则 401。
- REST 契约见 design.md D3 / tasks 8.4；错误统一 ``{"error": ...}``。
"""

import json
from pathlib import Path

from aiohttp import web

from ..cases import loader as case_loader

WEBUI_DIR = Path(__file__).resolve().parent.parent / "webui"


def _json_response(data, status: int = 200) -> web.Response:
    return web.json_response(
        data, status=status, dumps=lambda o: json.dumps(o, ensure_ascii=False)
    )


def _error(message: str, status: int = 400) -> web.Response:
    return _json_response({"error": message}, status=status)


def _token_middleware(state):
    """访问令牌校验中间件。"""

    @web.middleware
    async def middleware(request: web.Request, handler):
        token = state.config["access_token"]
        if token:
            path = request.path
            if path.startswith("/api/") or path == "/ws":
                provided = (
                    request.query.get("token")
                    or request.headers.get("X-Access-Token")
                    or (
                        request.headers.get("Authorization", "")
                        .removeprefix("Bearer ")
                        .strip()
                        if request.headers.get("Authorization", "").startswith(
                            "Bearer "
                        )
                        else ""
                    )
                )
                if provided != token:
                    return _error("unauthorized", 401)
        return await handler(request)

    return middleware


def build_app(state) -> web.Application:
    """构建 aiohttp 应用（路由见模块 docstring）。"""
    app = web.Application(middlewares=[_token_middleware(state)])
    app["state"] = state

    async def index(request: web.Request) -> web.Response:
        return web.FileResponse(WEBUI_DIR / "index.html")

    app.router.add_get("/", index)
    app.router.add_static("/static/", WEBUI_DIR)

    # ---------- 会话 ----------

    async def list_conversations(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        return _json_response({"conversations": await db.list_conversations()})

    async def create_conversation(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        body = await request.json()
        kind = body.get("kind", "private")
        if kind not in ("private", "group"):
            return _error("kind 只能是 private|group")
        members = body.get("members") or []
        if kind == "private" and not members:
            defaults = state.config.get("default_players") or []
            if not defaults:
                return _error("私聊会话至少需要一个成员")
            members = [defaults[0]]
        conv = await db.create_conversation(
            kind=kind,
            group_id=body.get("group_id"),
            name=body.get("name")
            or (
                f"群 {body.get('group_id')}"
                if kind == "group"
                else members[0]["nickname"]
            ),
        )
        for member in members:
            await db.add_player(
                conv["id"], member.get("nickname", member["user_id"]), member["user_id"]
            )
        conv = await db.get_conversation(conv["id"])
        await state.broadcast({"type": "conversations"})
        return _json_response(conv, 201)

    async def patch_conversation(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        conv_id = int(request.match_info["id"])
        body = await request.json()
        conv = await db.update_conversation(
            conv_id,
            archived=body.get("archived"),
            name=body.get("name"),
        )
        if conv is None:
            return _error("会话不存在", 404)
        await state.broadcast({"type": "conversations"})
        return _json_response(conv)

    async def delete_conversation(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        conv_id = int(request.match_info["id"])
        if not await db.delete_conversation(conv_id):
            return _error("会话不存在", 404)
        await state.broadcast({"type": "conversations"})
        return _json_response({"ok": True})

    async def get_messages(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        conv_id = int(request.match_info["id"])
        if await db.get_conversation(conv_id) is None:
            return _error("会话不存在", 404)
        after = int(request.query.get("after", "0") or 0)
        limit = min(int(request.query.get("limit", "500") or 500), 10000)
        messages = await db.list_messages(conv_id, after=after, limit=limit)
        annotations = await db.list_annotations(conv_id)
        ann_map = {a["message_id"]: a for a in annotations}
        for msg in messages:
            msg["annotation"] = ann_map.get(msg["id"])
        return _json_response({"messages": messages})

    async def post_message(request: web.Request) -> web.Response:
        conv_id = int(request.match_info["id"])
        body = await request.json()
        try:
            msg = await state.inject_message(
                conv_id, body.get("sender", ""), body.get("text", "")
            )
        except ValueError as exc:
            return _error(str(exc))
        except RuntimeError as exc:
            return _error(str(exc), 503)
        await state.broadcast(
            {"type": "message", "conversation_id": conv_id, "message": msg}
        )
        return _json_response(msg, 201)

    async def add_player(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        conv_id = int(request.match_info["id"])
        if await db.get_conversation(conv_id) is None:
            return _error("会话不存在", 404)
        body = await request.json()
        if not body.get("user_id"):
            return _error("user_id 必填")
        player = await db.add_player(
            conv_id, body.get("nickname", body["user_id"]), body["user_id"]
        )
        await state.broadcast({"type": "conversations"})
        return _json_response(player, 201)

    # ---------- 批注 ----------

    async def get_annotation(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        mid = int(request.match_info["mid"])
        ann = await db.get_annotation(mid)
        if ann is None:
            return _error("无批注", 404)
        return _json_response({"annotation": ann})

    async def post_annotation(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        mid = int(request.match_info["mid"])
        body = await request.json()
        text = body.get("text", "")
        if not text.strip():
            return _error("批注文本不能为空")
        existing = await db.get_annotation(mid)
        ann = (
            await db.update_annotation(mid, text)
            if existing
            else await db.add_annotation(mid, text)
        )
        await state.broadcast({"type": "annotation", "message_id": mid})
        return _json_response(ann, 201 if not existing else 200)

    async def delete_annotation(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        mid = int(request.match_info["mid"])
        if not await db.delete_annotation(mid):
            return _error("无批注", 404)
        await state.broadcast({"type": "annotation", "message_id": mid})
        return _json_response({"ok": True})

    # ---------- 玩家 ----------

    async def get_players(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        all_players = await db.list_players()
        defaults = state.config.get("default_players") or []
        return _json_response({"default_players": defaults, "players": all_players})

    # ---------- 用例 ----------

    async def list_cases(request: web.Request) -> web.Response:
        cases, errors = case_loader.load_cases_dir(state.cases_dir)
        return _json_response({"cases": cases, "errors": errors})

    async def create_case(request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        name = (body.get("name") or "").strip()
        if not name:
            return _error("name 必填")
        if body.get("content") is not None:
            data = body["content"]
            data["name"] = name
        else:
            data = case_loader.new_case_template(name)
        try:
            case_loader.save_case(state.cases_dir, data)
        except ValueError as exc:
            return _error(str(exc))
        return _json_response(data, 201)

    async def get_case(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        try:
            case = case_loader.load_case_file(state.cases_dir / f"{name}.json")
        except ValueError as exc:
            return _error(str(exc), 404)
        return _json_response(case)

    async def put_case(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        body = await request.json()
        data = body.get("content")
        if not isinstance(data, dict):
            return _error("content 必填（用例对象）")
        data["name"] = name
        try:
            case_loader.save_case(state.cases_dir, data)
        except ValueError as exc:
            return _error(str(exc))  # 校验失败不保存
        return _json_response(data)

    async def delete_case(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if not case_loader.delete_case(state.cases_dir, name):
            return _error("用例不存在", 404)
        return _json_response({"ok": True})

    async def run_case(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if not (state.cases_dir / f"{name}.json").exists():
            return _error("用例不存在", 404)
        try:
            run = await state.run_case(name)
        except Exception as exc:  # 运行期异常不炸接口
            return _error(f"运行失败: {exc}", 500)
        await state.broadcast({"type": "case_runs", "case_name": name})
        return _json_response(run, 201)

    async def list_case_runs(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        runs = await db.list_case_runs(request.match_info["name"])
        return _json_response({"runs": runs})

    async def get_run(request: web.Request) -> web.Response:
        db = await state.ensure_db()
        run = await db.get_case_run(int(request.match_info["run_id"]))
        if run is None:
            return _error("运行记录不存在", 404)
        return _json_response(run)

    async def status(request: web.Request) -> web.Response:
        cfg = state.config
        return _json_response(
            {
                "adapter_ready": state.adapter is not None,
                "host": cfg["host"],
                "port": cfg["port"],
                "token_set": bool(cfg["access_token"]),
                "players": cfg.get("default_players", []),
            }
        )

    # ---------- WebSocket ----------

    async def ws_handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        state.add_ws(ws)
        db = await state.ensure_db()
        try:
            # 连接即推全量快照：会话列表 + 玩家
            await ws.send_str(
                json.dumps(
                    {
                        "type": "snapshot",
                        "conversations": await db.list_conversations(),
                        "players": await db.list_players(),
                    },
                    ensure_ascii=False,
                )
            )
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                    except ValueError:
                        continue
                    if payload.get("type") == "open":
                        conv_id = int(payload.get("conversation_id", 0))
                        messages = await db.list_messages(conv_id, after=0, limit=10000)
                        ann_map = {
                            a["message_id"]: a
                            for a in await db.list_annotations(conv_id)
                        }
                        for m in messages:
                            m["annotation"] = ann_map.get(m["id"])
                        await ws.send_str(
                            json.dumps(
                                {
                                    "type": "messages",
                                    "conversation_id": conv_id,
                                    "messages": messages,
                                },
                                ensure_ascii=False,
                            )
                        )
                elif msg.type == web.WSMsgType.ERROR:
                    break
        finally:
            state.remove_ws(ws)
        return ws

    # 路由注册
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/conversations", list_conversations)
    app.router.add_post("/api/conversations", create_conversation)
    app.router.add_patch("/api/conversations/{id}", patch_conversation)
    app.router.add_delete("/api/conversations/{id}", delete_conversation)
    app.router.add_get("/api/conversations/{id}/messages", get_messages)
    app.router.add_post("/api/conversations/{id}/messages", post_message)
    app.router.add_post("/api/conversations/{id}/players", add_player)
    app.router.add_get("/api/players", get_players)
    app.router.add_get("/api/messages/{mid}/annotation", get_annotation)
    app.router.add_post("/api/messages/{mid}/annotation", post_annotation)
    app.router.add_patch("/api/messages/{mid}/annotation", post_annotation)
    app.router.add_delete("/api/messages/{mid}/annotation", delete_annotation)
    app.router.add_get("/api/cases", list_cases)
    app.router.add_post("/api/cases", create_case)
    app.router.add_get("/api/cases/{name}", get_case)
    app.router.add_put("/api/cases/{name}", put_case)
    app.router.add_delete("/api/cases/{name}", delete_case)
    app.router.add_post("/api/cases/{name}/runs", run_case)
    app.router.add_get("/api/cases/{name}/runs", list_case_runs)
    app.router.add_get("/api/runs/{run_id}", get_run)
    app.router.add_get("/ws", ws_handler)
    return app

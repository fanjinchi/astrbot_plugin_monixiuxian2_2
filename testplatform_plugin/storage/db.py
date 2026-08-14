"""aiosqlite 数据访问层（测试平台全部持久化）。

Schema:
- conversations(id, kind[private|group], group_id, name, archived, system_created, created_at)
- players(id, conversation_id, nickname, user_id)  UNIQUE(conversation_id, user_id)
- messages(id, conversation_id, direction[in|out|system], sender, text, rich, created_at)
- annotations(id, message_id, text, updated_at)
- case_runs(id, case_name, run_index, status, conversation_id,
            steps_result, case_snapshot, run_messages, started_at, finished_at)

id 均为 INTEGER 自增主键，插入顺序即时间序（消息轮询的 after 游标直接用 id）。
"""

import asyncio
import json
import time
from typing import Any

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    group_id TEXT,
    name TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    system_created INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    nickname TEXT,
    user_id TEXT NOT NULL,
    UNIQUE(conversation_id, user_id)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    sender TEXT,
    text TEXT,
    rich TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS case_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_name TEXT NOT NULL,
    run_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    conversation_id INTEGER,
    steps_result TEXT,
    case_snapshot TEXT,
    run_messages TEXT,
    started_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_annotations_msg ON annotations(message_id);
"""


def _jloads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _jumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


class Database:
    """aiosqlite 封装：单连接 + 写锁，所有方法 async。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """打开连接并幂等建表。"""
        if self.conn is not None:
            return
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(_SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    # ---------- 会话 ----------

    async def create_conversation(
        self,
        kind: str,
        group_id: str | None = None,
        name: str | None = None,
        archived: bool = False,
        system_created: bool = False,
    ) -> dict:
        """创建会话并返回其记录。"""
        assert kind in ("private", "group")
        async with self._lock:
            cur = await self.conn.execute(
                "INSERT INTO conversations(kind, group_id, name, archived, system_created, created_at)"
                " VALUES(?, ?, ?, ?, ?, ?)",
                (
                    kind,
                    group_id,
                    name,
                    1 if archived else 0,
                    1 if system_created else 0,
                    time.time(),
                ),
            )
            await self.conn.commit()
            conv_id = cur.lastrowid
        return await self.get_conversation(conv_id)

    async def list_conversations(self) -> list[dict]:
        """列出全部会话（含消息数与玩家列表）。"""
        rows = await self.conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count"
            " FROM conversations c ORDER BY c.id DESC"
        )
        convs = [dict(r) for r in await rows.fetchall()]
        players = await self.list_players()
        for conv in convs:
            conv["players"] = [p for p in players if p["conversation_id"] == conv["id"]]
        return convs

    async def get_conversation(self, conv_id: int) -> dict | None:
        row = await self.conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count"
            " FROM conversations c WHERE c.id = ?",
            (conv_id,),
        )
        row = await row.fetchone()
        if row is None:
            return None
        conv = dict(row)
        conv["players"] = await self.list_players(conv_id)
        return conv

    async def update_conversation(
        self, conv_id: int, *, archived: bool | None = None, name: str | None = None
    ) -> dict | None:
        """更新会话（归档/改名），返回更新后的记录。"""
        sets, args = [], []
        if archived is not None:
            sets.append("archived = ?")
            args.append(1 if archived else 0)
        if name is not None:
            sets.append("name = ?")
            args.append(name)
        if not sets:
            return await self.get_conversation(conv_id)
        args.append(conv_id)
        async with self._lock:
            await self.conn.execute(
                f"UPDATE conversations SET {', '.join(sets)} WHERE id = ?", args
            )
            await self.conn.commit()
        return await self.get_conversation(conv_id)

    async def delete_conversation(self, conv_id: int) -> bool:
        """删除会话，级联删除其消息、批注与玩家。"""
        async with self._lock:
            cur = await self.conn.execute(
                "DELETE FROM conversations WHERE id = ?", (conv_id,)
            )
            # 注意顺序：批注必须先于消息删除（子查询依赖消息表）
            await self.conn.execute(
                "DELETE FROM annotations WHERE message_id IN"
                " (SELECT id FROM messages WHERE conversation_id = ?)",
                (conv_id,),
            )
            await self.conn.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
            )
            await self.conn.execute(
                "DELETE FROM players WHERE conversation_id = ?", (conv_id,)
            )
            await self.conn.commit()
        return cur.rowcount > 0

    async def latest_private_conversation_for_user(
        self, user_id: str, include_archived: bool = False
    ) -> dict | None:
        """按玩家 user_id 找最近的非归档私聊会话（出站消息路由用）。"""
        archived_filter = "" if include_archived else "AND c.archived = 0"
        row = await self.conn.execute(
            "SELECT c.id FROM conversations c JOIN players p ON p.conversation_id = c.id"
            " WHERE c.kind = 'private' AND p.user_id = ? "
            + archived_filter
            + " ORDER BY c.id DESC LIMIT 1",
            (user_id,),
        )
        row = await row.fetchone()
        if row is None:
            return None
        return await self.get_conversation(row["id"])

    async def latest_group_conversation(
        self, group_id: str, include_archived: bool = False
    ) -> dict | None:
        """按群 ID 找最近的非归档群会话（出站消息路由用）。"""
        archived_filter = "" if include_archived else "AND archived = 0"
        row = await self.conn.execute(
            "SELECT id FROM conversations WHERE kind = 'group' AND group_id = ? "
            + archived_filter
            + " ORDER BY id DESC LIMIT 1",
            (group_id,),
        )
        row = await row.fetchone()
        if row is None:
            return None
        return await self.get_conversation(row["id"])

    # ---------- 玩家 ----------

    async def add_player(
        self, conversation_id: int, nickname: str, user_id: str
    ) -> dict:
        """向会话添加模拟玩家（user_id 稳定身份；重复添加则返回已有记录）。"""
        existing = await self.get_player(conversation_id, user_id)
        if existing:
            return existing
        async with self._lock:
            cur = await self.conn.execute(
                "INSERT INTO players(conversation_id, nickname, user_id) VALUES(?, ?, ?)",
                (conversation_id, nickname, user_id),
            )
            await self.conn.commit()
            pid = cur.lastrowid
        return {
            "id": pid,
            "conversation_id": conversation_id,
            "nickname": nickname,
            "user_id": user_id,
        }

    async def get_player(self, conversation_id: int, user_id: str) -> dict | None:
        row = await self.conn.execute(
            "SELECT * FROM players WHERE conversation_id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        row = await row.fetchone()
        return dict(row) if row else None

    async def list_players(self, conversation_id: int | None = None) -> list[dict]:
        if conversation_id is None:
            rows = await self.conn.execute("SELECT * FROM players ORDER BY id")
        else:
            rows = await self.conn.execute(
                "SELECT * FROM players WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            )
        return [dict(r) for r in await rows.fetchall()]

    # ---------- 消息 ----------

    async def add_message(
        self,
        conversation_id: int,
        direction: str,
        sender: str,
        text: str,
        rich: Any = None,
    ) -> dict:
        """追加消息，返回记录。direction: in(玩家) / out(机器人) / system。"""
        async with self._lock:
            cur = await self.conn.execute(
                "INSERT INTO messages(conversation_id, direction, sender, text, rich, created_at)"
                " VALUES(?, ?, ?, ?, ?, ?)",
                (conversation_id, direction, sender, text, _jumps(rich), time.time()),
            )
            await self.conn.commit()
            mid = cur.lastrowid
        row = await self.conn.execute("SELECT * FROM messages WHERE id = ?", (mid,))
        return dict(await row.fetchone())

    async def list_messages(
        self, conversation_id: int, after: int = 0, limit: int = 500
    ) -> list[dict]:
        """按时间序读消息；after=游标（消息 id），只返回 id > after 的消息。"""
        rows = await self.conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? AND id > ?"
            " ORDER BY id ASC LIMIT ?",
            (conversation_id, after, limit),
        )
        msgs = []
        for r in await rows.fetchall():
            m = dict(r)
            m["rich"] = _jloads(m["rich"])
            msgs.append(m)
        return msgs

    # ---------- 批注 ----------

    async def add_annotation(self, message_id: int, text: str) -> dict:
        async with self._lock:
            cur = await self.conn.execute(
                "INSERT INTO annotations(message_id, text, updated_at) VALUES(?, ?, ?)",
                (message_id, text, time.time()),
            )
            await self.conn.commit()
            aid = cur.lastrowid
        return {
            "id": aid,
            "message_id": message_id,
            "text": text,
            "updated_at": await self._get_annotation_ts(aid),
        }

    async def _get_annotation_ts(self, aid: int) -> float:
        row = await self.conn.execute(
            "SELECT updated_at FROM annotations WHERE id = ?", (aid,)
        )
        row = await row.fetchone()
        return row["updated_at"] if row else 0.0

    async def get_annotation(self, message_id: int) -> dict | None:
        row = await self.conn.execute(
            "SELECT * FROM annotations WHERE message_id = ?", (message_id,)
        )
        row = await row.fetchone()
        return dict(row) if row else None

    async def update_annotation(self, message_id: int, text: str) -> dict | None:
        async with self._lock:
            cur = await self.conn.execute(
                "UPDATE annotations SET text = ?, updated_at = ? WHERE message_id = ?",
                (text, time.time(), message_id),
            )
            await self.conn.commit()
        if cur.rowcount == 0:
            return None
        return await self.get_annotation(message_id)

    async def delete_annotation(self, message_id: int) -> bool:
        async with self._lock:
            cur = await self.conn.execute(
                "DELETE FROM annotations WHERE message_id = ?", (message_id,)
            )
            await self.conn.commit()
        return cur.rowcount > 0

    async def list_annotations(self, conversation_id: int) -> list[dict]:
        rows = await self.conn.execute(
            "SELECT a.* FROM annotations a JOIN messages m ON m.id = a.message_id"
            " WHERE m.conversation_id = ?",
            (conversation_id,),
        )
        return [dict(r) for r in await rows.fetchall()]

    # ---------- 用例运行轨迹 ----------

    async def add_case_run(
        self,
        case_name: str,
        run_index: int,
        status: str,
        conversation_id: int | None = None,
        case_snapshot: Any = None,
    ) -> dict:
        async with self._lock:
            cur = await self.conn.execute(
                "INSERT INTO case_runs(case_name, run_index, status, conversation_id,"
                " case_snapshot, started_at) VALUES(?, ?, ?, ?, ?, ?)",
                (
                    case_name,
                    run_index,
                    status,
                    conversation_id,
                    _jumps(case_snapshot),
                    time.time(),
                ),
            )
            await self.conn.commit()
            rid = cur.lastrowid
        return await self.get_case_run(rid)

    async def list_case_runs(self, case_name: str | None = None) -> list[dict]:
        if case_name is None:
            rows = await self.conn.execute("SELECT * FROM case_runs ORDER BY id DESC")
        else:
            rows = await self.conn.execute(
                "SELECT * FROM case_runs WHERE case_name = ? ORDER BY id DESC",
                (case_name,),
            )
        runs = []
        for r in await rows.fetchall():
            run = dict(r)
            run["steps_result"] = _jloads(run["steps_result"])
            run["case_snapshot"] = _jloads(run["case_snapshot"])
            run["run_messages"] = _jloads(run["run_messages"])
            runs.append(run)
        return runs

    async def get_case_run(self, run_id: int) -> dict | None:
        row = await self.conn.execute("SELECT * FROM case_runs WHERE id = ?", (run_id,))
        row = await row.fetchone()
        if row is None:
            return None
        run = dict(row)
        run["steps_result"] = _jloads(run["steps_result"])
        run["case_snapshot"] = _jloads(run["case_snapshot"])
        run["run_messages"] = _jloads(run["run_messages"])
        return run

    async def finish_case_run(
        self,
        run_id: int,
        status: str,
        steps_result: Any,
        run_messages: Any,
    ) -> None:
        async with self._lock:
            await self.conn.execute(
                "UPDATE case_runs SET status = ?, steps_result = ?, run_messages = ?, finished_at = ?"
                " WHERE id = ?",
                (
                    status,
                    _jumps(steps_result),
                    _jumps(run_messages),
                    time.time(),
                    run_id,
                ),
            )
            await self.conn.commit()

    async def max_run_index(self, case_name: str) -> int:
        row = await self.conn.execute(
            "SELECT COALESCE(MAX(run_index), 0) AS m FROM case_runs WHERE case_name = ?",
            (case_name,),
        )
        row = await row.fetchone()
        return int(row["m"])

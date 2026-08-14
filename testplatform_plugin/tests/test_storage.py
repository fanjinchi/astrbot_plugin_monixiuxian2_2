"""storage.db.Database 单元测试：CRUD / 级联删除 / 重启恢复。"""

import asyncio
import json

import pytest

from testplatform_plugin.storage.db import Database


@pytest.fixture
def event_loop():
    """为 async 测试提供事件循环。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def run(coro):
    """同步驱动协程。"""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def db(tmp_path):
    """临时数据库实例（连接已建立）。"""
    d = Database(str(tmp_path / "test.db"))
    run(d.connect())
    yield d
    run(d.close())


def test_conversation_crud(db):
    conv = run(db.create_conversation("private", None, "测试会话"))
    assert conv["kind"] == "private"
    assert conv["archived"] == 0
    got = run(db.get_conversation(conv["id"]))
    assert got["name"] == "测试会话"
    updated = run(db.update_conversation(conv["id"], archived=True, name="新名字"))
    assert updated["archived"] == 1
    assert updated["name"] == "新名字"
    listing = run(db.list_conversations())
    assert listing[0]["id"] == conv["id"]
    assert run(db.delete_conversation(conv["id"])) is True
    assert run(db.get_conversation(conv["id"])) is None


def test_player_add_and_dedupe(db):
    conv = run(db.create_conversation("private", None, "c"))
    p1 = run(db.add_player(conv["id"], "玩家甲", "uid_1"))
    assert p1["user_id"] == "uid_1"
    # 同 user_id 重复添加 → 返回已有
    p2 = run(db.add_player(conv["id"], "玩家甲改名", "uid_1"))
    assert p2["id"] == p1["id"]
    assert p2["nickname"] == "玩家甲"
    players = run(db.list_players(conv["id"]))
    assert len(players) == 1


def test_message_flow_and_after_cursor(db):
    conv = run(db.create_conversation("private", None, "c"))
    run(db.add_player(conv["id"], "p", "u1"))
    m1 = run(db.add_message(conv["id"], "in", "u1", "你好", None))
    m2 = run(db.add_message(conv["id"], "out", "bot", "回复", None))
    assert m2["id"] > m1["id"]
    # after 游标只取新消息
    new = run(db.list_messages(conv["id"], after=m1["id"]))
    assert [m["id"] for m in new] == [m2["id"]]
    assert new[0]["direction"] == "out"
    assert new[0]["text"] == "回复"


def test_annotation_crud(db):
    conv = run(db.create_conversation("private", None, "c"))
    run(db.add_player(conv["id"], "p", "u1"))
    m = run(db.add_message(conv["id"], "in", "u1", "闭关", None))
    assert run(db.get_annotation(m["id"])) is None
    ann = run(db.add_annotation(m["id"], "这里要改"))
    assert ann["text"] == "这里要改"
    # 更新
    ann2 = run(db.update_annotation(m["id"], "改成这样"))
    assert ann2["text"] == "改成这样"
    anns = run(db.list_annotations(conv["id"]))
    assert len(anns) == 1 and anns[0]["message_id"] == m["id"]
    assert run(db.delete_annotation(m["id"])) is True
    assert run(db.get_annotation(m["id"])) is None


def test_case_runs_crud(db):
    conv = run(db.create_conversation("private", None, "c"))
    r1 = run(db.add_case_run("case_a", 1, "running", conv["id"], case_snapshot={"name": "case_a"}))
    assert r1["status"] == "running"
    assert r1["case_snapshot"]["name"] == "case_a"
    assert run(db.max_run_index("case_a")) == 1
    assert run(db.max_run_index("case_b")) == 0
    run(db.finish_case_run(r1["id"], "passed", [{"ok": True}], [{"id": 1}]))
    got = run(db.get_case_run(r1["id"]))
    assert got["status"] == "passed"
    assert got["steps_result"] == [{"ok": True}]
    assert got["run_messages"] == [{"id": 1}]
    runs = run(db.list_case_runs("case_a"))
    assert len(runs) == 1


def test_rich_json_roundtrip(db):
    conv = run(db.create_conversation("private", None, "c"))
    run(db.add_player(conv["id"], "p", "u1"))
    rich = [{"type": "image", "text": "[图片]"}]
    run(db.add_message(conv["id"], "out", "bot", "[图片]", rich))
    msgs = run(db.list_messages(conv["id"]))
    assert msgs[0]["rich"] == rich


def test_delete_conversation_cascades(db):
    conv = run(db.create_conversation("private", None, "c"))
    run(db.add_player(conv["id"], "p", "u1"))
    m = run(db.add_message(conv["id"], "in", "u1", "x", None))
    run(db.add_annotation(m["id"], "note"))
    assert run(db.delete_conversation(conv["id"])) is True
    assert run(db.list_players(conv["id"])) == []
    assert run(db.list_messages(conv["id"])) == []
    # 批注随消息级联删除
    assert run(db.get_annotation(m["id"])) is None


def test_restart_recovery(tmp_path):
    """重启恢复：重新打开同一 db 文件，数据仍在。"""
    path = tmp_path / "test.db"
    d1 = Database(str(path))
    run(d1.connect())
    conv = run(d1.create_conversation("private", None, "持久会话"))
    run(d1.add_player(conv["id"], "p", "u1"))
    run(d1.add_message(conv["id"], "in", "u1", "闭关", None))
    run(d1.close())

    d2 = Database(str(path))
    run(d2.connect())
    convs = run(d2.list_conversations())
    assert len(convs) == 1
    assert convs[0]["name"] == "持久会话"
    msgs = run(d2.list_messages(conv["id"]))
    assert msgs[0]["text"] == "闭关"
    run(d2.close())

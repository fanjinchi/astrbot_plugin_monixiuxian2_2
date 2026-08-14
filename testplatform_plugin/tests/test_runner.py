"""cases.runner 单元测试：用假注入器模拟 AstrBot 回复，验证通过/超时/隔离。"""

import asyncio
import json
from pathlib import Path

import pytest

from testplatform_plugin.cases import loader, runner
from testplatform_plugin.storage.db import Database


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeBot:
    """假 AstrBot：注入消息后，根据玩家消息文本回复固定文案。"""

    def __init__(self, reply_map: dict[str, str], delay: float = 0.0):
        self.reply_map = reply_map
        self.delay = delay

    async def inject(self, db: Database, conv_id: int, user_id: str, text: str) -> dict:
        await db.add_message(conv_id, "in", user_id, text, None)
        reply = self.reply_map.get(text, "(无回复)")
        if self.delay:
            await asyncio.sleep(self.delay)
        await db.add_message(conv_id, "out", "bot", reply, None)
        msgs = await db.list_messages(conv_id, after=0)
        return msgs[-2]  # 返回刚注入的 in 消息


@pytest.fixture
def env(tmp_path):
    """临时用例目录 + 临时数据库。"""
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    db = Database(str(tmp_path / "test.db"))
    run(db.connect())
    yield cases_dir, db
    run(db.close())


def write_case(cases_dir: Path, case: dict) -> None:
    loader.save_case(cases_dir, case)


def base_case(name="flow") -> dict:
    return {
        "name": name,
        "description": "d",
        "scenario": "s",
        "tags": [],
        "conversation": {"kind": "private"},
        "steps": [
            {"type": "send", "player": "player1", "text": "闭关"},
            {"type": "expect", "match": "修炼中", "timeout": 5},
        ],
    }


def test_passed_run(env):
    cases_dir, db = env
    write_case(cases_dir, base_case())
    bot = FakeBot({"闭关": "你开始修炼了（修炼中…）"})
    inject = lambda c, u, t: bot.inject(db, c, u, t)  # noqa: E731
    result = run(runner.run_case("flow", cases_dir=cases_dir, db=db, inject=inject))
    assert result["status"] == "passed"
    assert result["run_index"] == 1
    assert result["conversation_id"] is not None
    assert result["case_snapshot"]["name"] == "flow"
    steps = result["steps_result"]
    assert steps[0]["type"] == "send" and steps[0]["ok"]
    assert steps[1]["type"] == "expect" and steps[1]["ok"]
    # 轨迹：运行期全部消息（1 条 in + 1 条 out）
    msgs = result["run_messages"]
    assert [m["direction"] for m in msgs] == ["in", "out"]
    # 玩家身份唯一化
    players = run(db.list_players(result["conversation_id"]))
    assert players[0]["user_id"].startswith("case_flow_1_")


def test_failed_run_records_actual_replies(env):
    cases_dir, db = env
    write_case(cases_dir, base_case())
    bot = FakeBot({"闭关": "你没有修炼资格"})
    inject = lambda c, u, t: bot.inject(db, c, u, t)  # noqa: E731
    result = run(runner.run_case("flow", cases_dir=cases_dir, db=db, inject=inject))
    assert result["status"] == "failed"
    step = result["steps_result"][1]
    assert not step["ok"]
    assert any("没有修炼资格" in t for t in step["actual"])  # 期望不匹配时保留实际回复
    assert result["run_messages"][-1]["text"] == "你没有修炼资格"


def test_two_runs_are_isolated(env):
    cases_dir, db = env
    write_case(cases_dir, base_case())
    bot = FakeBot({"闭关": "修炼中"})
    r1 = run(runner.run_case("flow", cases_dir=cases_dir, db=db, inject=lambda c, u, t: bot.inject(db, c, u, t)))
    r2 = run(runner.run_case("flow", cases_dir=cases_dir, db=db, inject=lambda c, u, t: bot.inject(db, c, u, t)))
    assert r1["run_index"] == 1 and r2["run_index"] == 2
    # 两次运行使用不同会话与不同玩家身份 → 互不污染
    assert r1["conversation_id"] != r2["conversation_id"]
    p1 = run(db.list_players(r1["conversation_id"]))[0]["user_id"]
    p2 = run(db.list_players(r2["conversation_id"]))[0]["user_id"]
    assert p1 != p2
    assert run(db.max_run_index("flow")) == 2
    assert len(run(db.list_case_runs("flow"))) == 2


def test_pin_players_uses_fixed_identity(env):
    cases_dir, db = env
    case = base_case()
    case["conversation"]["pin_players"] = {"player1": "gm_admin_001"}
    write_case(cases_dir, case)
    bot = FakeBot({"闭关": "修炼中"})
    inject = lambda c, u, t: bot.inject(db, c, u, t)  # noqa: E731
    result = run(runner.run_case("flow", cases_dir=cases_dir, db=db, inject=inject))
    players = run(db.list_players(result["conversation_id"]))
    assert players[0]["user_id"] == "gm_admin_001"


def test_regex_match(env):
    cases_dir, db = env
    case = base_case()
    case["steps"][1]["match"] = "re:修为.*\\d+"
    write_case(cases_dir, case)
    bot = FakeBot({"闭关": "修为+120"})
    result = run(runner.run_case("flow", cases_dir=cases_dir, db=db, inject=lambda c, u, t: bot.inject(db, c, u, t)))
    assert result["status"] == "passed"


def test_missing_case_records_error(env):
    cases_dir, db = env
    result = run(runner.run_case("nope", cases_dir=cases_dir, db=db, inject=None))
    assert result["status"] == "error"
    assert result["run_index"] == 1


def test_injector_exception_records_error(env):
    cases_dir, db = env
    write_case(cases_dir, base_case())

    async def broken_inject(conv_id, user_id, text):
        raise RuntimeError("注入器故障")

    result = run(runner.run_case("flow", cases_dir=cases_dir, db=db, inject=broken_inject))
    assert result["status"] == "error"
    assert "注入器故障" in result["steps_result"][-1]["detail"]


def test_sleep_step(env):
    cases_dir, db = env
    case = base_case()
    case["steps"] = [
        {"type": "send", "player": "player1", "text": "闭关"},
        {"type": "sleep", "seconds": 0.2},
        {"type": "expect", "match": "修炼中", "timeout": 5},
    ]
    write_case(cases_dir, case)
    bot = FakeBot({"闭关": "修炼中"})
    inject = lambda c, u, t: bot.inject(db, c, u, t)  # noqa: E731
    result = run(runner.run_case("flow", cases_dir=cases_dir, db=db, inject=inject))
    assert result["status"] == "passed"
    assert result["steps_result"][1]["type"] == "sleep"

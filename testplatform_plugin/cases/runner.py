"""用例运行器。

每次运行：创建**临时会话**（system-created）与**唯一玩家身份**
（``case_{用例名}_{run序号}_{player}``，修仙插件按 user_id 键控玩家 →
天然从零状态）；``pin_players`` 可钉住固定 user_id（承担状态继承，默认不钉）。

步骤执行：``send``=注入，``expect``=轮询该会话新 out 消息匹配（超时失败，
记录超时前全部实际回复），``sleep``=真实等待。

结果与**轨迹**写入 DB ``case_runs`` 表：status、逐步骤结果（含实际回复）、
``case_snapshot``（用例文件内容快照）、``run_messages``（运行期全部消息交换
快照含时序）——轨迹独立于会话持久化，会话删除不丢轨迹；运行会话保留供人工批注。

本模块不 import AstrBot——注入器由调用方注入（``inject`` 参数），便于脱离
AstrBot 环境单测。
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from . import loader

PollFn = Callable[[int, int], Awaitable[list[dict]]]
InjectFn = Callable[[int, str, str], Awaitable[dict]]


def match_reply(text: str, pattern: str) -> bool:
    """期望匹配：默认子串；前缀 ``re:`` 为正则搜索。"""
    if pattern.startswith("re:"):
        return re.search(pattern[3:], text) is not None
    return pattern in text


async def run_case(
    case_name: str,
    *,
    cases_dir: Path,
    db: Any,
    inject: InjectFn,
    poll: PollFn | None = None,
) -> dict:
    """运行一个用例（从磁盘重读，最新内容生效），返回最终 run 记录。

    Args:
        case_name: 用例名（对应 cases/<case_name>.json）。
        cases_dir: 用例目录。
        db: Database 实例（写入 case_runs 与创建会话）。
        inject: 注入器 ``inject(conversation_id, player_user_id, text)``，
            消息进入 AstrBot 真实管线（生产环境为 app_state.inject_message）。
        poll: 轮询器 ``poll(conversation_id, after) -> [message, ...]``，
            默认 db.list_messages。

    Returns:
        完整 run 记录（含 steps_result / run_messages / case_snapshot）。
    """
    poll = poll or db.list_messages

    try:
        case = loader.load_case_file(cases_dir / f"{case_name}.json")
    except (ValueError, OSError) as exc:
        run = await db.add_case_run(
            case_name, await db.max_run_index(case_name) + 1, "error"
        )
        await db.finish_case_run(run["id"], "error", [{"error": str(exc)}], [])
        return await db.get_case_run(run["id"])

    run_index = await db.max_run_index(case_name) + 1
    conv = case["conversation"]
    conv_name = f"[用例] {case_name} #{run_index}"
    conversation = await db.create_conversation(
        kind=conv.get("kind", "private"),
        group_id=conv.get("group_id"),
        name=conv_name,
        system_created=True,
    )
    conv_id = conversation["id"]

    # 玩家身份：默认唯一 user_id（从零状态）；pin_players 钉住固定身份
    pin_players = conv.get("pin_players", {}) or {}
    player_ids: dict[str, str] = {}
    for step in case["steps"]:
        if step["type"] == "send" and step["player"] not in player_ids:
            player_ids[step["player"]] = pin_players.get(
                step["player"], f"case_{case_name}_{run_index}_{step['player']}"
            )
    for label, user_id in pin_players.items():
        player_ids.setdefault(label, user_id)
    for label, user_id in player_ids.items():
        await db.add_player(conv_id, label, user_id)

    run = await db.add_case_run(
        case_name, run_index, "running", conv_id, case_snapshot=case
    )

    steps_result: list[dict] = []
    status = "passed"
    after = 0
    out_window: list[dict] = []  # 本 expect 窗口内收集到的 out 消息

    try:
        for index, step in enumerate(case["steps"]):
            stype = step["type"]
            note = step.get("note", "")
            started = asyncio.get_event_loop().time()
            result: dict = {
                "index": index,
                "type": stype,
                "note": note,
                "ok": False,
                "detail": "",
                "actual": [],
            }
            if stype == "send":
                user_id = player_ids.get(step["player"], step["player"])
                msg = await inject(conv_id, user_id, step["text"])
                result.update(ok=True, detail=f"已注入（消息 #{msg['id']}）")
            elif stype == "expect":
                deadline = asyncio.get_event_loop().time() + float(
                    step.get("timeout", 30)
                )
                matched = None
                while asyncio.get_event_loop().time() < deadline:
                    new_msgs = await poll(conv_id, after)
                    for msg in new_msgs:
                        if msg["id"] > after:
                            after = msg["id"]
                        if msg["direction"] == "out":
                            out_window.append(msg)
                            if match_reply(msg["text"] or "", step["match"]):
                                matched = msg
                                break
                    if matched:
                        break
                    await asyncio.sleep(0.3)
                result["actual"] = [m["text"] for m in out_window]
                if matched:
                    result.update(
                        ok=True,
                        detail=f"匹配（消息 #{matched['id']}：{matched['text'][:60]}）",
                    )
                else:
                    result.update(
                        detail=f"超时未匹配 {step['match']!r}；窗口内实际回复 {len(out_window)} 条"
                    )
                    status = "failed"
            else:  # sleep
                await asyncio.sleep(float(step["seconds"]))
                result.update(ok=True, detail=f"等待 {step['seconds']}s")
            result["duration"] = round(asyncio.get_event_loop().time() - started, 2)
            steps_result.append(result)
            if status != "passed":
                break
    except Exception as exc:  # 运行期异常（如注入器报错）→ 记为 error
        status = "error"
        steps_result.append(
            {
                "index": len(steps_result),
                "type": "error",
                "note": "",
                "ok": False,
                "detail": str(exc),
                "actual": [],
            }
        )

    run_messages = await db.list_messages(conv_id, after=0, limit=100000)
    await db.finish_case_run(run["id"], status, steps_result, run_messages)
    return await db.get_case_run(run["id"])

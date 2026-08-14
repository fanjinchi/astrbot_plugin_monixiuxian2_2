"""用例加载与校验。

用例为 ``data/plugin_data/astrbot_plugin_testplatform/cases/<name>.json`` 的
JSON 文件，一个文件一个用例，**自带人可读说明**：

.. code-block:: json

    {
      "name": "cultivation-basic-flow",
      "description": "验证新玩家从零开始的修炼主循环：注册 → 闭关 → 等待结算 → 出关收获。",
      "scenario": "前置条件：无（运行器自动使用全新玩家身份）。覆盖：注册/修炼/结算。",
      "tags": ["cultivation", "smoke"],
      "conversation": { "kind": "private" },
      "steps": [
        { "type": "send", "player": "player_a", "text": "我要修仙", "note": "新玩家注册" },
        { "type": "expect", "match": "修仙", "timeout": 10, "note": "期望收到注册成功提示" }
      ]
    }

必填字段：``name``、``description``（测试目的与覆盖场景）、``scenario``
（前置条件/涉及功能）、``steps``（非空）。缺必填说明字段的用例**校验拒绝**，
不参与列出与运行。步骤类型：``send``（注入消息）、``expect``（期望回复匹配，
match 默认子串，前缀 ``re:`` 为正则，含 timeout）、``sleep``（等待秒数）。
可选字段：``tags``、``conversation``（``kind`` private|group、``group_id``、
``pin_players``）、步骤 ``note``（做什么、期望什么的人读说明）。

列表与运行每次从文件系统重读——服务器端直接编辑 JSON 即时生效，无需重启。
"""

import json
import re
import time
from pathlib import Path
from typing import Any

VALID_STEP_TYPES = ("send", "expect", "sleep")


def new_case_template(name: str) -> dict:
    """生成新用例模板（含占位说明字段）。"""
    return {
        "name": name,
        "description": "（必填）本用例测试的目的与覆盖场景，一句话说明。",
        "scenario": "（必填）前置条件与涉及功能。",
        "tags": [],
        "conversation": {"kind": "private"},
        "steps": [
            {
                "type": "send",
                "player": "player_a",
                "text": "我要修仙",
                "note": "（可选）这一步做什么、期望什么。",
            },
            {
                "type": "expect",
                "match": "修仙",
                "timeout": 30,
                "note": "（可选）期望收到的回复内容（子串；前缀 re: 为正则）。",
            },
        ],
    }


def validate_case(data: Any, source: str = "") -> None:
    """校验用例结构；不合法时抛出 ValueError（带具体原因）。

    Raises:
        ValueError: 用例缺少必填字段或结构非法。
    """
    ctx = f"（{source}）" if source else ""
    if not isinstance(data, dict):
        raise ValueError(f"用例必须是 JSON 对象{ctx}")
    for field in ("name", "description", "scenario"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"用例缺少必填字段 {field!r}{ctx}")
    if not isinstance(data.get("tags", []), list) or not all(
        isinstance(t, str) for t in data["tags"]
    ):
        raise ValueError(f"用例 tags 必须是字符串数组{ctx}")
    conv = data.get("conversation", {})
    if not isinstance(conv, dict):
        raise ValueError(f"用例 conversation 必须是对象{ctx}")
    kind = conv.get("kind", "private")
    if kind not in ("private", "group"):
        raise ValueError(f"conversation.kind 只能是 private|group{ctx}")
    if kind == "group" and not (
        isinstance(conv.get("group_id"), str) and conv["group_id"]
    ):
        raise ValueError(f"群聊用例必须提供 conversation.group_id{ctx}")
    pin = conv.get("pin_players", {})
    if pin is not None and not isinstance(pin, dict):
        raise ValueError(
            f"conversation.pin_players 必须是对象（player 标签 -> user_id）{ctx}"
        )
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"用例 steps 必须是非空数组{ctx}")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"steps[{i}] 必须是对象{ctx}")
        stype = step.get("type")
        if stype not in VALID_STEP_TYPES:
            raise ValueError(f"steps[{i}].type 必须是 {VALID_STEP_TYPES}{ctx}")
        if stype == "send":
            if not (isinstance(step.get("player"), str) and step["player"]):
                raise ValueError(f"steps[{i}].player 必填（send）{ctx}")
            if not isinstance(step.get("text"), str):
                raise ValueError(f"steps[{i}].text 必填（send）{ctx}")
        elif stype == "expect":
            if not isinstance(step.get("match"), str) or not step["match"]:
                raise ValueError(f"steps[{i}].match 必填（expect）{ctx}")
            timeout = step.get("timeout", 30)
            if not isinstance(timeout, (int, float)) or timeout <= 0:
                raise ValueError(f"steps[{i}].timeout 必须是正数{ctx}")
            if step["match"].startswith("re:"):
                try:
                    re.compile(step["match"][3:])
                except re.error as exc:
                    raise ValueError(
                        f"steps[{i}].match 正则不合法: {exc}{ctx}"
                    ) from exc
        else:  # sleep
            seconds = step.get("seconds")
            if not isinstance(seconds, (int, float)) or seconds <= 0:
                raise ValueError(f"steps[{i}].seconds 必须是正数（sleep）{ctx}")


def load_case_file(path: Path) -> dict:
    """读取并校验单个用例文件；不合法抛 ValueError。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"用例 JSON 解析失败: {exc}") from exc
    validate_case(data, source=path.stem)
    if data["name"] != path.stem:
        raise ValueError(f"用例 name（{data['name']!r}）与文件名（{path.stem}）不一致")
    return data


def load_cases_dir(cases_dir: Path) -> tuple[list[dict], list[dict]]:
    """重读用例目录，返回 (合法用例列表, 非法用例错误列表)。

    非法用例跳过不参与运行，但错误信息返回给调用方展示（网页/CLI 可见原因）。
    """
    cases, errors = [], []
    if not cases_dir.exists():
        return cases, errors
    for path in sorted(cases_dir.glob("*.json")):
        try:
            cases.append(load_case_file(path))
        except ValueError as exc:
            errors.append({"name": path.stem, "error": str(exc)})
    return cases, errors


def save_case(cases_dir: Path, data: dict) -> dict:
    """校验并写入用例文件（原子写）。校验失败不落盘。"""
    validate_case(data, source=str(data.get("name", "")))
    cases_dir.mkdir(parents=True, exist_ok=True)
    path = cases_dir / f"{data['name']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)
    data["updated_at"] = time.time()
    return data


def delete_case(cases_dir: Path, name: str) -> bool:
    """删除用例文件。"""
    path = cases_dir / f"{name}.json"
    if not path.exists():
        return False
    path.unlink()
    return True

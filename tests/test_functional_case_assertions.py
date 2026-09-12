"""功能用例断言步骤的静态护栏：断言前必须有新的 ``send``（平台 runner 窗口语义）。

根因类别（独立评审判定为 blocker）：平台 runner 的匹配窗口只在新 out 消息到达时才重新求值
——``out_window`` 在步骤循环**外**初始化，拼接与匹配都写在 ``new_msgs`` 非空的分支里，
而游标 ``after`` 整用例单调递增（``../astrbot_plugin_testplatform/cases/runner.py`` 的
步骤循环）。因此「同一份回复上的第二条断言」永远等不到新消息 → 窗口永不重新求值 →
超时失败，且 runner 在首个失败步骤 fail-fast（``if status != "passed": break``），
后续步骤全部不执行。

真实实例：``functional_tests/cases/pvp/pvp-basic-duel.json`` 曾在唯一一条战报消息上串接
3 条 ``combine`` 断言（战报链 / 千分位分档 / 无千分位分档），第 2、3 条必超时。修法是
每条断言前补一条哨兵 ``send``（如 ``#我的信息``），本测试把这个约束钉成护栏。

规则：用例内任何断言步骤之前，必须存在一条**新的** ``send``（即自上一个断言步骤以来
至少注入过一条消息）；等价于「不存在连续两个仅断言的步骤」。非 ``combine`` 断言同样
适用——它也需要新消息才会被求值；``sleep`` 不产生新消息，故不算数。
"""

import json
from pathlib import Path

import pytest

from tests.helpers import PLUGIN_ROOT

CASES_ROOT = PLUGIN_ROOT / "functional_tests" / "cases"
ASSERTION_STEPS = ("expect", "expect_not")

# Shared remediation text: the guard failure must name the runner semantics.
WINDOW_RULE = (
    "平台 runner 只在 poll 到新的 out 消息时才重新拼接/匹配窗口（combine 窗口 "
    "out_window 在步骤循环外初始化、游标 after 整用例单调递增），故同一份回复上的"
    "第二条断言永不求值：每条断言前必须有一条新的 send（哨兵 #我的信息 即可），"
    "否则该步骤必超时并触发 fail-fast（真实实例：pvp-basic-duel 的两条剩余气血分档断言）"
)


def _assertion_window_violations(steps: list[dict]) -> list[str]:
    """Apply the window rule to one step list.

    Args:
        steps: Case step dicts as loaded from JSON.

    Returns:
        ``"step<N> (<type>/<tag>)"`` for each assertion step that has no new
        ``send`` since the previous assertion step; empty when the case is clean.
    """
    violations = []
    pending_assert = False
    for index, step in enumerate(steps):
        stype = step["type"]
        if stype == "send":
            pending_assert = False
        elif stype in ASSERTION_STEPS:
            if pending_assert:
                tag = "combine" if step.get("combine") else "single"
                violations.append(f"step{index} ({stype}/{tag})")
            pending_assert = True
    return violations


def find_window_violations(cases_root: Path) -> list[str]:
    """Scan a case directory for the window-evaluation anti-pattern.

    Args:
        cases_root: Directory holding the case JSONs (searched recursively).

    Returns:
        ``"<case path> step<N> (<type>/<tag>)"`` descriptions; empty when clean.
    """
    violations = []
    for path in sorted(cases_root.rglob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        violations += [
            f"{path.relative_to(cases_root)} {label}"
            for label in _assertion_window_violations(case["steps"])
        ]
    return violations


def test_every_assertion_step_is_preceded_by_a_new_send():
    """用例中不得出现两个连续断言步骤（第二个等不到新消息，必超时）。"""
    violations = find_window_violations(CASES_ROOT)

    assert not violations, (
        f"用例含「断言步骤前无新 send」的编排缺陷：{violations}；{WINDOW_RULE}"
    )


def test_guard_scans_a_non_empty_assertion_corpus():
    """反向护栏：确认扫描确实覆盖到用例与 combine 断言，避免路径写错时假绿。"""
    cases = sorted(CASES_ROOT.rglob("*.json"))
    combined = sum(
        1
        for path in cases
        for step in json.loads(path.read_text(encoding="utf-8"))["steps"]
        if step["type"] in ASSERTION_STEPS and step.get("combine")
    )

    assert cases, f"未发现任何用例：{CASES_ROOT}"
    assert combined, "用例语料里没有 combine 断言，护栏形同虚设"


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        # blocker 的旧形态：战报链 combine → 两条分档 combine（无哨兵）→ 第二条报红
        (
            [
                {"type": "send", "text": "#决斗 900000003"},
                {"type": "expect", "combine": True},
                {"type": "expect", "combine": True},
            ],
            ["step2 (expect/combine)"],
        ),
        # 哨兵修法：每条断言前各有一条新 send → 干净
        (
            [
                {"type": "send", "text": "#决斗 900000003"},
                {"type": "expect", "combine": True},
                {"type": "send", "text": "#我的信息"},
                {"type": "expect", "combine": True},
                {"type": "send", "text": "#我的信息"},
                {"type": "expect_not", "combine": True},
            ],
            [],
        ),
        # sleep 不产生新消息，同样救不了连续断言（非 combine 断言也适用）
        (
            [
                {"type": "expect"},
                {"type": "sleep", "seconds": 2},
                {"type": "expect_not"},
            ],
            ["step2 (expect_not/single)"],
        ),
    ],
)
def test_window_rule_is_pinned_by_synthetic_step_sequences(steps, expected):
    """钉规则本身：旧形态报红、哨兵形态通过、sleep 不算新消息。"""
    assert _assertion_window_violations(steps) == expected

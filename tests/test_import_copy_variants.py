"""copy_variants.csv 灌入器（scripts/import_copy_variants.py）的回归测试。

覆盖：12 册解析行数、分域、组属性、键归一、州条覆盖、编号连续性，
以及灌入后 lint 全表 0 FAIL（tasks 5.5/6.2 质量门）。
"""

import csv
import subprocess
import sys
from collections import Counter
from pathlib import Path

from tests.helpers import load_module

_mod = load_module("import_copy_variants", "scripts/import_copy_variants.py")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORY_DIR = PROJECT_ROOT / "design_docs" / "剧情"


def _parse_all() -> list[dict]:
    """复现 main() 的解析流程（不写盘）。"""
    rows: list[dict] = []
    for filename, group in _mod.EVENT_BOOKS:
        rows.extend(_mod.parse_book(STORY_DIR / filename, "adventure_event", group))
    rows.extend(_mod.parse_book(STORY_DIR / "01-突破剧本.md", "breakthrough", ""))
    for r in rows:
        r["domain"] = _mod.KEY_DOMAIN.get(r["scene"], r["domain"])
    rows.extend(_mod.parse_book(STORY_DIR / "02-修炼结算剧本.md", "cultivation", ""))
    rows.extend(_mod.parse_book(STORY_DIR / "03-战斗说书人剧本.md", "combat", ""))
    return rows


def test_parse_total_rows() -> None:
    """12 册应产出 477 行（事件 341 + 突破 55 + 修炼 18 + 战斗 55 + 机缘 8）。"""
    assert len(_parse_all()) == 477


def test_domain_split() -> None:
    """分域行数：adventure_event 341 / breakthrough 55 / combat 55 / cultivation 18 / fortune 8。"""
    counts = Counter(r["domain"] for r in _parse_all())
    assert counts == {
        "adventure_event": 341,
        "breakthrough": 55,
        "combat": 55,
        "cultivation": 18,
        "fortune": 8,
    }


def test_group_split() -> None:
    """事件域组属性：散修 121 + 五宗组各 44。"""
    rows = _parse_all()
    event_rows = [r for r in rows if r["domain"] == "adventure_event"]
    groups = Counter(r["group"] for r in event_rows)
    assert groups[""] == 121
    for g in (
        "sect_qingyun",
        "sect_jingang",
        "sect_tianji",
        "sect_wandu",
        "sect_xuemo",
    ):
        assert groups[g] == 44, f"{g} 应有 44 行"


def test_key_rename() -> None:
    """连字符键归一：pity-hint→pity_hint、lose-streak→lose_streak_reward、
    comprehend-*、weapon-drop→fortune.weapon_drop。"""
    rows = _parse_all()
    scenes = {(r["domain"], r["scene"]) for r in rows}
    assert ("breakthrough", "pity_hint") in scenes
    assert ("breakthrough", "lose_streak_reward") in scenes
    assert ("breakthrough", "comprehend_success") in scenes
    assert ("breakthrough", "comprehend_universal") in scenes
    assert ("fortune", "weapon_drop") in scenes
    assert ("fortune", "pill_drop") in scenes
    assert ("breakthrough", "comprehend") not in scenes  # 未归一键不得出现


def test_state_coverage() -> None:
    """散修州条六州各 11（6×11=66）；宗门州条落本宗州：云州 48（青云+天机双宗）、
    朔/蛮/沧各 24、青/中 0。"""
    rows = _parse_all()
    event_rows = [r for r in rows if r["domain"] == "adventure_event"]
    states = Counter(r["state"] for r in event_rows if r["state"] != "通用")
    assert sum(states.values()) == 66 + 120
    # 散修州条：六州各 11（11 事件 × 每州 1 条）
    for state in _mod.STATES:
        n = sum(
            1
            for r in event_rows
            if r["group"] == "" and r["state"] == state and r["level_band"] == "通用"
        )
        assert n == 11, f"散修 {state} 应有 11 条州专属，实得 {n}"
    # 宗门州条：云州 48（青云门+天机阁）、朔/蛮/沧各 24、青/中 0
    for group, state in _mod.SECT_STATE.items():
        n = sum(1 for r in event_rows if r["group"] == group and r["state"] == state)
        assert n == 24, f"{group} 应有 24 条本宗州州条（4 事件 × 6），实得 {n}"
    assert states["云州"] == 11 + 48
    assert states["朔州"] == 11 + 24
    assert states["蛮州"] == 11 + 24
    assert states["沧州"] == 11 + 24
    assert "青州" not in states or states["青州"] == 11
    assert "中州" not in states or states["中州"] == 11


def test_variant_no_sequence() -> None:
    """(domain, scene, group) 内 variant_no 从 01 连续递增（lint 唯一性前提）。"""
    _mod.check_rows(_parse_all())  # 不满足会抛 ValueError


def test_imported_csv_zero_fail() -> None:
    """灌入后的 copy_variants.csv 过 lint 闸门：0 FAIL。"""
    proc = subprocess.run(
        [sys.executable, "design_docs/content-design/lint_narrative.py"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert "Summary: 0 FAIL" in proc.stdout, proc.stdout[-2000:]
    # 表头含 group 列
    with (PROJECT_ROOT / "design_docs/content-design/copy_variants.csv").open(
        encoding="utf-8", newline=""
    ) as f:
        header = csv.DictReader(f).fieldnames
    assert "group" in header

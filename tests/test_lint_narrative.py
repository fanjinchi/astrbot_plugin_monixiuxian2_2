"""Tests for the narrative lint gate (design_docs/content-design/lint_narrative.py).

Covers the content-sync-pipeline 叙事文案 lint 闸门 delta
(openspec/changes/narrative-content-pipeline/): banned-word / numeric-promise /
length / grade-article text checks, canon column validation, name consistency,
severity gating by narrative_status, and the backlog WARN for light canon tables.
"""

from tests.helpers import load_module

_lint = load_module("lint_narrative", "design_docs/content-design/lint_narrative.py")


# ---------------------------------------------------------------------------
# _text_violations
# ---------------------------------------------------------------------------


def test_banned_word_detected():
    problems = _lint._text_violations("你触发了被动技能，伤害暴涨", 60)
    assert any("技能" in p for p in problems)


def test_banned_word_whitelist_phrase_passes():
    # "实战经验" 整体是正当叙事词（白名单），不应命中禁词"经验"
    assert _lint._text_violations("你击退了妖兽，增长了实战经验。", 60) == []


def test_numeric_promise_detected():
    assert any("百分号" in p for p in _lint._text_violations("伤害提升30%", 60))
    assert any("数字" in p for p in _lint._text_violations("攻击+15点", 60))


def test_length_cap():
    long_text = "x" * 61
    assert any("超上限" in p for p in _lint._text_violations(long_text, 60))
    assert _lint._text_violations("x" * 60, 60) == []


def test_grade_article_in_body_detected():
    assert any("品级冠词" in p for p in _lint._text_violations("这是一柄天品宝剑", 60))


def test_empty_text_is_clean():
    assert _lint._text_violations("", 60) == []


# ---------------------------------------------------------------------------
# _origin_registered
# ---------------------------------------------------------------------------


def test_origin_registered():
    assert _lint._origin_registered("云州·青云山")
    assert _lint._origin_registered("散修日常")
    assert _lint._origin_registered("青云门")
    assert not _lint._origin_registered("云州·落星湖")
    assert not _lint._origin_registered("")


# ---------------------------------------------------------------------------
# _severity
# ---------------------------------------------------------------------------


def test_severity_gating():
    assert _lint._severity("legacy", "占位", strict=True) == "WARN"
    assert _lint._severity("draft", "定稿", strict=False) == "FAIL"
    assert _lint._severity("draft", "占位", strict=False) == "WARN"
    assert _lint._severity("draft", "占位", strict=True) == "FAIL"


# ---------------------------------------------------------------------------
# _check_name_consistency
# ---------------------------------------------------------------------------


def test_name_consistency_mismatch_fails():
    rows = [{"id": "sword_006", "name": "青云天剑", "status": "draft"}]
    results: list[str] = []
    _lint._check_name_consistency(
        rows, "weapons", {"sword_006": "裂空神剑"}, "id", results
    )
    assert len(results) == 1 and results[0].startswith("FAIL")


def test_name_consistency_legacy_mismatch_warns():
    rows = [{"id": "sword_006", "name": "青云天剑", "status": "legacy"}]
    results: list[str] = []
    _lint._check_name_consistency(
        rows, "weapons", {"sword_006": "裂空神剑"}, "id", results
    )
    assert len(results) == 1 and results[0].startswith("WARN")


def test_name_consistency_new_entry_skipped():
    # config 无此 id（新增条目，同步时 append），不产生一致性问题
    rows = [{"id": "new_001", "name": "新剑", "status": "draft"}]
    results: list[str] = []
    _lint._check_name_consistency(rows, "weapons", {}, "id", results)
    assert results == []


# ---------------------------------------------------------------------------
# _check_canon_columns
# ---------------------------------------------------------------------------


def _canon_row(**over):
    row = {
        "id": "x1",
        "status": "draft",
        "canon_origin": "云州",
        "tone_tier": "正经",
        "story_hook": "",
        "narrative_status": "占位",
    }
    row.update(over)
    return row


def test_canon_columns_missing_fail():
    results: list[str] = []
    _lint._check_canon_columns([{"id": "x1"}], "weapons", results)
    assert any(r.startswith("FAIL") and "缺 canon 列" in r for r in results)


def test_canon_columns_illegal_tone_fails():
    results: list[str] = []
    _lint._check_canon_columns([_canon_row(tone_tier="幽默风")], "weapons", results)
    assert any(r.startswith("FAIL") and "tone_tier" in r for r in results)


def test_canon_columns_empty_origin_warns():
    results: list[str] = []
    _lint._check_canon_columns([_canon_row(canon_origin="")], "weapons", results)
    assert any(r.startswith("WARN") and "canon_origin 为空" in r for r in results)


def test_canon_columns_unregistered_origin_fails():
    results: list[str] = []
    _lint._check_canon_columns(
        [_canon_row(canon_origin="云州·落星湖")], "weapons", results
    )
    assert any(r.startswith("FAIL") and "未在 bible 登记" in r for r in results)


def test_canon_columns_illegal_narrative_status_fails():
    results: list[str] = []
    _lint._check_canon_columns(
        [_canon_row(narrative_status="已写完")], "weapons", results
    )
    assert any(r.startswith("FAIL") and "narrative_status" in r for r in results)


# ---------------------------------------------------------------------------
# _check_narrative_backlog（轻量 canon 表的叙事待写 WARN）
# ---------------------------------------------------------------------------


def test_backlog_warn_for_placeholder_rows():
    rows = [
        {"id": "a", "narrative_status": "占位"},
        {"id": "b", "narrative_status": "待写"},
        {"id": "c", "narrative_status": "定稿"},
    ]
    results: list[str] = []
    _lint._check_narrative_backlog(rows, "rifts", results)
    assert len(results) == 2
    assert all(r.startswith("WARN") for r in results)

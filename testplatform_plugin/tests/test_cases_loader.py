"""cases.loader 单元测试：校验规则 / 必填字段拒收 / 模板。"""

import pytest

from testplatform_plugin.cases import loader

GOOD_CASE = {
    "name": "test-case",
    "description": "测试用例",
    "scenario": "验证基本流程",
    "tags": ["cultivation"],
    "conversation": {"kind": "private"},
    "steps": [
        {"type": "send", "player": "player1", "text": "闭关"},
        {"type": "expect", "match": "修炼", "timeout": 30},
    ],
}


def test_valid_case_passes():
    loader.validate_case(GOOD_CASE)  # 不抛异常


def test_missing_required_fields_rejected():
    for field in ("description", "scenario"):
        case = dict(GOOD_CASE)
        del case[field]
        with pytest.raises(ValueError, match=field):
            loader.validate_case(case)


def test_empty_required_fields_rejected():
    case = dict(GOOD_CASE)
    case["description"] = "   "
    with pytest.raises(ValueError, match="description"):
        loader.validate_case(case)


def test_empty_steps_rejected():
    case = dict(GOOD_CASE, steps=[])
    with pytest.raises(ValueError, match="steps"):
        loader.validate_case(case)


def test_send_step_requires_player_and_text():
    case = dict(GOOD_CASE, steps=[{"type": "send", "player": "p1"}])
    with pytest.raises(ValueError, match="text"):
        loader.validate_case(case)
    case = dict(GOOD_CASE, steps=[{"type": "send", "text": "hi"}])
    with pytest.raises(ValueError, match="player"):
        loader.validate_case(case)


def test_expect_requires_match_and_positive_timeout():
    case = dict(GOOD_CASE, steps=[{"type": "expect", "match": "x", "timeout": 0}])
    with pytest.raises(ValueError, match="timeout"):
        loader.validate_case(case)
    case = dict(GOOD_CASE, steps=[{"type": "expect", "match": "x", "timeout": -1}])
    with pytest.raises(ValueError, match="timeout"):
        loader.validate_case(case)


def test_bad_regex_rejected():
    case = dict(GOOD_CASE, steps=[{"type": "expect", "match": "re:[", "timeout": 5}])
    with pytest.raises(ValueError, match="正则"):
        loader.validate_case(case)


def test_sleep_requires_positive_seconds():
    case = dict(GOOD_CASE, steps=[{"type": "sleep"}])
    with pytest.raises(ValueError, match="seconds"):
        loader.validate_case(case)


def test_group_requires_group_id():
    case = dict(GOOD_CASE, conversation={"kind": "group"})
    with pytest.raises(ValueError, match="group_id"):
        loader.validate_case(case)


def test_unknown_step_type_rejected():
    case = dict(GOOD_CASE, steps=[{"type": "dance"}])
    with pytest.raises(ValueError, match="type 必须"):
        loader.validate_case(case)


def test_name_must_match_filename(tmp_path):
    (tmp_path / "other-name.json").write_text(
        __import__("json").dumps(GOOD_CASE, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="文件名"):
        loader.load_case_file(tmp_path / "other-name.json")


def test_save_and_reload(tmp_path):
    case = dict(GOOD_CASE, name="save-me")
    loader.save_case(tmp_path, case)
    loaded = loader.load_case_file(tmp_path / "save-me.json")
    assert loaded["description"] == "测试用例"
    assert loaded["steps"][1]["match"] == "修炼"


def test_save_rejects_invalid_without_writing(tmp_path):
    bad = dict(GOOD_CASE, name="bad", description="")
    with pytest.raises(ValueError):
        loader.save_case(tmp_path, bad)
    assert not (tmp_path / "bad.json").exists()


def test_load_cases_dir_collects_errors(tmp_path):
    loader.save_case(tmp_path, dict(GOOD_CASE, name="good"))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    cases, errors = loader.load_cases_dir(tmp_path)
    assert [c["name"] for c in cases] == ["good"]
    assert errors[0]["name"] == "broken"
    assert "解析失败" in errors[0]["error"]


def test_new_case_template(tmp_path):
    tpl = loader.new_case_template("fresh-case")
    assert tpl["name"] == "fresh-case"
    loader.validate_case(tpl)  # 模板本身合法
    # 模板可直接保存
    loader.save_case(tmp_path, tpl)
    assert (tmp_path / "fresh-case.json").exists()


def test_delete_case(tmp_path):
    loader.save_case(tmp_path, dict(GOOD_CASE, name="del-me"))
    assert loader.delete_case(tmp_path, "del-me") is True
    assert loader.delete_case(tmp_path, "del-me") is False

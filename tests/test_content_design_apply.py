"""Tests for the implement-content-design change.

Covers the artifacts in openspec/changes/implement-content-design/:

- content-sync-pipeline delta: reconcile sync semantics, exp_multiplier zero
  preservation, skill row import contract (0.x additive, no trigger_rate on
  ultimates, same-name merge keeps the existing id).
- skill-system delta: route multiplier applied to technique loadouts, heart
  method route equip check, comprehension pool sourcing from heart methods.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_module, load_package_module

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

_sync_mod = load_module("sync_content_to_config", "scripts/sync_content_to_config.py")
_build_heart = _sync_mod._build_heart
_build_skill = _sync_mod._build_skill
_validate_ultimate = _sync_mod._validate_ultimate
_merge_skill = _sync_mod._merge_skill
_reconcile_list = _sync_mod._reconcile_list
_reconcile_groups = _sync_mod._reconcile_groups

_core_pkg = load_package_module(
    "core/__init__.py", "astrbot_plugin_monixiuxian2_2.core"
)
_config_mod = load_package_module(
    "config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager"
)
ConfigManager = _config_mod.ConfigManager
_skill_mod = load_package_module(
    "core/skill_manager.py", "astrbot_plugin_monixiuxian2_2.core.skill_manager"
)
SkillManager = _skill_mod.SkillManager
_handler_mod = load_package_module(
    "handlers/equipment_handler.py",
    "astrbot_plugin_monixiuxian2_2.handlers.equipment_handler",
)
EquipmentHandler = _handler_mod.EquipmentHandler


@pytest.fixture
def config_manager():
    return ConfigManager(PLUGIN_ROOT)


class FakeDbExt:
    """In-memory player_skills store mirroring database_extended CRUD."""

    def __init__(self):
        self.player_skills: dict[tuple[str, str], dict] = {}
        self.get_user_cd = AsyncMock(return_value=None)
        self.get_active_loan = AsyncMock(return_value=None)

    async def is_skill_learned(self, user_id: str, skill_id: str) -> bool:
        return (user_id, skill_id) in self.player_skills

    async def get_star_level(self, user_id: str, skill_id: str) -> int:
        entry = self.player_skills.get((user_id, skill_id))
        return entry["star_level"] if entry else 1

    async def learn_or_star_up(
        self,
        user_id: str,
        skill_id: str,
        source: str = "",
        max_star: int = 3,
        max_star_exp_compensation: int = 0,
    ) -> tuple[bool, int]:
        key = (user_id, skill_id)
        if key not in self.player_skills:
            self.player_skills[key] = {"star_level": 1, "source": source}
            return True, 1
        star = min(self.player_skills[key]["star_level"] + 1, max_star)
        self.player_skills[key]["star_level"] = star
        return False, star


class FakePlayer:
    def __init__(self, **kwargs):
        self.user_id = kwargs.get("user_id", "u1")
        self.state = kwargs.get("state", "空闲")
        self.weapon = kwargs.get("weapon", "")
        self.armor = kwargs.get("armor", "")
        self.main_technique = kwargs.get("main_technique", "")
        self.techniques = kwargs.get("techniques", "[]")
        self.storage_ring_items = kwargs.get("storage_ring_items", "{}")
        self.study_target = kwargs.get("study_target", "")
        self.cultivation_type = kwargs.get("cultivation_type", "灵修")

    def get_techniques_list(self):
        try:
            return json.loads(self.techniques)
        except json.JSONDecodeError:
            return []

    def set_techniques_list(self, techniques_list):
        self.techniques = json.dumps(techniques_list, ensure_ascii=False)

    def get_storage_ring_items(self):
        try:
            return json.loads(self.storage_ring_items)
        except json.JSONDecodeError:
            return {}


def test_build_heart_keeps_zero_exp_multiplier():
    """exp_multiplier 0.0 must survive sync (double-exp regression, review m3)."""
    row = {
        "id": "h1",
        "name": "测试心法",
        "description": "d",
        "rank": "凡品",
        "required_level_index": "0",
        "passive_bonus_json": "{}",
        "exp_multiplier": "0.0",
        "skill_pool_json": "[]",
        "route": "通用",
        "shop_weight": "100",
        "ref_source": "测试",
        "design_note": "",
        "status": "draft",
    }
    entry = _build_heart(row, [])
    assert entry["exp_multiplier"] == 0.0
    row["exp_multiplier"] = ""
    assert _build_heart(row, [])["exp_multiplier"] == 0.0
    row["exp_multiplier"] = "0.08"
    assert _build_heart(row, [])["exp_multiplier"] == 0.08


# ---------------------------------------------------------------------------
# 6.2 skill row import contract
# ---------------------------------------------------------------------------


def _skill_row(**overrides):
    row = {
        "id": "draft_test",
        "name": "测试功法",
        "description": "d",
        "pool": "通用功法池",
        "trigger_condition": "attack",
        "trigger_name": "测试触发",
        "trigger_rate": "0.2",
        "effect_type": "damage_bonus",
        "effect_value": "0.5",
        "ultimate_json": "null",
        "route_mult_ling": "1.0",
        "route_mult_ti": "0.8",
        "learn_coefficient": "1.0",
        "ref_source": "测试",
        "design_note": "",
        "status": "draft",
    }
    row.update(overrides)
    return row


def test_build_skill_maps_persisted_keys():
    """Trigger skills keep trigger_condition; ultimates and route map cleanly."""
    entry = _build_skill(_skill_row(), [])
    trig = entry["trigger_skill"]
    assert trig["trigger_condition"] == "attack"
    assert trig["trigger_rate"] == 0.2
    assert trig["effect_type"] == "damage_bonus"
    assert trig["effect_value"] == 0.5
    assert entry["route_multiplier"] == {"灵修": 1.0, "体修": 0.8}
    assert entry["_pool"] == "通用功法池"
    # Merge-only / design metadata never persists into the entry
    for meta in ("learn_coefficient", "ref_source", "design_note", "status"):
        assert meta not in entry


def test_build_skill_rejects_bad_contracts():
    errors = []
    assert _build_skill(_skill_row(trigger_rate="0"), errors) is None
    assert _build_skill(_skill_row(trigger_rate="1.5"), errors) is None
    assert _build_skill(_skill_row(trigger_condition="ambush"), errors) is None
    assert _build_skill(_skill_row(effect_type="teleport"), errors) is None
    # optional-key contract violations are collected as errors, not fatal
    assert _build_skill(_skill_row(duration="0"), errors) is not None
    assert _build_skill(_skill_row(pierce_rate="1.5"), errors) is not None
    assert len(errors) == 6


def test_build_skill_collects_malformed_optional_keys():
    """Malformed optional skill keys must be collected as errors, not crash
    the sync (review fix: try/except around _num)."""
    errors = []
    entry = _build_skill(_skill_row(duration="abc", tick_rate="fast"), errors)
    assert entry is not None
    assert any("duration must be numeric, got 'abc'" in e for e in errors)
    assert any("tick_rate must be numeric, got 'fast'" in e for e in errors)


def test_build_skill_rejects_unknown_vampire():
    """vampire only accepts 1/true/yes or 0/false/no; anything else is an
    error, and explicit falsy spellings pass without setting the key."""
    errors = []
    entry = _build_skill(_skill_row(vampire="maybe"), errors)
    assert entry is not None
    assert any(
        "vampire must be 1/true/yes or 0/false/no, got 'maybe'" in e for e in errors
    )
    errors2 = []
    entry2 = _build_skill(_skill_row(vampire="0"), errors2)
    assert entry2 is not None
    assert errors2 == []
    assert "vampire" not in entry2["trigger_skill"]


def test_validate_ultimate_forbids_trigger_rate_and_requires_effect():
    errors = []
    assert _validate_ultimate("null", "ctx", errors) is None
    ult = _validate_ultimate(
        json.dumps(
            {
                "effect_type": "damage_bonus",
                "effect_value": 2.0,
                "min_action_index": 3,
                "trigger_self_hp_below": 0.4,
            }
        ),
        "ctx",
        errors,
    )
    assert ult["effect_value"] == 2.0
    # Mandatory-cast contract: no trigger_rate, ever
    assert (
        _validate_ultimate(
            json.dumps(
                {
                    "effect_type": "damage_bonus",
                    "effect_value": 2.0,
                    "trigger_rate": 1.0,
                }
            ),
            "ctx",
            errors,
        )
        is None
    )
    assert (
        _validate_ultimate(json.dumps({"effect_type": "damage_bonus"}), "ctx", errors)
        is None
    )
    assert len(errors) == 2


# ---------------------------------------------------------------------------
# 6.3 skill merge + reconcile
# ---------------------------------------------------------------------------


def test_merge_skill_update_keeps_existing_id():
    """Same-name skill updates fields but preserves the persisted id."""
    groups = {
        "灵修专属": [
            {
                "id": "spirit_001",
                "name": "万剑归宗",
                "ultimate": {"effect_value": 2.0},
                "route_multiplier": {"灵修": 1.2, "体修": 0.8},
            }
        ]
    }
    payload = {
        "id": "draft_new",
        "name": "万剑归宗",
        "ultimate": {"effect_value": 2.0},
        "route_multiplier": {"灵修": 1.2, "体修": 0.8},
        "_pool": "灵修专属",
    }
    action, diffs = _merge_skill(groups, payload)
    assert action == "UPDATE"
    assert groups["灵修专属"][0]["id"] == "spirit_001"
    assert diffs == []


def test_merge_skill_add_to_group():
    groups = {}
    payload = {
        "id": "draft_a",
        "name": "新功法",
        "route_multiplier": {"灵修": 1.0, "体修": 1.0},
        "_pool": "体修专属",
    }
    action, _ = _merge_skill(groups, payload)
    assert action == "ADD"
    assert groups["体修专属"][0]["name"] == "新功法"
    assert "_pool" not in groups["体修专属"][0]


def test_reconcile_filters_config_to_imported_names():
    entries = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    deleted = _reconcile_list(entries, {"A", "C"})
    assert deleted == ["B"]
    assert [e["name"] for e in entries] == ["A", "C"]

    groups = {"通用": [{"name": "A"}, {"name": "B"}], "体修专属": [{"name": "C"}]}
    deleted = _reconcile_groups(groups, {"A"})
    assert deleted == ["B", "C"]
    assert [e["name"] for e in groups["通用"]] == ["A"]
    assert groups["体修专属"] == []


def test_merge_skill_clears_stale_trigger_and_ultimate():
    """A row without trigger/ultimate keys must clear stale ones in config.

    Review fix (ocr medium): previously the merge only overwrote keys present
    in the payload, so removing a trigger/ultimate from the CSV left the old
    block live in config/skills.json while sync reported "no field changes".
    """
    groups = {
        "通用功法池": [
            {
                "id": "s1",
                "name": "旧技能",
                "trigger_skill": {
                    "name": "旧触发",
                    "trigger_condition": "on_attack",
                    "trigger_rate": 0.3,
                    "effect_type": "damage_bonus",
                    "effect_value": 0.5,
                },
                "ultimate": {"effect_value": 2.0},
                "route_multiplier": {"灵修": 1.0, "体修": 1.0},
            }
        ]
    }
    row = {
        "pool": "通用功法池",
        "id": "s1",
        "name": "旧技能",
        "trigger_name": "",
        "trigger_condition": "",
        "trigger_rate": "",
        "effect_type": "",
        "effect_value": "",
        "route_mult_ling": "1.0",
        "route_mult_ti": "1.0",
        "learn_coefficient": "",
        "ultimate_json": "",
        "description": "d",
        "ref_source": "t",
        "design_note": "",
        "status": "draft",
    }
    payload = _build_skill(row, [])
    assert payload["trigger_skill"] is None
    assert payload["ultimate"] is None
    action, diffs = _merge_skill(groups, payload)
    assert action == "UPDATE"
    existing = groups["通用功法池"][0]
    assert existing["trigger_skill"] is None
    assert existing["ultimate"] is None
    assert any("trigger_skill" in d and "-> null" in d for d in diffs)
    assert any("ultimate" in d and "-> null" in d for d in diffs)


def test_merge_skill_moves_pool_group():
    """Changing the pool column must relocate the entry between groups.

    Review fix (ocr medium): the UPDATE branch previously kept the entry in
    its old group, so a skill moved out of 通用功法池 stayed selectable as a
    universal skill by the runtime pool filter.
    """
    groups = {
        "通用功法池": [
            {
                "id": "s2",
                "name": "移池技能",
                "route_multiplier": {"灵修": 1.0, "体修": 1.0},
            }
        ]
    }
    payload = {
        "id": "s2",
        "name": "移池技能",
        "route_multiplier": {"灵修": 1.0, "体修": 1.0},
        "_pool": "体修专属",
    }
    action, diffs = _merge_skill(groups, payload)
    assert action == "UPDATE"
    assert groups["通用功法池"] == []
    moved = groups["体修专属"][0]
    assert moved["name"] == "移池技能"
    assert moved["id"] == "s2"
    assert any("_pool" in d for d in diffs)


def test_empty_import_aborts_without_writing(monkeypatch, tmp_path):
    """Zero draft/final rows in one CSV must abort a non-dry-run write.

    Review fix (ocr low): an empty import set would otherwise make reconcile
    delete every entry of that table while the budget gate passes trivially.
    """
    import shutil

    design_dir = tmp_path / "design"
    config_dir = tmp_path / "config"
    design_dir.mkdir()
    config_dir.mkdir()
    # heart/skills tables stay valid; weapons.csv carries only a legacy row.
    for fname in ("heart_methods.csv", "skills.csv"):
        shutil.copy(
            PLUGIN_ROOT / "design_docs" / "content-design" / fname, design_dir / fname
        )
    (design_dir / "weapons.csv").write_text(
        "id,name,weapon_category,size_class,rank,required_level_index,base_damage,"
        "weapon_coefficient_k,bonus_damage,armor_value,price,shop_weight,route_mult_ling,"
        "route_mult_ti,trigger_skills_json,description,ref_source,design_note,status\n"
        "legacy_w,旧武器,剑,单手,凡品,0,9,0.5,0,15,199,1000,1.0,1.0,[],desc,ref,,legacy\n",
        encoding="utf-8",
    )
    original = {
        fname: (PLUGIN_ROOT / "config" / fname).read_text(encoding="utf-8")
        for fname in ("weapons.json", "heart_methods.json", "skills.json")
    }
    for fname, text in original.items():
        (config_dir / fname).write_text(text, encoding="utf-8")
    monkeypatch.setattr(_sync_mod, "DESIGN_DIR", design_dir)
    monkeypatch.setattr(_sync_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr("sys.argv", ["sync_content_to_config.py"])
    assert _sync_mod.main() == 1
    for fname, text in original.items():
        assert (config_dir / fname).read_text(encoding="utf-8") == text


# ---------------------------------------------------------------------------
# 6.4 route multiplier in battle loadouts
# ---------------------------------------------------------------------------


def _make_skill_mgr(config_manager, user="u1"):
    db = MagicMock()
    db.ext = FakeDbExt()
    db.update_player = AsyncMock()
    db.get_player_by_id = AsyncMock(return_value=FakePlayer(user_id=user))
    return SkillManager(config_manager, db), db


def test_route_multiplier_scales_trigger_rate_per_route(config_manager):
    """体修 gets 1.2x on 铁山靠 (counter), 灵修 gets 0.8x."""
    for user, route, expected in (
        ("u_ti", "体修", 0.2 * 1.2),
        ("u_ling", "灵修", 0.2 * 0.8),
    ):
        mgr, db = _make_skill_mgr(config_manager, user)
        db.ext.player_skills[(user, "draft_tieshan")] = {"star_level": 1}
        player = FakePlayer(
            user_id=user,
            cultivation_type=route,
            techniques='["铁山靠"]',
            main_technique="长春功",
        )
        loadout = asyncio.run(mgr.get_battle_loadout(player))
        trig = loadout["trigger_skills"][0]
        assert trig["trigger_rate"] == pytest.approx(expected)
        assert trig["effect_value"] == 1.0  # value unchanged by route


def test_route_multiplier_scales_ultimate_value(config_manager):
    """灵修 万剑归宗 ultimate effect_value = 2.0 × 1.2."""
    mgr, db = _make_skill_mgr(config_manager)
    db.ext.player_skills[("u1", "spirit_001")] = {"star_level": 1}
    player = FakePlayer(
        user_id="u1",
        cultivation_type="灵修",
        techniques='["万剑归宗"]',
        main_technique="长春功",
    )
    loadout = asyncio.run(mgr.get_battle_loadout(player))
    ult = loadout["ultimates"][0]
    assert ult["effect_value"] == pytest.approx(2.0 * 1.2)
    assert ult["trigger_rate"] == 1.0  # mandatory-cast kept


def test_route_multiplier_compounds_with_star_level(config_manager):
    """Star bonus applies first, route multiplier second (rate capped at 1.0)."""
    mgr, db = _make_skill_mgr(config_manager)
    db.ext.player_skills[("u1", "draft_leizhen")] = {"star_level": 2}
    player = FakePlayer(
        user_id="u1",
        cultivation_type="灵修",
        techniques='["雷震剑诀"]',
        main_technique="长春功",
    )
    loadout = asyncio.run(mgr.get_battle_loadout(player))
    trig = loadout["trigger_skills"][0]
    assert trig["trigger_rate"] == pytest.approx(0.12 * 1.1 * 1.2)
    assert trig["effect_value"] == pytest.approx(1.5 * 1.1)


def test_route_multiplier_defaults_to_one(config_manager):
    """Skills without route_multiplier export unchanged (compat)."""
    mgr, db = _make_skill_mgr(config_manager)
    db.ext.player_skills[("u1", "common_001")] = {"star_level": 1}
    # Strip route_multiplier from the shared def to simulate old config
    original = mgr.config_manager.skills_data["基础吐纳"].get("route_multiplier")
    mgr.config_manager.skills_data["基础吐纳"].pop("route_multiplier", None)
    try:
        player = FakePlayer(
            user_id="u1",
            cultivation_type="体修",
            techniques='["基础吐纳"]',
            main_technique="长春功",
        )
        loadout = asyncio.run(mgr.get_battle_loadout(player))
        assert loadout["trigger_skills"][0]["trigger_rate"] == pytest.approx(0.15)
    finally:
        mgr.config_manager.skills_data["基础吐纳"]["route_multiplier"] = original


# ---------------------------------------------------------------------------
# 6.5 heart method route equip check
# ---------------------------------------------------------------------------


def _make_equip_handler(config_manager, player_kwargs=None):
    db = MagicMock()
    db.ext = FakeDbExt()
    db.update_player = AsyncMock()
    db.get_player_by_id = AsyncMock(return_value=FakePlayer(**(player_kwargs or {})))
    return EquipmentHandler(db, config_manager), db


async def _equip_result(handler, item_name):
    event = MagicMock()
    # Real handlers yield the message they pass to plain_result; capture it
    event.plain_result = MagicMock(side_effect=lambda msg: msg)
    results = []
    async for m in handler.handle_equip_item(event, item_name):
        results.append(m)
    return results


@pytest.mark.asyncio
async def test_heart_route_mismatch_rejected(config_manager):
    """体修 player equipping a 灵修 heart method is rejected with a route hint."""
    handler, _ = _make_equip_handler(config_manager, {"cultivation_type": "体修"})
    results = await _equip_result(handler, "烈火功")
    msg = results[0]
    assert "适用于【灵修】路线" in msg
    assert "体修" in msg


@pytest.mark.asyncio
async def test_heart_route_match_passes_check(config_manager):
    """灵修 player equipping 烈火功 passes the route check (fails later at ring)."""
    handler, _ = _make_equip_handler(config_manager, {"cultivation_type": "灵修"})
    results = await _equip_result(handler, "烈火功")
    msg = results[0]
    assert "储物戒中没有【烈火功】" in msg  # passed route check


@pytest.mark.asyncio
async def test_universal_heart_always_allowed(config_manager):
    """通用 heart methods are equippable by any route."""
    handler, _ = _make_equip_handler(config_manager, {"cultivation_type": "体修"})
    results = await _equip_result(handler, "长春功")
    msg = results[0]
    assert "储物戒中没有【长春功】" in msg


# ---------------------------------------------------------------------------
# 6.6 comprehension pool from heart method skill pools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_builds_from_heart_method(config_manager):
    """长春功 pool: 基础吐纳 (coeff 1.0) + 铁布衫 (coeff 0.8)."""
    mgr, db = _make_skill_mgr(config_manager)
    player = FakePlayer(main_technique="长春功")
    pool = await mgr._build_comprehension_pool(player, "cultivation")
    assert [p["skill_id"] for p in pool] == ["common_001", "common_002"]
    assert [p["coefficient"] for p in pool] == [1.0, 0.8]
    assert all(p["source"] == "heart_method" for p in pool)


@pytest.mark.asyncio
async def test_pool_keeps_learned_for_star_up_and_filters_study_target(config_manager):
    """Heart-method pool keeps learned skills (duplicates star up); the study
    target is excluded once learned (it is a learn-once channel)."""
    mgr, db = _make_skill_mgr(config_manager)
    db.ext.player_skills[("u1", "common_001")] = {"star_level": 1}
    player = FakePlayer(main_technique="长春功", study_target="draft_kuangfeng")
    pool = await mgr._build_comprehension_pool(player, "cultivation")
    ids = [p["skill_id"] for p in pool]
    # Learned heart-method skills stay (duplicates star up on re-roll)
    assert "common_001" in ids
    assert "common_002" in ids
    # Unlearned study target joins the pool once
    assert ids.count("draft_kuangfeng") == 1
    assert pool[-1]["source"] == "study_target"
    # Already-learned study target is not re-added
    db.ext.player_skills[("u1", "draft_kuangfeng")] = {"star_level": 1}
    pool = await mgr._build_comprehension_pool(player, "cultivation")
    assert "draft_kuangfeng" not in [p["skill_id"] for p in pool]


def test_roll_comprehension_rate_by_coefficient(config_manager, monkeypatch):
    mgr, db = _make_skill_mgr(config_manager)
    pool = [
        {
            "skill_id": "common_001",
            "weight": 1.0,
            "coefficient": 1.0,
            "source": "heart_method",
        },
        {
            "skill_id": "common_002",
            "weight": 1.0,
            "coefficient": 0.8,
            "source": "heart_method",
        },
    ]
    monkeypatch.setattr("random.choice", lambda seq: pool[1])
    # coeff 0.8 × base 0.20 = 0.16
    monkeypatch.setattr("random.random", lambda: 0.01)
    assert mgr._roll_comprehension(pool, 0.20)["skill_id"] == "common_002"
    monkeypatch.setattr("random.random", lambda: 0.99)
    assert mgr._roll_comprehension(pool, 0.20) is None


@pytest.mark.asyncio
async def test_breakthrough_success_learns_from_heart_pool(config_manager, monkeypatch):
    mgr, db = _make_skill_mgr(config_manager)
    player = FakePlayer(main_technique="长春功")
    # Pool roll succeeds (0.01 < 0.20), universal 5% roll misses (0.99)
    seq = [0.01, 0.99]
    monkeypatch.setattr("random.random", lambda: seq.pop(0))
    result = await mgr.roll_breakthrough_success_comprehension(player)
    assert result is not None
    assert result["id"] in ("common_001", "common_002")
    assert ("u1", result["id"]) in db.ext.player_skills
    assert result["learn_source"] == "heart_method"


@pytest.mark.asyncio
async def test_breakthrough_universal_replace(config_manager, monkeypatch):
    mgr, db = _make_skill_mgr(config_manager)
    player = FakePlayer(main_technique="长春功")
    # Pool roll succeeds AND universal roll hits; choice picks a universal skill
    seq = [0.01, 0.01]
    monkeypatch.setattr("random.random", lambda: seq.pop(0))

    def fake_choice(seq_):
        # _roll_comprehension draws from heart-method pool entries (no _group);
        # _pick_universal_skill draws from filtered universal skills
        for s in seq_:
            if s.get("_group") == "通用功法池":
                return s
        return seq_[0]

    monkeypatch.setattr("random.choice", fake_choice)
    result = await mgr.roll_breakthrough_success_comprehension(player)
    assert result["id"] != "common_002"
    assert result["learn_source"] == "universal"


@pytest.mark.asyncio
async def test_no_heart_method_uses_universal_fallback(config_manager, monkeypatch):
    mgr, db = _make_skill_mgr(config_manager)
    player = FakePlayer(main_technique="")
    # Normal comprehension is skipped entirely without a heart method
    assert await mgr.roll_breakthrough_success_comprehension(player) is None
    # Independent 3% universal fallback fires
    monkeypatch.setattr("random.random", lambda: 0.01)
    monkeypatch.setattr(
        "random.choice",
        lambda seq_: next(s for s in seq_ if s.get("_group") == "通用功法池"),
    )
    result = await mgr.roll_universal_pool_breakthrough(player, success=True)
    assert result is not None
    assert ("u1", result["id"]) in db.ext.player_skills

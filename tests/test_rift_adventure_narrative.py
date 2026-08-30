"""Tests for the rift/adventure narrative carriers (externalize-narrative-texts §5).

Covers:
- rift ``description`` shown in the list UI when configured, absent otherwise;
- ``settlement_desc`` rendered in the exploration settlement message;
- legacy rift configs without the new fields loading fine (empty defaults);
- the explore-event pool read from config with the RIFT_CONFIG default fallback;
- adventure ``desc_variants`` bucket selection (current segment + 通用 merged,
  route filtering) and the verbatim ``desc`` fallback;
- the legacy-encounter template cluster converging adventure/rift/sect copy.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import load_module, load_package_module

_rift_mod = load_module("rift_manager_ran", "managers/rift_manager.py")
RiftManager = _rift_mod.RiftManager
RIFT_CONFIG = _rift_mod.RIFT_CONFIG

_adv_mod = load_module("adventure_manager_ran", "managers/adventure_manager.py")
AdventureManager = _adv_mod.AdventureManager

_nd = load_package_module(
    "data/narrative_defaults/__init__.py",
    "astrbot_plugin_monixiuxian2_2.data.narrative_defaults",
)
DEFAULT_NARRATIVE_CONFIG = _nd.DEFAULT_NARRATIVE_CONFIG

# The standalone rift shim registers models_extended under this name.
from models_extended import UserStatus  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


class FakeRiftConfigManager:
    """Minimal ConfigManager stub carrying only what RiftManager reads."""

    def __init__(self, rift_config: dict):
        self.rift_config = rift_config

    def get_level_name(self, level_index: int, cultivation_type: str = "灵修") -> str:
        return f"境界{level_index}"

    def is_pill(self, item_name: str) -> bool:
        return False


def _fake_db_rift(rift_id: int = 1, name: str = "青云秘境"):
    """DB-row stand-in for a rift (attributes + get_rewards)."""
    rift = MagicMock()
    rift.rift_id = rift_id
    rift.rift_name = name
    rift.required_level = 0
    rift.rift_level = 1
    rift.get_rewards.return_value = {"exp": [1000, 1000], "gold": [500, 500]}
    return rift


def _make_finished_rift_db(rift_id: int = 1):
    """DB mock positioned at a finished rift exploration for ``rift_id``."""
    db = MagicMock()
    cd = MagicMock()
    cd.type = UserStatus.EXPLORING
    cd.scheduled_time = 0
    cd.create_time = 0
    cd.get_extra_data.return_value = {"rift_id": rift_id, "rift_level": 1}
    db.ext.get_user_cd = AsyncMock(return_value=cd)
    db.ext.get_rift_by_id = AsyncMock(return_value=_fake_db_rift(rift_id))
    db.ext.set_user_free = AsyncMock()
    db.update_player = AsyncMock()
    player = MagicMock()
    player.experience = 0
    player.gold = 0
    db.get_player_by_id = AsyncMock(return_value=player)
    return db


class _StubPve:
    """PVE stub: skips encounter combat, fixes the guardian-challenge outcome."""

    def __init__(self, won: bool):
        self.won = won

    async def trigger_pve_combat(self, *args, **kwargs):
        return None

    async def challenge_legacy_guardian(self, player):
        return self.won, "守护者战斗详情"


class _StubImpart:
    """Impart stub returning a fixed legacy instance."""

    def __init__(self, type_name: str, instance_id: int):
        self.type_name = type_name
        self.instance_id = instance_id

    def get_type_name(self, legacy_type: str) -> str:
        return self.type_name

    async def create_legacy(self, user_id, legacy_type, **kwargs):
        return SimpleNamespace(id=self.instance_id)


# ===== 5.1 秘境 description / settlement_desc =====


@pytest.mark.asyncio
async def test_rift_list_shows_description_when_configured():
    """A configured ``description`` appears under the rift name in the list UI."""
    cfg = {
        "rifts": [
            {
                "id": 1,
                "name": "青云秘境",
                "level": 0,
                "exp_range": [500, 1500],
                "gold_range": [200, 800],
                "description": "云雾缭绕的入门秘境。",
            }
        ]
    }
    db = MagicMock()
    db.ext.get_all_rifts = AsyncMock(return_value=[_fake_db_rift(1)])
    mgr = RiftManager(db, FakeRiftConfigManager(cfg))

    success, msg = await mgr.list_rifts()

    assert success
    assert "云雾缭绕的入门秘境。" in msg


@pytest.mark.asyncio
async def test_rift_list_omits_description_for_legacy_entries():
    """Old entries without ``description`` load fine and render no extra line."""
    cfg = {
        "rifts": [
            {
                "id": 1,
                "name": "青云秘境",
                "level": 0,
                "exp_range": [500, 1500],
                "gold_range": [200, 800],
            }
        ]
    }
    db = MagicMock()
    db.ext.get_all_rifts = AsyncMock(return_value=[_fake_db_rift(1)])
    mgr = RiftManager(db, FakeRiftConfigManager(cfg))

    success, msg = await mgr.list_rifts()

    assert success
    lines = msg.splitlines()
    name_idx = next(i for i, line in enumerate(lines) if "【青云秘境】" in line)
    # The line right after the name stays the requirement line (no description).
    assert lines[name_idx + 1].startswith("  等级要求")


@pytest.mark.asyncio
async def test_rift_settlement_renders_settlement_desc():
    """A configured ``settlement_desc`` is prepended to the settlement body."""
    cfg = {
        "rifts": [
            {
                "id": 1,
                "name": "青云秘境",
                "level": 0,
                "exp_range": [500, 1500],
                "gold_range": [200, 800],
                "settlement_desc": "此行云雾散尽，有所得亦有所悟。",
            }
        ],
        "explore_events": [{"desc": "固定事件", "item_chance": 0}],
    }
    mgr = RiftManager(_make_finished_rift_db(1), FakeRiftConfigManager(cfg))

    success, msg, _ = await mgr.finish_exploration("u1")

    assert success
    assert "此行云雾散尽，有所得亦有所悟。\n\n固定事件" in msg


@pytest.mark.asyncio
async def test_rift_settlement_unchanged_without_settlement_desc():
    """Entries lacking ``settlement_desc`` produce the pre-change message shape."""
    cfg = {
        "rifts": [
            {
                "id": 1,
                "name": "青云秘境",
                "level": 0,
                "exp_range": [500, 1500],
                "gold_range": [200, 800],
            }
        ],
        "explore_events": [{"desc": "固定事件", "item_chance": 0}],
    }
    mgr = RiftManager(_make_finished_rift_db(1), FakeRiftConfigManager(cfg))

    success, msg, _ = await mgr.finish_exploration("u1")

    assert success
    assert "━━━━━━━━━━━━━━━\n\n固定事件" in msg


# ===== 5.2 探索事件池外移 =====


@pytest.mark.asyncio
async def test_explore_events_come_from_config():
    """The settlement event is drawn from the configured explore_events pool."""
    cfg = {
        "rifts": [],
        "explore_events": [{"desc": "配置化事件甲", "item_chance": 0}],
    }
    mgr = RiftManager(_make_finished_rift_db(1), FakeRiftConfigManager(cfg))

    success, msg, reward_data = await mgr.finish_exploration("u1")

    assert success
    assert reward_data["event"] == "配置化事件甲"
    assert "配置化事件甲" in msg


@pytest.mark.asyncio
async def test_explore_events_fall_back_to_rift_default_pool():
    """Old configs without explore_events use the RIFT_CONFIG default pool."""
    cfg = {"rifts": []}  # legacy shape: no explore_events key
    mgr = RiftManager(_make_finished_rift_db(1), FakeRiftConfigManager(cfg))

    with patch.object(mgr, "_roll_rift_drops", new=AsyncMock(return_value=[])):
        success, _msg, reward_data = await mgr.finish_exploration("u1")

    assert success
    default_descs = {e["desc"] for e in RIFT_CONFIG["explore_events"]}
    assert reward_data["event"] in default_descs


def test_repo_rift_config_explore_events_match_original_pool():
    """The committed config pool is a verbatim copy of the original 5 variants."""
    with open(PLUGIN_ROOT / "config" / "rift_config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    assert cfg["explore_events"] == [
        {"desc": "你发现了一处灵泉，修为大增！", "item_chance": 70},
        {"desc": "你在秘境中击败了一只妖兽！", "item_chance": 80},
        {"desc": "你找到了一个隐藏的宝箱！", "item_chance": 100},
        {"desc": "你领悟了一些修炼心得。", "item_chance": 40},
        {"desc": "你在秘境中遇到了前辈留下的传承！", "item_chance": 90},
    ]
    for rift in cfg["rifts"]:
        assert rift["description"] == ""
        assert rift["settlement_desc"] == ""


# ===== 5.3 传承之地文案收敛 =====


def test_legacy_encounter_fragment_defaults_are_verbatim():
    """The embedded cluster matches the original strings (rift wording chosen)."""
    scenes = DEFAULT_NARRATIVE_CONFIG["legacy_encounter"]
    assert scenes["encounter_win"] == (
        "\n\n🗿 你偶遇上古传承之地，战胜了守护者！\n{battle_msg}\n"
        "🌟 获得【{name}】#{instance_id}，发送「激活传承」可开始修炼解锁。"
    )
    assert scenes["encounter_lose"] == (
        "\n\n🗿 你偶遇上古传承之地，但未能战胜守护者。\n{battle_msg}"
    )
    assert scenes["claim_win"] == (
        "🗿 你战胜了守护者！\n{battle_msg}\n"
        "🌟 获得宗门传承【{name}】#{instance_id}！\n"
        "⚠️ 宗门传承不可被夺取，但离宗时将自动归还宗门。\n"
        "💡 发送「激活传承 {instance_id}」开始修炼解锁等阶奖励。"
    )
    assert scenes["claim_lose"] == (
        "🗿 领取【{name}】需先战胜传承之地守护者。\n"
        "{battle_msg}\n"
        "此次未领取成功，不占用领取名额，可择日再试。"
    )


@pytest.mark.asyncio
async def test_adventure_legacy_uses_converged_encounter_copy():
    """Adventure 偶遇制 win/lose messages render from the shared cluster."""
    adv = AdventureManager(MagicMock())
    adv.legacy_chance = 1.0
    adv.impart_mgr = _StubImpart("历练传承", 7)
    adv.pve_combat_mgr = _StubPve(won=True)

    msg = await adv._maybe_trigger_legacy(SimpleNamespace(user_id="u1"))
    assert msg == (
        "\n\n🗿 你偶遇上古传承之地，战胜了守护者！\n守护者战斗详情\n"
        "🌟 获得【历练传承】#7，发送「激活传承」可开始修炼解锁。"
    )

    adv.pve_combat_mgr = _StubPve(won=False)
    msg = await adv._maybe_trigger_legacy(SimpleNamespace(user_id="u1"))
    assert msg == "\n\n🗿 你偶遇上古传承之地，但未能战胜守护者。\n守护者战斗详情"


@pytest.mark.asyncio
async def test_rift_legacy_uses_converged_encounter_copy():
    """Rift 偶遇制 win/lose messages render from the shared cluster."""
    cfg = {
        "legacy_chance": 1.0,
        "rifts": [],
        "explore_events": [{"desc": "固定事件", "item_chance": 0}],
    }
    mgr = RiftManager(_make_finished_rift_db(1), FakeRiftConfigManager(cfg))
    mgr.pve_combat_mgr = _StubPve(won=True)
    mgr.impart_mgr = _StubImpart("秘境传承", 42)

    success, msg, _ = await mgr.finish_exploration("u1")

    assert success
    assert (
        "\n\n🗿 你偶遇上古传承之地，战胜了守护者！\n守护者战斗详情\n"
        "🌟 获得【秘境传承】#42，发送「激活传承」可开始修炼解锁。" in msg
    )

    mgr = RiftManager(_make_finished_rift_db(1), FakeRiftConfigManager(cfg))
    mgr.pve_combat_mgr = _StubPve(won=False)
    mgr.impart_mgr = _StubImpart("秘境传承", 42)

    success, msg, _ = await mgr.finish_exploration("u1")

    assert success
    assert "🗿 你偶遇上古传承之地，但未能战胜守护者。\n守护者战斗详情" in msg


# ===== 5.5/5.6/5.7 历练事件 desc_variants 分桶 =====


def _adv():
    """AdventureManager instance (config file loads from the repo)."""
    return AdventureManager(MagicMock())


def test_select_event_desc_falls_back_to_desc_without_variants():
    """Legacy events without desc_variants keep the verbatim desc."""
    event = {"key": "e1", "desc": "原始兜底文案。"}
    player = SimpleNamespace(level_index=5, cultivation_type="灵修")
    assert _adv()._select_event_desc(event, player) == "原始兜底文案。"


def test_select_event_desc_merges_current_segment_and_common_buckets():
    """Pool = current segment bucket + 通用 bucket (design D7)."""
    event = {
        "key": "e1",
        "desc": "兜底",
        "desc_variants": {"通用": ["通用句"], "练气": ["练气句"], "筑基": ["筑基句"]},
    }
    player = SimpleNamespace(level_index=5, cultivation_type="灵修")  # 练气段
    assert _adv()._select_event_desc(event, player) in {"通用句", "练气句"}

    player = SimpleNamespace(level_index=12, cultivation_type="灵修")  # 筑基段
    assert _adv()._select_event_desc(event, player) in {"通用句", "筑基句"}


def test_select_event_desc_uncovered_segment_uses_common_bucket_only():
    """Levels outside the season-1 segments (e.g. Lv45) only draw from 通用."""
    event = {
        "key": "e1",
        "desc": "兜底",
        "desc_variants": {"通用": ["通用句"], "练气": ["练气句"]},
    }
    player = SimpleNamespace(level_index=45, cultivation_type="灵修")
    assert _adv()._select_event_desc(event, player) == "通用句"


def test_select_event_desc_empty_merged_pool_falls_back_to_desc():
    """No 通用/current-segment entries (or all route-filtered) → verbatim desc."""
    event = {
        "key": "e1",
        "desc": "原始兜底文案。",
        "desc_variants": {"筑基": ["筑基句"]},  # 练气段玩家取不到任何桶
    }
    player = SimpleNamespace(level_index=5, cultivation_type="灵修")
    assert _adv()._select_event_desc(event, player) == "原始兜底文案。"

    route_tagged = {
        "key": "e2",
        "desc": "原始兜底文案。",
        "desc_variants": {"通用": [{"text": "体修专属句", "route": "体修"}]},
    }
    assert _adv()._select_event_desc(route_tagged, player) == "原始兜底文案。"
    body_player = SimpleNamespace(level_index=5, cultivation_type="体修")
    assert _adv()._select_event_desc(route_tagged, body_player) == "体修专属句"


def test_repo_adventure_config_events_keep_verbatim_desc_fallback():
    """Every committed event keeps its desc fallback; new fields stay optional."""
    with open(PLUGIN_ROOT / "config" / "adventure_config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    assert cfg["event_groups"], "adventure_config.json 应有事件分组"
    for group_key, events in cfg["event_groups"].items():
        for event in events:
            assert isinstance(event.get("desc"), str) and event["desc"], (
                f"{group_key}/{event.get('key')} 缺少 desc 兜底文案"
            )
            # 可选字段若存在须符合 schema 形态
            assert isinstance(event.get("tags", []), list)
            variants = event.get("desc_variants")
            assert variants is None or isinstance(variants, dict)

    # 存量配置（无 tags/desc_variants）正常加载
    adv = _adv()
    assert adv.event_groups, "adventure_config.json 应正常加载事件分组"

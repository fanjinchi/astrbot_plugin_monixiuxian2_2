"""Tests for sect content linkage filtering (change group 7).

Covers:
- 7.1 Bounty list/accept filtering by template sect_id (bounty_manager).
- 7.2 Rift sect_member access check and list annotation (rift_manager).
- 7.3 Adventure event group/event filtering by player sect (adventure_manager).
"""

import sys
import time

import pytest
import pytest_asyncio

from tests.helpers import load_module, load_package_module

_migration_mod = load_module("migration_content_link_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager

_data_mod = load_package_module(
    "data/data_manager.py",
    "astrbot_plugin_monixiuxian2_2.data.data_manager",
)
DataBase = _data_mod.DataBase

Player = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models").Player

_sect_mod = load_package_module(
    "managers/sect_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.sect_content_link_manager",
)
SectManager = _sect_mod.SectManager

_rift_mod = load_module("rift_manager_cl", "managers/rift_manager.py")
RiftManager = _rift_mod.RiftManager

_adventure_mod = load_module("adventure_manager_cl", "managers/adventure_manager.py")
AdventureManager = _adventure_mod.AdventureManager


class FakeConfigManager:
    """Minimal ConfigManager stub with two default sect factions.

    The rift_config entries key off the migration-seeded rift ids (1-5):
    rift 1 is made sect-exclusive, rift 2 stays open to everyone.
    """

    def __init__(self):
        self.sect_config = {"positions": {}, "scale_ratio": 10}
        self.sect_factions = {
            "factions": [
                {
                    "id": "qingyun",
                    "name": "青云门",
                    "join_level_range": [0, 5],
                    "elders": [{"name": "玄诚子", "title": "传功长老"}],
                },
                {
                    "id": "huanxi",
                    "name": "合欢宗",
                    "join_level_range": [2, 6],
                    "elders": [{"name": "厉无欢", "title": "护法长老"}],
                },
            ]
        }
        self.sect_tasks = {"construction_tasks": [], "master_task_chains": []}
        self.game_config = {}
        self.rift_config = {
            "default_duration": 1800,
            "rifts": [
                {
                    "id": 1,
                    "name": "青云剑冢",
                    "level": 3,
                    "exp_range": [300, 900],
                    "gold_range": [100, 400],
                    "sect_id": "qingyun",
                    "access": "sect_member",
                },
                {
                    "id": 2,
                    "name": "落日峡谷",
                    "level": 5,
                    "exp_range": [500, 2000],
                    "gold_range": [200, 800],
                },
            ],
        }

    def get_level_name(self, level_index: int, cultivation_type: str = "灵修") -> str:
        return f"境界{level_index}"

    def is_pill(self, item_name: str) -> bool:
        return False


@pytest_asyncio.fixture
async def db():
    """Provide a migrated in-memory database and close it after the test."""
    database = DataBase(":memory:")
    await database.connect()
    await MigrationManager(database.conn, FakeConfigManager()).migrate()
    yield database
    await database.close()


@pytest.fixture(scope="module", autouse=True)
def bounty_manager_cls():
    """Load bounty_manager and yield its BountyManager class.

    bounty_manager does ``from ..data import DataBase`` at import time, so
    ``DataBase`` is exposed on the synthetic data package for the load only.
    Interpreter state is restored at module teardown so the patch never
    leaks into other test modules.
    """
    data_pkg = sys.modules["astrbot_plugin_monixiuxian2_2.data"]
    sentinel = object()
    previous = getattr(data_pkg, "DataBase", sentinel)
    data_pkg.DataBase = DataBase
    try:
        mod = load_package_module(
            "managers/bounty_manager.py",
            "astrbot_plugin_monixiuxian2_2.managers.bounty_manager_cl",
        )
        yield mod.BountyManager
    finally:
        sys.modules.pop(
            "astrbot_plugin_monixiuxian2_2.managers.bounty_manager_cl", None
        )
        if previous is sentinel:
            del data_pkg.DataBase
        else:
            data_pkg.DataBase = previous


async def _make_player(db: DataBase, user_id: str, level_index: int = 1) -> Player:
    player = Player(
        user_id=user_id,
        user_name=f"道友{user_id}",
        spiritual_root="天灵根",
        level_index=level_index,
    )
    await db.create_player(player)
    return player


async def _make_sect_mgr(db: DataBase) -> SectManager:
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    return mgr


async def _join(db, sect_mgr, user_id: str, sect_name: str, level_index: int = 1):
    await _make_player(db, user_id, level_index=level_index)
    success, msg = await sect_mgr.join_sect(user_id, sect_name)
    assert success, msg
    return await db.get_player_by_id(user_id)


# ===== 7.1 悬赏过滤 =====


def _sect_template() -> dict:
    return {
        "id": 901,
        "name": "后山巡守",
        "difficulty": "easy",
        "category": "巡山",
        "progress_tags": ["adventure_scout"],
        "min_target": 1,
        "max_target": 1,
        "time_limit": 3600,
        "reward": {"stone": 10, "exp": 10},
        "description": "为本门巡视后山。",
        "weight": 1,
        "sect_id": "qingyun",
    }


def _normal_template() -> dict:
    return {
        "id": 902,
        "name": "击退妖兽",
        "difficulty": "easy",
        "category": "巡山",
        "progress_tags": ["adventure_scout"],
        "min_target": 1,
        "max_target": 1,
        "time_limit": 3600,
        "reward": {"stone": 10, "exp": 10},
        "description": "驱逐妖兽。",
        "weight": 1,
    }


def _make_bounty_mgr(db, bounty_manager_cls):
    mgr = bounty_manager_cls(db)
    sect_tpl = _sect_template()
    normal_tpl = _normal_template()
    mgr.templates_by_id = {901: sect_tpl, 902: normal_tpl}
    mgr.templates_by_diff = {"easy": [sect_tpl, normal_tpl]}
    mgr.difficulties = {
        "easy": {"name": "F级", "stone_scale": 1.0, "exp_scale": 1.0, "min_level": 0}
    }
    return mgr


@pytest.mark.asyncio
async def test_bounty_list_hides_sect_template_for_non_member(db, bounty_manager_cls):
    """Sect-attributed templates never appear for sectless/other-sect players."""
    bounty_mgr = _make_bounty_mgr(db, bounty_manager_cls)

    player = await _make_player(db, "b1")
    bounties = await bounty_mgr.get_bounty_list(player)
    assert bounties, "normal templates still show"
    assert all(b["sect_id"] is None for b in bounties)
    assert all(b["id"] == 902 for b in bounties)


@pytest.mark.asyncio
async def test_bounty_list_shows_sect_template_for_member(db, bounty_manager_cls):
    """Member: sect-scope list holds the sect template; global list never does."""
    sect_mgr = await _make_sect_mgr(db)
    bounty_mgr = _make_bounty_mgr(db, bounty_manager_cls)

    # Sect-only pool: members see it in sect scope, global scope stays empty.
    bounty_mgr.templates_by_diff = {"easy": [_sect_template()]}
    player = await _join(db, sect_mgr, "b2", "青云门")
    bounties = await bounty_mgr.get_bounty_list(player, scope="sect")
    assert len(bounties) == 1
    assert bounties[0]["id"] == 901
    assert bounties[0]["sect_id"] == "qingyun"
    assert await bounty_mgr.get_bounty_list(player, scope="global") == []

    # Mixed pool: global scope only picks public templates, sect scope only sect ones.
    bounty_mgr2 = _make_bounty_mgr(db, bounty_manager_cls)
    seen_global = {
        bounty_mgr2._pick_template("easy", "qingyun")["id"] for _ in range(100)
    }
    assert seen_global == {902}
    seen_sect = {
        bounty_mgr2._pick_template("easy", "qingyun", scope="sect")["id"]
        for _ in range(100)
    }
    assert seen_sect == {901}


@pytest.mark.asyncio
async def test_bounty_accept_scope_split(db, bounty_manager_cls):
    """Scope split: global entry rejects sect bounties, sect entry rejects global/other-sect bounties."""
    sect_mgr = await _make_sect_mgr(db)
    bounty_mgr = _make_bounty_mgr(db, bounty_manager_cls)

    # 全局入口接宗门悬赏（含非成员与他宗成员）：分流提示走 /宗门 悬赏
    outsider = await _make_player(db, "b3")
    success, msg = await bounty_mgr.accept_bounty(outsider, 901)
    assert not success
    assert "宗门专属委托" in msg and "/宗门 悬赏" in msg

    other_sect = await _join(db, sect_mgr, "b4", "合欢宗", level_index=3)
    success, msg = await bounty_mgr.accept_bounty(other_sect, 901)
    assert not success
    assert "/宗门 悬赏" in msg

    # 宗门入口接他宗悬赏：拒绝
    success, msg = await bounty_mgr.accept_bounty(other_sect, 901, scope="sect")
    assert not success
    assert "其他宗门" in msg

    # 宗门入口接公共悬赏：分流提示走 /接取悬赏
    success, msg = await bounty_mgr.accept_bounty(other_sect, 902, scope="sect")
    assert not success
    assert "公共委托" in msg and "/接取悬赏" in msg


@pytest.mark.asyncio
async def test_bounty_accept_allows_member(db, bounty_manager_cls):
    """A qingyun member can accept the sect bounty via the sect scope (full accept flow)."""
    sect_mgr = await _make_sect_mgr(db)
    bounty_mgr = _make_bounty_mgr(db, bounty_manager_cls)

    player = await _join(db, sect_mgr, "b5", "青云门")
    # Sect-only pool so the cached list deterministically holds the sect bounty.
    bounty_mgr.templates_by_diff = {"easy": [_sect_template()]}
    await bounty_mgr.get_bounty_list(player, scope="sect")  # populate the accept cache
    success, msg = await bounty_mgr.accept_bounty(player, 901, scope="sect")
    assert success, msg
    active = await db.ext.get_active_bounty("b5")
    assert active is not None
    assert active["bounty_id"] == 901


@pytest.mark.asyncio
async def test_bounty_accept_normal_template_unchanged(db, bounty_manager_cls):
    """Templates without sect_id keep the existing accept behavior."""
    bounty_mgr = _make_bounty_mgr(db, bounty_manager_cls)

    player = await _make_player(db, "b6")
    await bounty_mgr.get_bounty_list(player)
    success, msg = await bounty_mgr.accept_bounty(player, 902)
    assert success, msg


@pytest.mark.asyncio
async def test_bounty_scope_mismatch_on_status_complete_abandon(db, bounty_manager_cls):
    """Status/complete/abandon reject cross-scope operations with guidance to the other entry."""
    sect_mgr = await _make_sect_mgr(db)
    bounty_mgr = _make_bounty_mgr(db, bounty_manager_cls)

    # 宗门悬赏进行中：全局入口状态/完成/放弃均引导到 /宗门 悬赏
    member = await _join(db, sect_mgr, "b7", "青云门")
    bounty_mgr.templates_by_diff = {"easy": [_sect_template()]}
    await bounty_mgr.get_bounty_list(member, scope="sect")
    success, msg = await bounty_mgr.accept_bounty(member, 901, scope="sect")
    assert success, msg

    success, msg = await bounty_mgr.check_bounty_status(member, scope="global")
    assert not success and "宗门悬赏" in msg and "/宗门 悬赏" in msg
    success, msg = await bounty_mgr.complete_bounty(member, scope="global")
    assert not success and "宗门悬赏" in msg
    success, msg = await bounty_mgr.abandon_bounty(member, scope="global")
    assert not success and "宗门悬赏" in msg

    # 本宗入口正常可见状态
    success, msg = await bounty_mgr.check_bounty_status(member, scope="sect")
    assert success and "后山巡守" in msg and "/宗门 悬赏 完成" in msg

    # 完成后（进度满）经宗门入口结算
    has_progress, hint = await bounty_mgr.add_bounty_progress(
        member, "adventure_scout", 1
    )
    assert has_progress and "/宗门 悬赏 完成" in hint
    success, msg = await bounty_mgr.complete_bounty(member, scope="sect")
    assert success, msg

    # 公共悬赏进行中：宗门入口引导到全局指令
    player = await _make_player(db, "b8")
    bounty_mgr2 = _make_bounty_mgr(db, bounty_manager_cls)
    bounty_mgr2.templates_by_diff = {"easy": [_normal_template()]}
    await bounty_mgr2.get_bounty_list(player, scope="global")
    success, msg = await bounty_mgr2.accept_bounty(player, 902, scope="global")
    assert success, msg
    success, msg = await bounty_mgr2.check_bounty_status(player, scope="sect")
    assert not success and "公共悬赏" in msg and "/悬赏状态" in msg
    success, msg = await bounty_mgr2.abandon_bounty(player, scope="sect")
    assert not success and "公共悬赏" in msg


# ===== 7.2 秘境准入 =====

# The migration seeds rifts 1-5; FakeConfigManager marks rift 1 as
# qingyun-exclusive and leaves rift 2 (required_level=3) open to everyone.


@pytest.mark.asyncio
async def test_rift_access_rejects_non_member(db):
    """Sect-member-only rifts reject sectless and other-sect players."""
    sect_mgr = await _make_sect_mgr(db)
    rift_mgr = RiftManager(db, FakeConfigManager())

    await _make_player(db, "r1")
    success, msg = await rift_mgr.enter_rift("r1", 1)
    assert not success
    assert "仅对本宗弟子开放" in msg

    await _join(db, sect_mgr, "r2", "合欢宗", level_index=3)
    success, msg = await rift_mgr.enter_rift("r2", 1)
    assert not success
    assert "仅对本宗弟子开放" in msg


@pytest.mark.asyncio
async def test_rift_access_allows_member_and_normal_rift(db):
    """The owning sect's member can enter; rifts without sect config are unaffected."""
    sect_mgr = await _make_sect_mgr(db)
    rift_mgr = RiftManager(db, FakeConfigManager())

    await _join(db, sect_mgr, "r3", "青云门")
    success, msg = await rift_mgr.enter_rift("r3", 1)
    assert success, msg
    await rift_mgr.exit_rift("r3")

    await _make_player(db, "r4", level_index=3)
    success, msg = await rift_mgr.enter_rift("r4", 2)
    assert success, msg


@pytest.mark.asyncio
async def test_rift_list_hides_sect_rift_for_non_member(db):
    """Sect-exclusive rifts are hidden from non-members; members see the 🏯 mark."""
    sect_mgr = await _make_sect_mgr(db)
    rift_mgr = RiftManager(db, FakeConfigManager())

    await _make_player(db, "r5")
    success, msg = await rift_mgr.list_rifts("r5")
    assert success
    assert "(ID:1)" not in msg, "sect-exclusive rift hidden from non-member"
    assert "(ID:2)" in msg, "normal rift still visible"

    await _join(db, sect_mgr, "r6", "青云门")
    success, msg = await rift_mgr.list_rifts("r6")
    assert success
    rift1_block = msg.split("(ID:1)")[1].split("(ID:2)")[0]
    assert "🏯 宗门专属秘境" in rift1_block


# ===== 7.3 历练事件过滤 =====


@pytest.mark.asyncio
async def test_adventure_weight_pool_appends_sect_group_for_member(db):
    """The inert sect_qingyun group joins the pool only for qingyun members."""
    adv_mgr = AdventureManager(db)
    route = adv_mgr.routes["scout"]

    pool = adv_mgr._build_event_weight_pool(route, None)
    assert "sect_qingyun" not in pool
    assert set(pool) == {"safe", "standard", "risky"}

    pool = adv_mgr._build_event_weight_pool(route, "qingyun")
    assert pool["sect_qingyun"] == AdventureManager.SECT_EVENT_GROUP_WEIGHT

    # Other factions do not get the qingyun group.
    pool = adv_mgr._build_event_weight_pool(route, "huanxi")
    assert "sect_qingyun" not in pool


@pytest.mark.asyncio
async def test_adventure_sect_events_filtered_within_group(db):
    """Events carrying a mismatched sect_id are excluded from the draw."""
    adv_mgr = AdventureManager(db)
    adv_mgr.event_groups["mixed"] = [
        {"key": "common", "name": "通用", "desc": "x", "exp_mult": 1.0},
        {
            "key": "sect_only",
            "name": "宗门",
            "desc": "y",
            "exp_mult": 1.0,
            "sect_id": "qingyun",
        },
    ]
    route = {"key": "t", "event_weights": {"mixed": 100}}

    for _ in range(100):
        assert adv_mgr._trigger_route_event(route, None)["key"] == "common"
        assert adv_mgr._trigger_route_event(route, "huanxi")["key"] == "common"

    # qingyun members can draw the sect event (the qingyun sect group is
    # also appended to the pool, so other sect events may appear too).
    seen = {adv_mgr._trigger_route_event(route, "qingyun")["key"] for _ in range(100)}
    assert "sect_only" in seen


@pytest.mark.asyncio
async def test_adventure_referenced_sect_group_dropped_for_non_member(db):
    """A route-referenced sect group falls back to standard for non-members."""
    adv_mgr = AdventureManager(db)
    route = {"key": "t", "event_weights": {"sect_qingyun": 100}}

    event = adv_mgr._trigger_route_event(route, None)
    standard_keys = {e["key"] for e in adv_mgr.event_groups["standard"]}
    assert event["key"] in standard_keys

    seen = {adv_mgr._trigger_route_event(route, "qingyun")["key"] for _ in range(100)}
    assert seen == {"elder_guidance", "sect_errand"}


@pytest.mark.asyncio
async def test_adventure_faction_resolution_from_player_sect(db):
    """_get_player_faction_id maps player.sect_id through the sects table."""
    sect_mgr = await _make_sect_mgr(db)
    adv_mgr = AdventureManager(db)

    player = await _join(db, sect_mgr, "a1", "青云门")
    assert await adv_mgr._get_player_faction_id(player) == "qingyun"

    sectless = await _make_player(db, "a2")
    assert await adv_mgr._get_player_faction_id(sectless) is None


@pytest.mark.asyncio
async def test_adventure_settlement_marks_sect_event(db, monkeypatch):
    """Settlement prefixes 「🏯 宗门际遇 · 事件名」 for sect events; normal events unchanged."""
    adv_mgr = AdventureManager(db)

    async def _finish_with_event(user_id: str, event: dict) -> str:
        monkeypatch.setattr(
            adv_mgr, "_trigger_route_event", lambda route, faction_id=None: event
        )
        # 与 GM 强制结算一致：把计划完成时间提前到当前，立即结算
        user_cd = await db.ext.get_user_cd(user_id)
        user_cd.scheduled_time = int(time.time())
        await db.ext.update_user_cd(user_cd)
        success, msg, _ = await adv_mgr.finish_adventure(user_id)
        assert success, msg
        return msg

    sect_event = {
        "key": "elder_guidance",
        "name": "长老传功",
        "desc": "传功长老路过点拨。",
        "exp_mult": 1.0,
        "gold_mult": 1.0,
        "item_chance": 0,
        "sect_id": "qingyun",
    }
    normal_event = {
        "key": "steady_path",
        "name": "平稳推进",
        "desc": "历练顺风顺水。",
        "exp_mult": 1.0,
        "gold_mult": 1.0,
        "item_chance": 0,
    }

    await _make_player(db, "m1")
    success, _ = await adv_mgr.start_adventure("m1", "巡山")
    assert success
    msg = await _finish_with_event("m1", sect_event)
    assert "🏯 宗门际遇 · 长老传功" in msg
    assert "传功长老路过点拨。" in msg

    await _make_player(db, "m2")
    success, _ = await adv_mgr.start_adventure("m2", "巡山")
    assert success
    msg = await _finish_with_event("m2", normal_event)
    assert "宗门际遇" not in msg
    assert "历练顺风顺水。" in msg

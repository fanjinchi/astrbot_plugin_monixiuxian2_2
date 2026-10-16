"""写锁内重读收口（bd -546）的并发回归：洞天收取 / 灵田收获 / 瞬回丹。

这三处写点原先按 @player_required 的入口快照整行回写：同一玩家并发双击时，后到者
会把窗口内别人提交的列覆盖回旧值，或按过期快照重复发奖。收口后的范式是
「写锁内重读 → 再校验 → 再计算 → 再写回」，本文件用真内存库 + 真 manager 驱动两路
并发，断言「只成功一路、收益只发一次、落败方拿到正常文案而不是异常」。

blessed_land_manager.py / spirit_farm_manager.py / core/pill_manager.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio

from tests.helpers import load_module, load_package_module

_data_mod = load_package_module(
    "data/data_manager.py", "astrbot_plugin_monixiuxian2_2.data.data_manager"
)
DataBase = _data_mod.DataBase
sys.modules["astrbot_plugin_monixiuxian2_2.data"].DataBase = DataBase

_migration_mod = load_module("migration_write_containment_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager

_config_mod = load_package_module(
    "config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager"
)
ConfigManager = _config_mod.ConfigManager
PLUGIN_ROOT = Path(__file__).resolve().parent.parent

_land_mod = load_package_module(
    "managers/blessed_land_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.blessed_land_containment",
)
BlessedLandManager = _land_mod.BlessedLandManager

_farm_mod = load_package_module(
    "managers/spirit_farm_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.spirit_farm_containment",
)
SpiritFarmManager = _farm_mod.SpiritFarmManager

_pill_mod = load_package_module(
    "core/pill_manager.py", "astrbot_plugin_monixiuxian2_2.core.pill_containment"
)
PillManager = _pill_mod.PillManager

Player = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models").Player

USER = "race-user"


class _StubConfigManager:
    """只够 MigrationManager 建表读的最小配置替身。"""

    def __init__(self):
        self.items_data: dict = {}
        self.weapons_data: dict = {}
        self.heart_methods_data: dict = {}
        self.storage_rings_data: dict = {}
        self.game_config: dict = {}


@pytest_asyncio.fixture
async def db():
    """Real in-memory database on the latest schema."""
    database = DataBase(":memory:")
    await database.connect()
    await MigrationManager(database.conn, _StubConfigManager()).migrate_or_reset()
    yield database
    await database.close()


async def _make_player(db, **overrides) -> Player:
    """Create the shared test player (idempotent per test: fresh :memory: db)."""
    fields = {
        "user_id": USER,
        "user_name": "并发测试",
        "level_index": 9,  # 筑基丹 required_level_index
        "gold": 100000,
        "experience": 1000,
        "base_hp": 500,
        "current_hp": 500,
    }
    fields.update(overrides)
    player = Player(**fields)
    await db.create_player(player)
    return player


def _split(results):
    """Split (ok, msg) results into successes and failures."""
    return [r for r in results if r[0]], [r for r in results if not r[0]]


@pytest.mark.asyncio
async def test_concurrent_land_collect_grants_once(db):
    """两路并发「洞天收取」：写锁内重读让后到者按冷却拒绝，收益只发一次。

    修复前两路都按入口快照算出 2 小时产出并整行回写：后写者把同一段产出再发一遍
    （收益重复），或把并发窗口里别人写入的列覆盖回旧值。
    """
    mgr = BlessedLandManager(db)
    await _make_player(db)
    now = int(time.time())
    await db.conn.execute(
        "INSERT INTO blessed_lands (user_id, land_type, land_name, level, exp_bonus, "
        "gold_per_hour, last_collect_time) VALUES (?, 1, '小洞天', 1, 0.05, 100, ?)",
        (USER, now - 7200),
    )
    await db.conn.commit()

    p1 = await db.get_player_by_id(USER)
    p2 = await db.get_player_by_id(USER)
    results = await asyncio.gather(mgr.collect_income(p1), mgr.collect_income(p2))

    ok, fail = _split(results)
    assert len(ok) == 1, results
    assert "冷却中" in fail[0][1]
    player = await db.get_player_by_id(USER)
    assert player.gold == 100000 + 200  # 2 小时 × 100/小时，只发一次


@pytest.mark.asyncio
async def test_concurrent_farm_harvest_grants_once(db):
    """两路并发「灵田收获」：后到者读到已清空的 crops，不重复发奖。

    修复前两路都按入口快照分类同一批成熟灵草，各发一份收益并各写一次
    （后者覆盖前者），收益与 «清空 crops» 的语义都对不上。
    """
    mgr = SpiritFarmManager(db)
    await _make_player(db)
    now = int(time.time())
    crops = json.dumps([{"name": "灵草", "mature_time": now - 10}])
    await db.conn.execute(
        "INSERT INTO spirit_farms (user_id, level, crops) VALUES (?, 1, ?)",
        (USER, crops),
    )
    await db.conn.commit()

    p1 = await db.get_player_by_id(USER)
    p2 = await db.get_player_by_id(USER)
    results = await asyncio.gather(mgr.harvest(p1), mgr.harvest(p2))

    ok, _fail = _split(results)
    assert len(ok) == 1, results
    player = await db.get_player_by_id(USER)
    assert player.gold == 100000 + 100  # 灵草 gold_yield，只发一次
    assert player.experience == 1000 + 500
    assert (await mgr.get_user_farm(USER))["crops"] == []


@pytest.mark.asyncio
async def test_concurrent_instant_pill_consumes_once(db):
    """两路并发抢最后一颗丹药：落败方拿到正常提示，不得抛 KeyError。

    包装层在写锁内重读后必须**再校验背包**（重读 → 再校验 → 再计算）：否则落败方
    在入口快照上通过的那次校验已经过期，本体 `inventory[pill_name] -= 1` 会
    抛 KeyError 穿出服务层——玩家只看到框架报错，没有任何回执。
    """
    pm = PillManager(db, ConfigManager(PLUGIN_ROOT))
    await _make_player(db, pills_inventory=json.dumps({"筑基丹": 1}))

    p1 = await db.get_player_by_id(USER)
    p2 = await db.get_player_by_id(USER)
    results = await asyncio.gather(
        pm.use_pill(p1, "筑基丹"),
        pm.use_pill(p2, "筑基丹"),
        return_exceptions=True,
    )

    assert not any(isinstance(r, Exception) for r in results), results
    ok, fail = _split(results)
    assert len(ok) == 1, results
    assert "背包中没有" in fail[0][1]
    player = await db.get_player_by_id(USER)
    assert player.get_pills_inventory() == {}

"""Child D 世界 Boss 领域验收测试（R1–R6 / AC1–AC5、AC7）。

真实内存库（迁移到最新 v39）+ 固定业务时钟 + 脚本化战斗引擎：

- R1 固定实例与出生快照：全随机选段、instance_id 确定性派生、快照不可变、
  难度出生固化、单 active、GM 强制三分支、再生资格以 next_spawn_at 为唯一权威；
- R2 生命周期：active → defeated | dissipated，终态同批写 terminated_at +
  next_spawn_at，到期消散幂等；
- R3 每日次数：北京自然日每人 3 次，并发/拒绝不误扣；
- R4 原子挑战：伤害 = hp_before - hp_after、次数/台账/贡献/气血在单事务内、
  CAS 冲突不旧战报套新 HP、地板单源写回、不写疲劳不收门票；
- R5 阶段：60%/20% 阈值、只升不降、跨两阈值两条事件、每阶段事件唯一；
- R6 台账：真实伤害 + 唯一末击，不引用旧即时灵石奖励；
- AC4/AC9 约束：不出现 DEFEAT_HP_FLOOR_RATIO 第二常量，不写 fatigue 表。
"""

import asyncio
import json
import random
import sys
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

from tests.helpers import PLUGIN_ROOT, load_module, load_package_module
from tests.test_player_health_foundation import T0, StubConfigManager, put_player

pytestmark = pytest.mark.asyncio

_schema_mod = load_package_module(
    "core/enemy_schema.py", "astrbot_plugin_monixiuxian2_2.core.enemy_schema"
)
_catalog_mod = load_package_module(
    "managers/enemy_catalog.py", "astrbot_plugin_monixiuxian2_2.managers.enemy_catalog"
)
_repo_mod = load_package_module(
    "data/pve_repository.py", "astrbot_plugin_monixiuxian2_2.data.pve_repository"
)
_events_mod = load_package_module(
    "managers/world_boss_events.py",
    "astrbot_plugin_monixiuxian2_2.managers.world_boss_events",
)
_service_mod = load_package_module(
    "managers/world_boss_service.py",
    "astrbot_plugin_monixiuxian2_2.managers.world_boss_service",
)
_migration_mod = load_package_module(
    "data/migration.py", "astrbot_plugin_monixiuxian2_2.data.migration"
)
_sync = load_module("sync_content_to_config_d", "scripts/sync_content_to_config.py")

WorldBossService = _service_mod.WorldBossService
WorldBossSpawnRejected = _service_mod.WorldBossSpawnRejected
WorldBossRepository = _repo_mod.WorldBossRepository
DataBase = sys.modules["astrbot_plugin_monixiuxian2_2.data"].DataBase

DESIGN_DIR = PLUGIN_ROOT / "design_docs" / "content-design"
_SHANGHAI = ZoneInfo("Asia/Shanghai")

PREVIEW_DOC, PREVIEW_ERRORS = _sync.render_enemy_document(
    DESIGN_DIR, manifest=None, manifest_path=None, existing_config=None
)
assert PREVIEW_ERRORS == [], PREVIEW_ERRORS

# 四只固定档案（design_docs/content-design/world_bosses.csv）
LQ_BA = "wb_lq_ba"
LQ_BA_HP = 1000
LQ_BA_DAMAGE = 18
ZJ_TUO = "wb_zj_tuo"
ZJ_TUO_HP = 1800


def _epoch(iso: str) -> int:
    """Beijing wall-clock ISO string -> unix epoch (business-time tests)."""
    return int(datetime.fromisoformat(iso).replace(tzinfo=_SHANGHAI).timestamp())


@pytest_asyncio.fixture
async def db():
    """迁移到最新版本的内存库（含玩家 u1：气血 500/500）。"""
    database = DataBase(":memory:")
    await database.connect()
    await _migration_mod.MigrationManager(
        database.conn, StubConfigManager()
    ).migrate_or_reset()
    await put_player(database, "u1", 500, 500, anchor=T0)
    yield database
    await database.close()


def _approved_doc() -> dict:
    """Preview 文档的深拷贝，并把四个 Boss 标为叙事已批准（广播用例）。"""
    doc = json.loads(json.dumps(PREVIEW_DOC))
    for entry in doc["world_bosses"]:
        entry["narrative_approved"] = True
    return doc


@pytest.fixture(scope="module")
def approved_catalog():
    return _catalog_mod.EnemyCatalog(_approved_doc(), source="wb-approved")


@pytest.fixture(scope="module")
def draft_catalog():
    return _catalog_mod.EnemyCatalog(PREVIEW_DOC, source="wb-draft")


class Clock:
    """可推进的固定业务时钟。"""

    def __init__(self, value: int = T0) -> None:
        self.value = int(value)

    def __call__(self) -> int:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += int(seconds)


class ScriptedEngine:
    """脚本化战斗引擎：每次 resolve 弹出一对 (玩家终值HP, Boss终值HP)。"""

    def __init__(self, scripts=()) -> None:
        self.scripts = list(scripts)
        self.boss_fighters = []
        self.player_fighters = []

    async def build_fighter_from_player(self, player, is_attacker=True):
        fighter = SimpleNamespace(user_id=player.user_id, hp=player.current_hp)
        self.player_fighters.append(fighter)
        return fighter

    def resolve_combat(self, fighter1, fighter2, combat_type="spar", merge_count=None):
        assert self.scripts, "scripted fight exhausted"
        self.boss_fighters.append(fighter2)
        player_hp, boss_hp = self.scripts.pop(0)
        return SimpleNamespace(
            winner_side="fighter1" if player_hp > 0 else "fighter2",
            winner_id=fighter1.user_id,
            combat_log=[],
            fighter1_final_hp=player_hp,
            fighter2_final_hp=boss_hp,
            rounds=1,
            total_actions=2,
        )


class StubHealthService:
    """气血结算替身；defeat_hp_floor 模拟 E1 落地后的单源地板。"""

    def __init__(self, floor: int = 0) -> None:
        self.floor = floor
        self.settles = []

    async def settle(self, user_id, now=None):
        self.settles.append((user_id, now))
        return 0

    def defeat_hp_floor(self, player) -> int:
        return self.floor


class LegacyHealthService:
    """E1 未落地时的健康服务（无 defeat_hp_floor 能力）。"""

    async def settle(self, user_id, now=None):
        return 0


class StubBusyState:
    def __init__(self, message: str | None = None) -> None:
        self.message = message
        self.calls = []

    async def assert_idle(self, user_id, template=""):
        self.calls.append((user_id, template))
        return self.message


def make_config(difficulty: float = 1.0):
    return SimpleNamespace(game_config={"pve": {"difficulty_multiplier": difficulty}})


def make_service(
    db,
    catalog,
    engine,
    *,
    clock=None,
    health=None,
    busy=None,
    rng=None,
    config=None,
):
    return WorldBossService(
        db,
        catalog,
        health if health is not None else StubHealthService(),
        busy if busy is not None else StubBusyState(),
        engine,
        config if config is not None else make_config(),
        clock=clock if clock is not None else Clock(T0),
        rng=rng,
    )


async def _events(db):
    async with db.conn.execute(
        "SELECT * FROM business_events ORDER BY occurred_at, rowid"
    ) as cursor:
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in await cursor.fetchall()]


async def _count(db, table):
    async with db.conn.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
        return (await cursor.fetchone())[0]


async def _player(db, user_id="u1"):
    return await db.get_player_by_id(user_id)


async def _instance(db, instance_id):
    return await WorldBossRepository(db.conn).get_instance(instance_id)


async def _attempts(db, date_key, user_id="u1"):
    return await WorldBossRepository(db.conn).get_daily_attempts(
        date_key=date_key, user_id=user_id
    )


def _snapshot(instance) -> dict:
    return json.loads(instance["birth_snapshot"])


def _pick_other_profile(catalog, profile_id: str) -> str:
    for profile in catalog.world_bosses:
        if profile.id != profile_id:
            return profile.id
    raise AssertionError("catalog must hold more than one profile")


class FixedPicker:
    """固定 randrange 返回值的 RNG 替身（驱动随机选段结果）。"""

    def __init__(self, seed_value: int) -> None:
        self.seed_value = seed_value

    def randrange(self, start, stop=None):
        return self.seed_value


def _seed_picking(catalog, profile_id: str) -> int:
    """找一个 seed，使 random.Random(seed) 选中 profile_id。"""
    ids = [profile.id for profile in catalog.world_bosses]
    index = ids.index(profile_id)
    for seed in range(1, 500):
        if random.Random(seed).randrange(len(ids)) == index:
            return seed
    raise AssertionError("no seed found")


# ─────────────────────────────── R1 spawn ──────────────────────────────────


async def test_ensure_spawn_creates_single_active_instance_with_frozen_snapshot(
    db, approved_catalog
):
    clock = Clock(T0)
    svc = make_service(db, approved_catalog, ScriptedEngine(), clock=clock)

    instance, created, profile_id = await svc.ensure_spawn()

    assert created is True
    assert instance["state"] == "active"
    assert instance["instance_id"] == f"wb_{profile_id}_{T0}"
    assert instance["expires_at"] == T0 + 48 * 3600
    assert instance["current_hp"] == instance["max_hp"]
    assert instance["next_spawn_at"] == 0
    snapshot = _snapshot(instance)
    assert snapshot["profile_id"] == profile_id
    assert snapshot["selected_profile_id"] == profile_id
    assert snapshot["selection_source"] == "seed"
    assert snapshot["scheduled_epoch"] == T0
    assert snapshot["difficulty_multiplier"] == 1.0
    assert snapshot["narrative_approved"] is True
    assert snapshot["phase_thresholds"] == [0.6, 0.2]
    for key in (
        "spawn_text",
        "phase2_text",
        "phase3_text",
        "kill_text",
        "dissipate_text",
    ):
        assert snapshot[key], key

    rows = await WorldBossRepository(db.conn).list_instances(states=("active",))
    assert len(rows) == 1
    events = await _events(db)
    assert [e["event_type"] for e in events] == [_events_mod.EVENT_SPAWN]
    assert json.loads(events[0]["payload"])["copy_key"] == "spawn_text"


async def test_second_ensure_returns_same_instance_without_new_event(
    db, approved_catalog
):
    svc = make_service(db, approved_catalog, ScriptedEngine())
    first, created_first, profile_id = await svc.ensure_spawn()

    second, created_second, profile_second = await svc.ensure_spawn()

    assert created_first is True and created_second is False
    assert second["instance_id"] == first["instance_id"]
    assert profile_second == profile_id
    events = await _events(db)
    assert len(events) == 1


async def test_restarted_service_recovers_active_boss_and_attempt_state(
    db, approved_catalog
):
    clock = Clock(T0)
    first_service = make_service(db, approved_catalog, ScriptedEngine(), clock=clock)
    instance, created, profile_id = await first_service.ensure_spawn(LQ_BA)
    assert created is True

    # 进程重启：新服务实例只拿同一个库重连，不得重复生成 Boss。
    restarted_service = make_service(
        db, approved_catalog, ScriptedEngine([(500, 900)]), clock=clock
    )
    recovered, created_again, profile_again = await restarted_service.ensure_spawn()
    assert created_again is False
    assert recovered["instance_id"] == instance["instance_id"]
    assert profile_again == profile_id

    result = await restarted_service.challenge(
        player=await _player(db), challenge_id="c-restart"
    )
    assert result.ok is True and result.damage_dealt == 100
    assert (await _instance(db, instance["instance_id"]))["current_hp"] == 900
    assert (await _attempts(db, "2023-11-15"))["attempts_used"] == 1
    assert await _count(db, "world_boss_instances") == 1
    assert [e["event_type"] for e in await _events(db)] == [_events_mod.EVENT_SPAWN]


async def test_forced_profile_is_reused_when_another_boss_is_active(
    db, approved_catalog
):
    svc = make_service(db, approved_catalog, ScriptedEngine())
    instance, _, profile_id = await svc.ensure_spawn()

    other = _pick_other_profile(approved_catalog, profile_id)
    reused, created, resolved = await svc.ensure_spawn(other)

    assert created is False
    assert reused["instance_id"] == instance["instance_id"]
    assert resolved == profile_id
    rows = await WorldBossRepository(db.conn).list_instances(states=("active",))
    assert len(rows) == 1


async def test_forced_profile_spawns_without_eligibility(db, approved_catalog):
    svc = make_service(db, approved_catalog, ScriptedEngine())

    instance, created, profile_id = await svc.ensure_spawn(ZJ_TUO)

    assert created is True
    assert profile_id == ZJ_TUO
    assert instance["instance_id"] == f"wb_{ZJ_TUO}_{T0}"
    assert _snapshot(instance)["selection_source"] == "forced"
    assert _snapshot(instance)["seed"] == 0


async def test_unknown_forced_profile_is_rejected(db, approved_catalog):
    svc = make_service(db, approved_catalog, ScriptedEngine())

    with pytest.raises(WorldBossSpawnRejected, match="未知的世界 Boss 档案"):
        await svc.ensure_spawn("wb_no_such_boss")

    assert await _count(db, "world_boss_instances") == 0


async def test_disabled_catalog_rejects_spawn(db):
    svc = make_service(db, None, ScriptedEngine())

    with pytest.raises(WorldBossSpawnRejected, match="玩法未启用"):
        await svc.ensure_spawn()

    assert svc.enabled is False


async def test_spawn_before_respawn_eligibility_is_rejected(db, approved_catalog):
    clock = Clock(T0)
    engine = ScriptedEngine([(500, 0)])
    svc = make_service(db, approved_catalog, engine, clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    result = await svc.challenge(
        player=await _player(db),
        challenge_id="kill-1",
        instance_id=instance["instance_id"],
    )
    assert result.defeated is True

    clock.advance(3600)
    with pytest.raises(WorldBossSpawnRejected, match="尚未到再生时间"):
        await svc.ensure_spawn()

    killed = await _instance(db, instance["instance_id"])
    assert killed["state"] == "defeated"
    assert killed["next_spawn_at"] == T0 + 12 * 3600


async def test_spawn_after_respawn_eligibility_creates_new_instance(
    db, approved_catalog
):
    clock = Clock(T0)
    engine = ScriptedEngine([(500, 0)])
    svc = make_service(db, approved_catalog, engine, clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    await svc.challenge(
        player=await _player(db),
        challenge_id="kill-1",
        instance_id=instance["instance_id"],
    )

    clock.value = T0 + 12 * 3600
    fresh, created, profile_id = await svc.ensure_spawn()

    assert created is True
    assert fresh["instance_id"] == f"wb_{profile_id}_{T0 + 12 * 3600}"
    assert fresh["state"] == "active"
    assert fresh["expires_at"] == clock.value + 48 * 3600
    actives = await WorldBossRepository(db.conn).list_instances(states=("active",))
    assert [row["instance_id"] for row in actives] == [fresh["instance_id"]]


async def test_expired_active_is_dissipated_then_respawns_later(db, approved_catalog):
    clock = Clock(T0)
    svc = make_service(db, approved_catalog, ScriptedEngine(), clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    instance_id = instance["instance_id"]

    clock.value = T0 + 48 * 3600  # 恰好到期：48h 生命周期结束
    with pytest.raises(WorldBossSpawnRejected, match="尚未到再生时间"):
        await svc.ensure_spawn()

    dissipated = await _instance(db, instance_id)
    assert dissipated["state"] == "dissipated"
    assert dissipated["terminated_at"] == T0 + 48 * 3600
    assert dissipated["next_spawn_at"] == T0 + 72 * 3600
    event_types = [e["event_type"] for e in await _events(db)]
    assert event_types == [_events_mod.EVENT_SPAWN, _events_mod.EVENT_DISSIPATED]

    clock.value = T0 + 72 * 3600
    fresh, created, _ = await svc.ensure_spawn()
    assert created is True
    assert fresh["state"] == "active"


async def test_repeated_poll_keeps_single_active_boss_across_expiry(
    db, approved_catalog
):
    clock = Clock(T0)
    svc = make_service(db, approved_catalog, ScriptedEngine(), clock=clock)
    first, _, first_profile = await svc.ensure_spawn()

    # 两次 poll 之间跨过到期点：下一次轮询消散旧实例，再等到资格后换一只新 Boss。
    clock.value = T0 + 72 * 3600
    second, created, second_profile = await svc.ensure_spawn()

    assert created is True
    assert second["instance_id"] != first["instance_id"]
    assert second["state"] == "active"
    actives = await WorldBossRepository(db.conn).list_instances(states=("active",))
    assert len(actives) == 1
    assert second_profile in {p.id for p in approved_catalog.world_bosses}
    assert second["instance_id"] == f"wb_{second_profile}_{T0 + 72 * 3600}"


async def test_seed_selection_is_reproducible_by_seed(db, approved_catalog):
    seed = _seed_picking(approved_catalog, ZJ_TUO)
    svc = make_service(db, approved_catalog, ScriptedEngine(), rng=FixedPicker(seed))

    instance, _, profile_id = await svc.ensure_spawn()

    assert profile_id == ZJ_TUO
    snapshot = _snapshot(instance)
    assert snapshot["seed"] == seed
    picked = approved_catalog.world_bosses[
        random.Random(seed).randrange(len(approved_catalog.world_bosses))
    ]
    assert picked.id == ZJ_TUO


async def test_difficulty_multiplier_is_frozen_at_spawn(db, approved_catalog):
    clock = Clock(T0)
    engine = ScriptedEngine([(500, 900)])
    config = make_config(2.0)
    svc = make_service(db, approved_catalog, engine, clock=clock, config=config)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    assert _snapshot(instance)["difficulty_multiplier"] == 2.0

    config.game_config["pve"]["difficulty_multiplier"] = 3.0
    await svc.challenge(
        player=await _player(db),
        challenge_id="c-1",
        instance_id=instance["instance_id"],
    )

    boss_fighter = engine.boss_fighters[-1]
    assert boss_fighter.damage == round(LQ_BA_DAMAGE * 2.0)

    # 热更新只影响之后出生的实例。
    clock.value = T0 + 72 * 3600
    fresh, created, _ = await svc.ensure_spawn()
    assert created is True
    assert _snapshot(fresh)["difficulty_multiplier"] == 3.0


# ─────────────────────────────── R4 challenge ──────────────────────────────


async def test_challenge_settles_damage_attempt_ledger_and_contribution(
    db, approved_catalog
):
    clock = Clock(T0)
    engine = ScriptedEngine([(480, 900)])
    svc = make_service(db, approved_catalog, engine, clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    player = await _player(db)

    result = await svc.challenge(
        player=player, challenge_id="c-1", instance_id=instance["instance_id"]
    )

    assert result.ok is True
    assert result.damage_dealt == 100
    assert result.defeated is False
    assert result.phase == 1
    assert result.phase_advanced == ()
    fresh = await _instance(db, instance["instance_id"])
    assert fresh["current_hp"] == 900
    assert fresh["phase"] == 1

    counter = await _attempts(db, "2023-11-15")
    assert counter["attempts_used"] == 1

    challenge = await WorldBossRepository(db.conn).get_challenge("c-1")
    assert challenge["damage_dealt"] == 100
    assert challenge["hp_before"] == LQ_BA_HP
    assert challenge["hp_after"] == 900
    assert challenge["player_hp_before"] == 500
    assert challenge["player_hp_after"] == 480
    assert challenge["fled"] == 0
    assert challenge["is_last_hit"] == 0
    assert challenge["outcome"] == "ongoing"
    assert challenge["instance_cas_version"] == instance["cas_version"]

    ledger = await WorldBossRepository(db.conn).get_ledger("c-1")
    assert ledger["damage_dealt"] == 100
    contribution = await WorldBossRepository(db.conn).get_contribution(
        instance_id=instance["instance_id"], user_id="u1"
    )
    assert contribution["total_damage"] == 100
    assert contribution["attempt_count"] == 1
    assert contribution["is_last_hit"] == 0

    assert int((await _player(db)).current_hp) == 480
    assert await _count(db, "adventure_fatigue") == 0
    event_types = [e["event_type"] for e in await _events(db)]
    assert event_types == [_events_mod.EVENT_SPAWN]


async def test_daily_cap_is_three_attempts_per_beijing_day(db, approved_catalog):
    clock = Clock(T0)
    engine = ScriptedEngine([(500, 1700), (500, 1600), (500, 1500)])
    svc = make_service(db, approved_catalog, engine, clock=clock)
    instance, _, _ = await svc.ensure_spawn(ZJ_TUO)
    player = await _player(db)

    for index in range(3):
        result = await svc.challenge(
            player=player,
            challenge_id=f"c-{index}",
            instance_id=instance["instance_id"],
        )
        assert result.ok is True

    fourth = await svc.challenge(
        player=player, challenge_id="c-3", instance_id=instance["instance_id"]
    )
    assert fourth.ok is False
    assert "挑战次数已用完（每日 3 次）" in fourth.message
    assert await _count(db, "world_boss_challenges") == 3
    counter = await _attempts(db, "2023-11-15")
    assert counter["attempts_used"] == 3


async def test_rejected_challenge_does_not_consume_attempt(db, approved_catalog):
    clock = Clock(T0)
    svc = make_service(db, approved_catalog, ScriptedEngine(), clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)

    clock.value = T0 + 48 * 3600  # 未轮询，实例已过期
    result = await svc.challenge(
        player=await _player(db),
        challenge_id="c-expired",
        instance_id=instance["instance_id"],
    )

    assert result.ok is False
    assert "已消散" in result.message
    assert await _count(db, "world_boss_challenges") == 0
    assert await _count(db, "world_boss_daily_attempts") == 0


async def test_phase_thresholds_advance_once_and_never_regress(db, approved_catalog):
    clock = Clock(T0)
    engine = ScriptedEngine([(500, 150), (500, 900)])
    svc = make_service(db, approved_catalog, engine, clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    player = await _player(db)

    crossed = await svc.challenge(
        player=player, challenge_id="c-1", instance_id=instance["instance_id"]
    )
    assert crossed.phase_advanced == (2, 3)
    assert crossed.phase == 3
    stage_events = [
        e for e in await _events(db) if e["event_type"] == _events_mod.EVENT_STAGE
    ]
    assert len(stage_events) == 2
    assert [json.loads(e["payload"])["phase"] for e in stage_events] == [2, 3]
    assert [json.loads(e["payload"])["copy_key"] for e in stage_events] == [
        "phase2_text",
        "phase3_text",
    ]

    # 血量回升（数据异常）也不得回退阶段。
    regressed = await svc.challenge(
        player=player, challenge_id="c-2", instance_id=instance["instance_id"]
    )
    assert regressed.phase == 3
    fresh = await _instance(db, instance["instance_id"])
    assert fresh["phase"] == 3


async def test_last_hit_is_unique_and_schedules_respawn(db, approved_catalog):
    clock = Clock(T0)
    engine = ScriptedEngine([(500, 900), (500, 0), (500, 0)])
    svc = make_service(db, approved_catalog, engine, clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    player = await _player(db)

    await svc.challenge(
        player=player, challenge_id="c-1", instance_id=instance["instance_id"]
    )
    clock.advance(60)
    last = await svc.challenge(
        player=player, challenge_id="c-2", instance_id=instance["instance_id"]
    )

    assert last.defeated is True
    assert last.is_last_hit is True
    fresh = await _instance(db, instance["instance_id"])
    assert fresh["state"] == "defeated"
    assert fresh["terminated_at"] == clock.value
    assert fresh["next_spawn_at"] == clock.value + 12 * 3600
    contribution = await WorldBossRepository(db.conn).get_contribution(
        instance_id=instance["instance_id"], user_id="u1"
    )
    assert contribution["is_last_hit"] == 1
    assert contribution["total_damage"] == LQ_BA_HP
    defeated_events = [
        e for e in await _events(db) if e["event_type"] == _events_mod.EVENT_DEFEATED
    ]
    assert len(defeated_events) == 1
    assert json.loads(defeated_events[0]["payload"])["copy_key"] == "kill_text"

    # 终态实例不再接受挑战，也不会重复扣次数。
    rejected = await svc.challenge(
        player=player, challenge_id="c-3", instance_id=instance["instance_id"]
    )
    assert rejected.ok is False
    assert "已不在挑战期" in rejected.message
    assert await _count(db, "world_boss_challenges") == 2


async def test_replaying_same_challenge_id_settles_once(db, approved_catalog):
    clock = Clock(T0)
    engine = ScriptedEngine([(500, 900)])
    svc = make_service(db, approved_catalog, engine, clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    player = await _player(db)

    first = await svc.challenge(
        player=player, challenge_id="c-dup", instance_id=instance["instance_id"]
    )
    second = await svc.challenge(
        player=player, challenge_id="c-dup", instance_id=instance["instance_id"]
    )

    assert first.ok is True and second.ok is True
    assert "已结算" in second.message
    assert second.damage_dealt == first.damage_dealt
    assert await _count(db, "world_boss_challenges") == 1
    assert await _count(db, "world_boss_ledger") == 1
    counter = await _attempts(db, "2023-11-15")
    assert counter["attempts_used"] == 1
    assert int((await _player(db)).current_hp) == 500


async def test_player_hp_uses_single_source_defeat_floor(db, approved_catalog):
    clock = Clock(T0)
    engine = ScriptedEngine([(0, 900)])
    svc = make_service(
        db, approved_catalog, engine, clock=clock, health=StubHealthService(floor=50)
    )
    instance, _, _ = await svc.ensure_spawn(LQ_BA)

    result = await svc.challenge(
        player=await _player(db),
        challenge_id="c-floor",
        instance_id=instance["instance_id"],
    )

    assert result.ok is True
    assert int((await _player(db)).current_hp) == 50


async def test_player_hp_falls_back_to_one_without_e1_floor_api(db, approved_catalog):
    clock = Clock(T0)
    engine = ScriptedEngine([(0, 900)])
    svc = make_service(
        db, approved_catalog, engine, clock=clock, health=LegacyHealthService()
    )
    instance, _, _ = await svc.ensure_spawn(LQ_BA)

    await svc.challenge(
        player=await _player(db),
        challenge_id="c-legacy",
        instance_id=instance["instance_id"],
    )

    assert int((await _player(db)).current_hp) == 1


async def test_busy_player_is_rejected_before_combat(db, approved_catalog):
    clock = Clock(T0)
    engine = ScriptedEngine()
    busy = StubBusyState("❌ 你当前正忙，无法挑战Boss！")
    svc = make_service(db, approved_catalog, engine, clock=clock, busy=busy)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)

    result = await svc.challenge(
        player=await _player(db),
        challenge_id="c-busy",
        instance_id=instance["instance_id"],
    )

    assert result.ok is False
    assert result.message == "❌ 你当前正忙，无法挑战Boss！"
    assert busy.calls and busy.calls[0][1] == _service_mod.BUSY_TEMPLATE
    assert await _count(db, "world_boss_challenges") == 0


async def test_beijing_day_boundary_opens_a_new_attempt_budget(db, approved_catalog):
    boundary = _epoch("2025-03-01 23:59:59")
    clock = Clock(boundary)
    engine = ScriptedEngine([(500, 900), (500, 900)])
    svc = make_service(db, approved_catalog, engine, clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    player = await _player(db)

    await svc.challenge(
        player=player, challenge_id="c-day1", instance_id=instance["instance_id"]
    )
    first = await _attempts(db, "2025-03-01")
    assert first["attempts_used"] == 1

    clock.advance(1)  # 北京时间跨日
    result = await svc.challenge(
        player=player, challenge_id="c-day2", instance_id=instance["instance_id"]
    )
    assert result.ok is True
    assert (await _attempts(db, "2025-03-01"))["attempts_used"] == 1
    second = await _attempts(db, "2025-03-02")
    assert second["attempts_used"] == 1


async def test_stale_snapshot_commit_is_rejected_and_computed_again(
    db, approved_catalog
):
    clock = Clock(T0)
    engine = ScriptedEngine([(500, 900), (500, 800)])
    svc = make_service(db, approved_catalog, engine, clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    instance_id = instance["instance_id"]

    snapshot = await svc._prepare_challenge("u1", instance_id, T0)
    assert isinstance(snapshot, dict)
    combat = await svc._run_challenge_combat(snapshot, 1234)
    first = await svc._commit_challenge(snapshot, combat, challenge_id="c-1")
    assert first is not None and first.ok is True

    stale = await svc._commit_challenge(snapshot, combat, challenge_id="c-2")
    assert stale is None
    assert await _count(db, "world_boss_challenges") == 1
    assert (await _attempts(db, "2023-11-15"))["attempts_used"] == 1
    assert (await _instance(db, instance_id))["current_hp"] == 900


async def test_failed_attempt_guard_rolls_back_instance_damage_and_ledger(
    db, approved_catalog
):
    """AC4 故障注入：提交阶段次数递增失败 → 整笔事务回滚，实例/玩家/台账不变。"""
    clock = Clock(T0)
    engine = ScriptedEngine([(500, 900)])
    svc = make_service(db, approved_catalog, engine, clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    instance_id = instance["instance_id"]

    snapshot = await svc._prepare_challenge("u1", instance_id, T0)
    assert isinstance(snapshot, dict)
    combat = await svc._run_challenge_combat(snapshot, 7)
    # 注入故障：准备与提交之间，并发挑战把当日次数消耗到上限。
    repo = WorldBossRepository(db.conn)
    for _ in range(3):
        await repo.increment_daily_attempts(
            date_key="2023-11-15", user_id="u1", limit=3
        )

    rejected = await svc._commit_challenge(snapshot, combat, challenge_id="c-abort")
    assert rejected is not None and rejected.ok is False
    assert "挑战次数已用完" in rejected.message
    assert (await _instance(db, instance_id))["current_hp"] == LQ_BA_HP
    assert (await _player(db)).current_hp == 500
    assert await _count(db, "world_boss_challenges") == 0
    assert await _count(db, "world_boss_ledger") == 0
    assert await _count(db, "world_boss_contributions") == 0
    assert (await _attempts(db, "2023-11-15"))["attempts_used"] == 3
    assert [event["event_type"] for event in await _events(db)] == [
        _events_mod.EVENT_SPAWN
    ]


async def test_concurrent_ensure_spawn_lands_exactly_one_instance(db, approved_catalog):
    """AC1/AC8 并发 ensure：确定性 id + 单事务读插，只落一行。"""
    clock = Clock(T0)
    svc = make_service(db, approved_catalog, ScriptedEngine(), clock=clock)

    results = await asyncio.gather(*(svc.ensure_spawn() for _ in range(3)))

    assert sum(1 for _, created, _ in results if created) == 1
    assert len({row["instance_id"] for row, _, _ in results}) == 1
    assert await _count(db, "world_boss_instances") == 1
    assert [event["event_type"] for event in await _events(db)] == [
        _events_mod.EVENT_SPAWN
    ]


async def test_concurrent_challenges_never_exceed_daily_cap(db, approved_catalog):
    """AC4/AC8 并发挑战：每日 3 次上限不超扣，伤害逐笔落账。"""
    clock = Clock(T0)
    engine = ScriptedEngine([(500, 900)] * 12)
    svc = make_service(db, approved_catalog, engine, clock=clock)
    instance, _, _ = await svc.ensure_spawn(LQ_BA)
    instance_id = instance["instance_id"]
    player = await _player(db)

    results = await asyncio.gather(
        *(
            svc.challenge(
                player=player,
                challenge_id=f"c-race-{index}",
                instance_id=instance_id,
            )
            for index in range(4)
        )
    )

    assert sum(1 for result in results if result.ok) == 3
    assert (await _attempts(db, "2023-11-15"))["attempts_used"] == 3
    assert await _count(db, "world_boss_challenges") == 3
    async with db.conn.execute(
        "SELECT COALESCE(SUM(damage_dealt), 0) FROM world_boss_ledger"
    ) as cursor:
        ledger_total = (await cursor.fetchone())[0]
    final_hp = (await _instance(db, instance_id))["current_hp"]
    # 并发下重算会改变单场伤害，但“台账累计 = 面板掉血”恒等，证明无超扣/漏扣。
    assert ledger_total == LQ_BA_HP - final_hp


async def test_profile_document_roundtrip_keeps_narrative_contract():
    """AC6 builder→validator→WorldBossProfile.from_dict 往返不丢失五文案与批准位。"""
    doc = _approved_doc()
    assert _schema_mod.validate_enemy_document(doc) == []
    entry = doc["world_bosses"][0]
    profile = _catalog_mod.WorldBossProfile.from_dict(entry)

    assert profile.profile_version == 1
    assert profile.narrative_approved is True
    for key in (
        "spawn_text",
        "phase2_text",
        "phase3_text",
        "kill_text",
        "dissipate_text",
    ):
        assert getattr(profile, key) == entry[key]

    missing = dict(entry)
    missing.pop("kill_text")
    with pytest.raises(KeyError):
        _catalog_mod.WorldBossProfile.from_dict(missing)

    unapproved = dict(entry, narrative_approved=False)
    assert (
        _catalog_mod.WorldBossProfile.from_dict(unapproved).narrative_approved is False
    )


# ─────────────────────── 静态约束 / 时间快进登记 ────────────────────────────


async def test_service_has_no_duplicate_floor_constant_and_no_legacy_rewards():
    source = (PLUGIN_ROOT / "managers" / "world_boss_service.py").read_text(
        encoding="utf-8"
    )
    # E1 单源地板：领域模块不得另立常量（scripts/audit_pve_redesign.py check_e1）。
    assert "DEFEAT_HP_FLOOR_RATIO" not in source
    # R6/Step 7 范围外：不引用旧的即时灵石奖励字段。
    assert "stone_reward" not in source


async def test_time_skip_registry_covers_world_boss_cooldowns():
    registry_source = (PLUGIN_ROOT / "core" / "time_skip_registry.py").read_text(
        encoding="utf-8"
    )
    assert "managers.boss_manager" in registry_source
    manager_source = (PLUGIN_ROOT / "managers" / "boss_manager.py").read_text(
        encoding="utf-8"
    )
    assert "world_boss_instances" in manager_source
    assert "next_spawn_at" in manager_source
    # 每日次数是历史事实，绝不参与时间快进。
    assert "world_boss_daily_attempts" not in manager_source

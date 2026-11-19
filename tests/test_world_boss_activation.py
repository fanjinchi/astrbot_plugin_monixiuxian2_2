"""E2 世界 Boss 激活回归：get_active / poller / handler / 暴击接线。

Covers implement steps 7–8:
- ``get_active`` settles expiry without spawning;
- the single poller keeps the fixed ``ensure_spawn(None) -> dispatch_pending``
  order, skips spawning when ``boss.enabled`` is false or the domain has no
  catalog, and treats the normal respawn-ineligibility rejection as non-fatal
  so dispatch keeps running through the terminal window;
- expired active rows cannot leave two actives across polls;
- handler/info/challenge/spawn entry points use the domain service;
- ``build_instance_fighter`` passes ``combat.base_crit_rate`` explicitly with
  per-enemy override, missing/None fallback and explicit-zero semantics.
"""

import asyncio
import random
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from tests.helpers import PLUGIN_ROOT, load_package_module
from tests.test_player_health_foundation import T0, StubConfigManager, put_player

_catalog_mod = load_package_module(
    "managers/enemy_catalog.py", "astrbot_plugin_monixiuxian2_2.managers.enemy_catalog"
)
_service_mod = load_package_module(
    "managers/world_boss_service.py",
    "astrbot_plugin_monixiuxian2_2.managers.world_boss_service",
)
_poller_mod = load_package_module(
    "managers/world_boss_poller.py",
    "astrbot_plugin_monixiuxian2_2.managers.world_boss_poller",
)
_handler_mod = load_package_module(
    "handlers/world_boss_handlers.py",
    "astrbot_plugin_monixiuxian2_2.handlers.world_boss_handlers",
)
_repo_mod = load_package_module(
    "data/pve_repository.py", "astrbot_plugin_monixiuxian2_2.data.pve_repository"
)
_migration_mod = load_package_module(
    "data/migration.py", "astrbot_plugin_monixiuxian2_2.data.migration"
)

EnemyCatalog = _catalog_mod.EnemyCatalog
WorldBossService = _service_mod.WorldBossService
spawn_with_message = _service_mod.spawn_with_message
WorldBossSpawnRejected = _service_mod.WorldBossSpawnRejected
WorldBossPoller = _poller_mod.WorldBossPoller
retry_delay_seconds = _poller_mod.retry_delay_seconds
WorldBossHandlers = _handler_mod.WorldBossHandlers
WorldBossRepository = _repo_mod.WorldBossRepository
DataBase = sys.modules["astrbot_plugin_monixiuxian2_2.data"].DataBase

ENEMIES_PATH = PLUGIN_ROOT / "config" / "enemies.json"


class Clock:
    """Advanceable business clock."""

    def __init__(self, value: int = T0) -> None:
        self.value = int(value)

    def __call__(self) -> int:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += int(seconds)


class StubHealthService:
    """Minimal health seam for spawn/query tests."""

    async def settle(self, user_id, now=None):
        return 0

    def defeat_hp_floor(self, player) -> int:
        return 0


class StubBusyState:
    """Always-idle busy seam."""

    async def assert_idle(self, user_id, template=""):
        return None


class ScriptedRng:
    """Return pre-computed seeds so each poll selects a chosen profile."""

    def __init__(self, seeds):
        self.seeds = list(seeds)

    def randrange(self, start, stop):
        return self.seeds.pop(0)


@pytest_asyncio.fixture
async def db():
    """In-memory database migrated to the latest schema with player u1."""
    database = DataBase(":memory:")
    await database.connect()
    await _migration_mod.MigrationManager(
        database.conn, StubConfigManager()
    ).migrate_or_reset()
    await put_player(database, "u1", 500, 500, anchor=T0)
    yield database
    await database.close()


@pytest.fixture(scope="module")
def catalog():
    """Formal v2 config: 4 world-boss profiles, narrative approved."""
    return EnemyCatalog.load(ENEMIES_PATH)


def _config(*, difficulty=1.0, base_crit_rate=None, include_combat=True):
    combat = {"base_crit_rate": base_crit_rate} if include_combat else {}
    return SimpleNamespace(
        game_config={"pve": {"difficulty_multiplier": difficulty}, "combat": combat}
    )


def _service(db, catalog, *, clock=None, rng=None, config=None):
    return WorldBossService(
        db,
        catalog,
        StubHealthService(),
        StubBusyState(),
        MagicMock(),
        config if config is not None else _config(),
        clock=clock if clock is not None else Clock(T0),
        rng=rng,
    )


async def _instances(db):
    async with db.conn.execute(
        "SELECT * FROM world_boss_instances ORDER BY spawned_at, rowid"
    ) as cursor:
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_get_active_settles_expiry_without_spawning(db, catalog):
    """Querying an expired instance dissipates it and creates no replacement."""
    clock = Clock(T0)
    service = _service(db, catalog, clock=clock)
    instance, created, _ = await service.ensure_spawn()
    assert created is True

    clock.value = int(instance["expires_at"]) + 1
    assert await service.get_active() is None

    rows = await _instances(db)
    assert len(rows) == 1
    assert rows[0]["instance_id"] == instance["instance_id"]
    assert rows[0]["state"] == "dissipated"
    assert rows[0]["next_spawn_at"] > 0


@pytest.mark.asyncio
async def test_expired_instance_between_polls_keeps_single_active(db, catalog):
    """An instance expiring between polls cannot leave two active rows."""
    # Find two seeds that pick different profiles (regular path uses randrange).
    profiles = catalog.world_bosses
    seeds = []
    for seed in range(1, 50):
        pick = random.Random(seed).randrange(len(profiles))
        if not seeds:
            seeds.append((seed, pick))
        elif pick != seeds[0][1]:
            seeds.append((seed, pick))
            break
    assert len(seeds) == 2, "need two seeds selecting different profiles"

    clock = Clock(T0)
    service = _service(
        db, catalog, clock=clock, rng=ScriptedRng([seeds[0][0], seeds[1][0]])
    )
    first, created, first_profile = await service.ensure_spawn()
    assert created is True and first_profile == profiles[seeds[0][1]].id

    # 第一次轮询后到期；下一次轮询必须等到再生资格时刻才能生成新档案
    clock.value = int(first["expires_at"]) + 24 * 3600 + 1
    second, created, second_profile = await service.ensure_spawn()
    assert created is True
    assert second_profile == profiles[seeds[1][1]].id
    assert second_profile != first_profile

    rows = await _instances(db)
    assert [row["state"] for row in rows] == ["dissipated", "active"]
    active = [row for row in rows if row["state"] == "active"]
    assert len(active) == 1


@pytest.mark.asyncio
async def test_poller_skips_spawn_but_dispatches_when_disabled():
    """``boss.enabled=false`` skips ensure_spawn but never stalls the outbox."""
    calls = []
    service = MagicMock()
    service.ensure_spawn = AsyncMock(side_effect=lambda *_: calls.append("spawn"))
    dispatcher = MagicMock()
    dispatcher.dispatch_pending = AsyncMock(
        side_effect=lambda: calls.append("dispatch")
    )

    poller = WorldBossPoller(service, dispatcher, lambda: False)
    await poller.poll_once()

    assert calls == ["dispatch"]
    service.ensure_spawn.assert_not_awaited()
    dispatcher.dispatch_pending.assert_awaited_once()


@pytest.mark.asyncio
async def test_poller_dispatches_after_terminal_state(db, catalog):
    """Post-kill ineligibility is a normal round: no raise, dispatch still runs.

    Regression: the regular path rejects ``ensure_spawn(None)`` until
    ``next_spawn_at`` (12h after a kill / 24h after dissipation). Rethrowing it
    would skip ``dispatch_pending`` for the whole window and starve the outbox.
    """
    clock = Clock(T0)
    service = _service(db, catalog, clock=clock)
    instance, created, _ = await service.ensure_spawn()
    assert created is True

    # Normal terminal state after a kill: 12h until the next respawn.
    await db.conn.execute(
        "UPDATE world_boss_instances SET state='defeated', terminated_at=?, "
        "next_spawn_at=? WHERE instance_id=?",
        (T0, T0 + 12 * 3600, instance["instance_id"]),
    )
    await db.conn.commit()
    clock.advance(60)

    dispatcher = MagicMock()
    dispatcher.dispatch_pending = AsyncMock()
    poller = WorldBossPoller(service, dispatcher, lambda: True)

    await poller.poll_once()

    dispatcher.dispatch_pending.assert_awaited_once()
    rows = await _instances(db)
    assert [row["state"] for row in rows] == ["defeated"]
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_poller_skips_spawn_when_domain_has_no_catalog():
    """v1/absent ``enemies.json`` disables spawning but keeps dispatch alive."""
    service = MagicMock()
    service.enabled = False
    service.ensure_spawn = AsyncMock()
    dispatcher = MagicMock()
    dispatcher.dispatch_pending = AsyncMock()

    poller = WorldBossPoller(service, dispatcher, lambda: True)
    await poller.poll_once()

    service.ensure_spawn.assert_not_awaited()
    dispatcher.dispatch_pending.assert_awaited_once()


@pytest.mark.asyncio
async def test_poller_reconnects_before_each_round():
    """Scheduled loop re-checks the DB connection before touching anything."""
    calls = []
    service = MagicMock()
    service.enabled = False
    dispatcher = MagicMock()
    dispatcher.dispatch_pending = AsyncMock(
        side_effect=lambda: calls.append("dispatch")
    )

    async def _reconnect():
        calls.append("connect")

    poller = WorldBossPoller(
        service, dispatcher, lambda: True, ensure_connection=_reconnect
    )
    await poller.poll_once()

    assert calls == ["connect", "dispatch"]


@pytest.mark.asyncio
async def test_poller_real_errors_still_back_off():
    """Only the domain's normal rejection is swallowed; real failures retry.

    Boundary of the terminal-window fix above: a database/transport exception
    must not be mistaken for "not eligible yet". It skips dispatch for that
    round (the round failed) and enters the exponential backoff schedule.
    """
    service = MagicMock()
    service.ensure_spawn = AsyncMock(side_effect=RuntimeError("database is gone"))
    dispatcher = MagicMock()
    dispatcher.dispatch_pending = AsyncMock()
    delays: list[float] = []

    async def _sleep(delay):
        delays.append(delay)
        if len(delays) >= 2:
            raise asyncio.CancelledError

    poller = WorldBossPoller(service, dispatcher, lambda: True, sleep=_sleep)

    with pytest.raises(asyncio.CancelledError):
        await poller.run()

    # Failures before each retry: 60s, 120s (min(60 * 2**n, 3600)).
    assert delays == [60, 120]
    dispatcher.dispatch_pending.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_repositories_follow_reconnect(tmp_path, catalog):
    """A replaced connection is picked up; no repository caches ``db.conn``.

    Scheduled rounds call ``ensure_connection`` first, which may rebuild the
    underlying connection. Repository properties must bind on use, otherwise
    the service would keep writing to the closed handle.
    """
    database = DataBase(str(tmp_path / "reconnect.db"))
    await database.connect()
    await _migration_mod.MigrationManager(
        database.conn, StubConfigManager()
    ).migrate_or_reset()
    await put_player(database, "u1", 500, 500, anchor=T0)
    try:
        service = _service(database, catalog)
        instance, created, _ = await service.ensure_spawn()
        assert created is True
        old_conn = database.conn

        await database.reconnect()
        assert database.conn is not old_conn
        assert service.instances.conn is database.conn
        assert service.outbox.conn is database.conn

        active = await service.get_active()
        assert active is not None
        assert active["instance_id"] == instance["instance_id"]
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_poller_orders_ensure_spawn_then_dispatch():
    """Enabled round: ensure_spawn(None) strictly precedes dispatch_pending."""
    calls = []
    service = MagicMock()
    service.ensure_spawn = AsyncMock(side_effect=lambda *_: calls.append("spawn"))
    dispatcher = MagicMock()
    dispatcher.dispatch_pending = AsyncMock(
        side_effect=lambda: calls.append("dispatch")
    )

    poller = WorldBossPoller(service, dispatcher, lambda: True)
    await poller.poll_once()

    assert calls == ["spawn", "dispatch"]
    service.ensure_spawn.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test_poller_start_is_idempotent_and_stop_cancels():
    """A second start does not create a second loop; stop cancels the task."""
    service = MagicMock()
    service.ensure_spawn = AsyncMock()
    dispatcher = MagicMock()
    dispatcher.dispatch_pending = AsyncMock()

    async def _never(_delay):
        await asyncio.Event().wait()

    poller = WorldBossPoller(service, dispatcher, lambda: False, sleep=_never)
    poller.start()
    first = poller._task
    poller.start()
    assert poller._task is first

    await poller.stop()
    assert first.cancelled() is True
    assert poller.running is False


def test_retry_backoff_formula():
    """Backoff follows min(60 * 2**n, 3600)."""
    assert retry_delay_seconds(0) == 60
    assert retry_delay_seconds(1) == 120
    assert retry_delay_seconds(5) == 1920
    assert retry_delay_seconds(10) == 3600


@pytest.mark.asyncio
async def test_handler_info_and_fight_use_domain_service():
    """``世界Boss`` reads get_active; ``挑战Boss`` delegates one challenge id."""
    db = MagicMock()
    db.get_player_by_id = AsyncMock(return_value=SimpleNamespace(user_id="u1"))
    service = MagicMock()
    service.get_active = AsyncMock(return_value=None)
    service.challenge = AsyncMock(
        return_value=_service_mod.ChallengeResult(ok=True, message="已结算")
    )
    handler = WorldBossHandlers(db, service)

    event = SimpleNamespace(plain_result=lambda text: text)
    messages = [msg async for msg in handler.handle_boss_info(event)]
    assert messages == ["👹 当前没有活跃的世界 Boss。"]

    ok, message = await handler.handle_boss_fight("u1", challenge_id="fixed-key")
    assert ok is True and message == "已结算"
    service.challenge.assert_awaited_once_with(
        player=db.get_player_by_id.return_value, challenge_id="fixed-key"
    )


@pytest.mark.parametrize(
    ("created", "profile_id", "expected"),
    [
        (True, None, "✅ 已生成世界Boss：裂峡罴王"),
        (False, None, "已有活跃世界 Boss 裂峡罴王。"),
        (False, "wb_zj_tuo", "已有活跃世界 Boss 裂峡罴王，未生成 泽底鼍龙。"),
    ],
)
@pytest.mark.asyncio
async def test_spawn_management_three_branches(catalog, created, profile_id, expected):
    """Created / reused / reused-with-requested-name share one message shape."""
    service = MagicMock()
    service.catalog = catalog
    service.ensure_spawn = AsyncMock(
        return_value=(
            {"boss_name": "裂峡罴王"},
            created,
            "wb_lq_ba" if created else "wb_lq_ba",
        )
    )

    ok, message = await spawn_with_message(service, profile_id)

    assert ok is True
    assert message == expected


@pytest.mark.asyncio
async def test_spawn_rejection_is_user_readable():
    """Domain rejections are returned verbatim, never raised into the handler."""
    service = MagicMock()
    service.ensure_spawn = AsyncMock(
        side_effect=WorldBossSpawnRejected("❌ 世界 Boss 尚未到再生时间。")
    )

    ok, message = await spawn_with_message(service, None)

    assert ok is False
    assert "尚未到再生时间" in message


def _instance_row(crit_rate=0):
    """Minimal persisted instance row for the fighter builder."""
    return {
        "instance_id": "wb_test_1700000000",
        "profile_id": "wb_lq_ba",
        "boss_name": "裂峡罴王",
        "boss_level": 1,
        "max_hp": 1000,
        "current_hp": 800,
        "atk": 18,
        "agility": 8,
        "speed": 11,
        "armor_value": 7,
        "phase": 1,
        "birth_snapshot": {
            "crit_rate": crit_rate,
            "difficulty_multiplier": 1.0,
            "trigger_skills": [],
            "ultimates": [],
            "phase_thresholds": [0.6, 0.2],
            "phase2_damage_multiplier": 1.1,
            "phase3_damage_multiplier": 0.9,
            "phase3_armor_multiplier": 0.5,
        },
    }


@pytest.mark.parametrize(
    ("combat_key", "expected"),
    [
        ({"base_crit_rate": 0.27}, 0.27),
        ({"base_crit_rate": None}, 0.15),
        ({"base_crit_rate": 0}, 0),
        ({}, 0.15),
    ],
)
def test_instance_fighter_reads_base_crit_rate(combat_key, expected):
    """World-boss fighter uses the shared crit fallback contract."""
    service = WorldBossService(
        MagicMock(),
        None,
        StubHealthService(),
        StubBusyState(),
        MagicMock(),
        SimpleNamespace(game_config={"combat": combat_key}),
    )

    fighter = service._build_instance_fighter(_instance_row())

    assert fighter.crit_rate == pytest.approx(expected)


def test_instance_fighter_positive_per_enemy_crit_overrides():
    """A positive snapshot crit percentage overrides the config fallback."""
    service = WorldBossService(
        MagicMock(),
        None,
        StubHealthService(),
        StubBusyState(),
        MagicMock(),
        _config(base_crit_rate=0.27),
    )

    fighter = service._build_instance_fighter(_instance_row(crit_rate=8))

    assert fighter.crit_rate == pytest.approx(0.08)


def test_instance_fighter_re_reads_live_base_crit_rate():
    """Changing the global combat key affects the next fighter build."""
    config = _config(base_crit_rate=0.2)
    service = WorldBossService(
        MagicMock(),
        None,
        StubHealthService(),
        StubBusyState(),
        MagicMock(),
        config,
    )

    first = service._build_instance_fighter(_instance_row())
    config.game_config["combat"]["base_crit_rate"] = 0.35
    second = service._build_instance_fighter(_instance_row())

    assert first.crit_rate == pytest.approx(0.2)
    assert second.crit_rate == pytest.approx(0.35)

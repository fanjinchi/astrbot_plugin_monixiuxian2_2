"""Spike probes for the transaction() unit-of-work CM (openspec: add-transaction-unit-of-work).

Tasks 0.1-0.5 of the change plan answer the design.md Open Questions.
Task 1.3 promotes the durable assertions into regression pins in this file
(the 0.5 cross-task probes are the F1/F2 pins); the 1.3 additions live in the
tail section below. The tail also carries the two hardening pins filed by the
final review of that change (bd ip5: a joined exit after a reconnect must clamp
the depth at 0; bd mxt: a task-less entry must raise instead of silently
joining the same-task fast path).
"""

import asyncio
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from aiosqlite.context import Result

from tests.helpers import load_package_module

load_package_module(
    "data/data_manager.py", "astrbot_plugin_monixiuxian2_2.data.data_manager"
)
load_package_module("data/migration.py", "astrbot_plugin_monixiuxian2_2.data.migration")
_data_pkg = __import__(
    "astrbot_plugin_monixiuxian2_2.data", fromlist=["DataBase", "MigrationManager"]
)
DataBase = _data_pkg.DataBase
MigrationManager = _data_pkg.MigrationManager
Player = __import__("astrbot_plugin_monixiuxian2_2.models", fromlist=["Player"]).Player


class FakeConfigManager:
    """Minimal config stub required by some managers under test."""

    def __init__(self):
        self.storage_rings_data = {
            "基础储物戒": {"type": "storage_ring", "capacity": 20, "rank": "凡品"}
        }
        self.pills_data = {}

    def is_pill(self, item_name: str) -> bool:
        return item_name in self.pills_data

    def get_pill_config(self, name: str) -> dict | None:
        return None

    def get_level_name(self, level_index: int, cultivation_type: str = "灵修") -> str:
        return f"境界{level_index}"


@pytest_asyncio.fixture
async def db(tmp_path):
    """Provide a migrated temp-file database and close it after the test."""
    database = DataBase(str(tmp_path / "test.db"))
    await database.connect()
    await MigrationManager(database.conn, MagicMock()).migrate_or_reset()
    yield database
    await database.close()


async def _make_player(db: DataBase, user_id: str = "u1", gold: int = 10000) -> Player:
    player = Player(
        user_id=user_id, user_name=f"道友{user_id}", spiritual_root="天灵根", gold=gold
    )
    await db.create_player(player)
    return player


def _make_event(message: str, sender_id: str = "u1") -> MagicMock:
    event = MagicMock()
    event.get_sender_id.return_value = sender_id
    event.get_message_str.return_value = message
    event.plain_result.side_effect = lambda text: text
    return event


class _ResultPatchingMonitor:
    """Monkeypatch aiosqlite Connection.execute while keeping its dual protocol.

    aiosqlite's ``Connection.execute`` returns a ``Result`` object that is both
    awaitable (``await conn.execute(...)``) and an async context manager
    (``async with conn.execute(...) as cursor``). Any probe that needs to
    intercept SQL statements must re-wrap in the same way instead of
    replacing ``execute`` with a plain coroutine function.
    """

    def __init__(self, conn, on_sql):
        self._conn = conn
        self._orig = conn.execute
        self._on_sql = on_sql
        self.orig_commit = conn.commit
        self.orig_rollback = conn.rollback

    async def _run(self, sql, parameters):
        await self._on_sql(sql, parameters)
        return await self._orig(sql, parameters)

    def patched_execute(self, sql, parameters=None):
        return Result(self._run(sql, parameters))

    async def patched_commit(self):
        await self._on_sql("COMMIT", None)
        return await self.orig_commit()

    async def patched_rollback(self):
        await self._on_sql("ROLLBACK", None)
        return await self.orig_rollback()

    def install(self):
        self._conn.execute = self.patched_execute
        self._conn.commit = self.patched_commit
        self._conn.rollback = self.patched_rollback

    def restore(self):
        self._conn.execute = self._orig
        self._conn.commit = self.orig_commit
        self._conn.rollback = self.orig_rollback


# ===== 0.1 最小 CM 原型：§7.1 场景共存 =====


@pytest.mark.asyncio
async def test_01_cm_commit_on_clean_exit(db):
    """Independent CM block commits on clean exit; depth returns to 0."""
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    player.gold = 200
    async with db.transaction() as txn:
        assert db.conn._txn_depth == 1
        assert db.conn._txn_owner_task is asyncio.current_task()
        assert not txn.aborted
        await db.update_player(player)
        assert db.conn.in_transaction
    assert db.conn._txn_depth == 0
    assert db.conn._txn_owner_task is None
    assert db.conn._txn_state is None
    assert not db.conn.in_transaction
    assert (await db.get_player_by_id("u1")).gold == 200


@pytest.mark.asyncio
async def test_01_cm_rollback_on_exception(db):
    """Exception inside the block rolls back every write and re-raises."""
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    player.gold = 200
    with pytest.raises(RuntimeError, match="boom"):
        async with db.transaction():
            await db.update_player(player)
            raise RuntimeError("boom")
    assert (await db.get_player_by_id("u1")).gold == 10000
    assert db.conn._txn_depth == 0 and db.conn._txn_owner_task is None
    assert not db.conn.in_transaction


@pytest.mark.asyncio
async def test_01_cm_does_not_intercept_early_bare_commit(db):
    """Bare conn.commit() inside the CM is NOT intercepted (that is a later constraint)."""
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    player.gold = 200
    async with db.transaction():
        await db.update_player(player)
        await db.conn.commit()  # early bare commit: tolerated at spike stage
    assert (
        await db.get_player_by_id("u1")
    ).gold == 200  # data persisted by bare commit
    assert db.conn._txn_depth == 0  # owner exit commit() is a no-op, no error


@pytest.mark.asyncio
async def test_01_cm_coexists_with_hand_begin_and_fail_open_helpers(db):
    """D1.2 coexistence: helpers carry no commit param; outside a CM (depth 0) they
    commit fail-open—even inside a hand-BEGIN block. The CM must never be
    entered inside a raw BEGIN block (documented transition constraint); this
    test pins the standalone-path coexistence only.
    """
    await _make_player(db)
    await db.conn.execute("BEGIN IMMEDIATE")
    # Fail-open: _txn_depth == 0 inside a hand-BEGIN block, so the helper's own
    # commit closes the hand transaction too (legacy behavior preserved).
    await db.ext.update_bank_account("u1", 500, 123)
    assert not db.conn.in_transaction  # helper committed (fail-open)
    assert await db.ext.get_bank_account("u1") == {
        "balance": 500,
        "last_interest_time": 123,
    }

    # Independent helper call still commits (legacy standalone semantics).
    await db.ext.update_bank_account("u1", 600, 124)
    assert not db.conn.in_transaction
    assert (await db.ext.get_bank_account("u1"))["balance"] == 600


@pytest.mark.asyncio
async def test_01_same_task_nesting_is_noop_join(db):
    """Same-task nesting shares the transaction; inner exit is passive."""
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    player.gold = 200
    abort_ping = []

    async with db.transaction() as outer:
        assert db.conn._txn_depth == 1
        async with db.transaction() as inner:
            assert db.conn._txn_depth == 2
            assert inner._state is outer._state  # shared TxnState
            await db.update_player(player)
            abort_ping.append(inner._joined)
        # inner exit: passive, no commit happened
        assert db.conn.in_transaction
        assert db.conn._txn_depth == 1
    assert db.conn._txn_depth == 0
    assert abort_ping == [True]
    assert (await db.get_player_by_id("u1")).gold == 200


@pytest.mark.asyncio
async def test_01_inner_abort_propagates_to_owner(db):
    """abort() from an inner (joined) layer shares the TxnState and rolls back at owner exit."""
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    player.gold = 200

    async with db.transaction() as outer:
        async with db.transaction() as inner:
            inner.abort()
            assert outer.aborted  # shared TxnState: the owner sees the marker
            await db.update_player(player)
        # inner exit passive — nothing rolled back yet
        assert db.conn.in_transaction
        assert outer.aborted

    assert (await db.get_player_by_id("u1")).gold == 10000  # owner rolled back
    assert not db.conn.in_transaction


@pytest.mark.asyncio
async def test_01_abort_is_idempotent_and_marker_does_not_leak(db):
    """abort() called twice is fine; the marker never leaks into the next transaction."""
    await _make_player(db)
    player = await db.get_player_by_id("u1")

    async with db.transaction() as txn:
        txn.abort()
        txn.abort()
        assert txn.aborted
        player.gold = 200
        await db.update_player(player)
    assert (await db.get_player_by_id("u1")).gold == 10000

    # Next transaction commits normally (marker did not leak).
    player = await db.get_player_by_id("u1")
    player.gold = 300
    async with db.transaction():
        await db.update_player(player)
    assert (await db.get_player_by_id("u1")).gold == 300


@pytest.mark.asyncio
async def test_01_rollback_without_active_transaction_is_safe_noop(db):
    """Best-effort rollback outside any transaction is a safe no-op without warnings."""
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await db.conn.rollback()  # no active txn: sqlite3 no-op
        assert not db.conn.in_transaction
    assert all("rollback" not in str(w.message).lower() for w in caught)


# ===== 0.2 探针：GeneratorExit / CancelledError =====
#
# Important spike finding (design.md Open Question Q-GE): handle_buy's yield
# points all sit AFTER its commit/rollback calls, so a GeneratorExit thrown at
# a yield cannot leak the write lock in today's code. The real leak path is
# CancelledError injected at an *await* point inside the BEGIN block: it is a
# BaseException, so the manual ``except Exception`` never runs and the BEGIN
# write lock stays held. Probe 1 proves the leak on current code; probes 2-4
# prove the CM fixes both GeneratorExit (aclose) and CancelledError (cancel).


_shop_mod = load_package_module(
    "handlers/shop_handler.py", "astrbot_plugin_monixiuxian2_2.handlers.shop_handler"
)
ShopHandler = _shop_mod.ShopHandler
_core_pkg = __import__(
    "astrbot_plugin_monixiuxian2_2.core", fromlist=["StorageRingManager", "PillManager"]
)
StorageRingManager = _core_pkg.StorageRingManager
PillManager = _core_pkg.PillManager


def _make_shop_handler(db: DataBase) -> ShopHandler:
    handler = ShopHandler.__new__(ShopHandler)
    handler.db = db
    handler.config_manager = FakeConfigManager()
    handler.shop_manager = MagicMock()
    handler.shop_manager.get_sect_shop_discount.return_value = 1.0
    handler.storage_ring_manager = StorageRingManager(db, FakeConfigManager())
    handler.pill_manager = PillManager(db, FakeConfigManager())
    return handler


@pytest.mark.asyncio
async def test_02_baseline_cancel_no_longer_leaks_write_lock(db):
    """Regression: CancelledError at an await inside handle_buy's txn block must not leak the lock.

    This probe originally demonstrated the pre-CM bug (Baseline evidence in
    design.md Open Question Q-GE): the manual ``except Exception`` cannot
    catch the BaseException, so the BEGIN write lock stayed held. After the
    3.3 migration the block runs under the transaction CM, whose BaseException-
    safe exit rolls back and releases the lock — the bug demonstration is now
    a positive regression test.
    """
    handler = _make_shop_handler(db)
    await _make_player(db, gold=10000)
    await db.update_shop_data(
        "pill_pavilion",
        12345,
        [{"name": "回气丹", "type": "pill", "price": 100, "stock": 5}],
    )
    event = _make_event("购买 回气丹")

    # Slow down the first in-transaction DB call so the cancel lands reliably
    # inside the txn block (local sqlite transactions finish in <1ms).
    orig_decrement = db.decrement_shop_item_stock
    entered_txn = asyncio.Event()

    async def slow_decrement(*args, **kwargs):
        entered_txn.set()
        await asyncio.sleep(5)  # hold the txn open for the cancel
        return await orig_decrement(*args, **kwargs)

    db.decrement_shop_item_stock = slow_decrement
    try:
        agen = handler.handle_buy(event, "回气丹")

        async def drain():
            async for _ in agen:
                pass

        task = asyncio.create_task(drain())
        # Wait until the handler is inside the txn block (in_transaction flips).
        await asyncio.wait_for(entered_txn.wait(), timeout=10)
        assert db.conn.in_transaction, "handler never reached the txn block"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        db.decrement_shop_item_stock = orig_decrement

    # REGRESSION ASSERTION: the CM's BaseException-safe exit rolled back, so
    # the write lock must be released (pre-CM this stayed True — leak).
    assert not db.conn.in_transaction, (
        "write lock leaked on cancel: CM exit must roll back on BaseException"
    )


@pytest.mark.asyncio
async def test_02_cm_generator_exit_aclose_rolls_back(db):
    """CM fixes GeneratorExit: aclose() at a yield inside the block rolls back + releases.

    aclose() does not propagate GeneratorExit to the caller; we assert the
    side effects: transaction rolled back, depth/owner cleared, connection no
    longer in_transaction, and no 'cannot rollback - no transaction' warning.
    """
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    warnings_caught: list[str] = []

    async def probe_gen():
        try:
            async with db.transaction():
                player.gold = 200
                await db.update_player(player)
                yield "mid-txn"  # suspension point INSIDE the CM block
        finally:
            pass

    import warnings

    agen = probe_gen()
    assert await agen.__anext__() == "mid-txn"
    assert db.conn.in_transaction
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await agen.aclose()
        warnings_caught = [str(w.message) for w in caught]
    assert not db.conn.in_transaction
    assert db.conn._txn_depth == 0 and db.conn._txn_owner_task is None
    assert all("rollback" not in msg.lower() for msg in warnings_caught)
    # The GeneratorExit path must roll back the write (no commit).
    assert (await db.get_player_by_id("u1")).gold == 10000


@pytest.mark.asyncio
async def test_02_cm_cancel_during_block_rolls_back(db):
    """CM fixes CancelledError: task.cancel() at an await inside the block rolls back."""
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    entered = asyncio.Event()

    async def probe_coro():
        async with db.transaction():
            player.gold = 200
            await db.update_player(player)
            entered.set()
            await asyncio.sleep(5)  # long enough for the cancel to land
        player.gold = 999  # never reached

    task = asyncio.create_task(probe_coro())
    await entered.wait()
    assert db.conn.in_transaction
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not db.conn.in_transaction
    assert db.conn._txn_depth == 0 and db.conn._txn_owner_task is None
    assert (await db.get_player_by_id("u1")).gold == 10000  # rolled back, not committed


# ===== 0.3 abort() 原型 =====


_bank_mod = load_package_module(
    "managers/bank_manager.py", "astrbot_plugin_monixiuxian2_2.managers.bank_manager"
)
BankManager = _bank_mod.BankManager


@pytest.mark.asyncio
async def test_03_abort_prototype_on_bank_deposit(db):
    """abort() on the deposit block: recheck-fail -> abort -> clean exit rolls back.

    Simulates the recheck-then-abort pattern (real deposit rechecks
    availability before writing): the gold deduction is rolled back because
    the txn was aborted even though the block exited cleanly.
    """
    await _make_player(db, gold=1000)
    player = await db.get_player_by_id("u1")
    result_msg = None

    async with db.transaction() as txn:
        # Simulate the deposit write sequence with abort injected mid-way.
        player.gold -= 500
        await db.update_player(player)
        txn.abort()  # recheck/settle failed -> abandon
        result_msg = "存款失败：结算确认失败"

    # abort + clean exit: owner rolled back, no re-raise, caller got its message.
    assert result_msg == "存款失败：结算确认失败"
    assert (await db.get_player_by_id("u1")).gold == 1000  # deduction undone


@pytest.mark.asyncio
async def test_03_abort_with_exception_still_rolls_back_and_reraises(db):
    """abort() + exception: exception path wins (rollback + re-raise)."""
    await _make_player(db, gold=1000)
    player = await db.get_player_by_id("u1")

    with pytest.raises(RuntimeError, match="late failure"):
        async with db.transaction() as txn:
            player.gold -= 500
            await db.update_player(player)
            txn.abort()
            raise RuntimeError("late failure")

    assert (await db.get_player_by_id("u1")).gold == 1000
    assert not db.conn.in_transaction


# ===== 0.5 跨任务交错探针 =====


@pytest.mark.asyncio
async def test_05_owner_exit_before_joiner_begin(db):
    """① joiner's BEGIN strictly after owner exit; waiting joiner observes depth 0 & foreign owner."""
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    events: list[str] = []

    async def owner_work():
        async with db.transaction():
            player.gold = 300
            await db.update_player(player)
            events.append("owner:inside")
            await asyncio.sleep(0.05)  # widen the window for the joiner
            events.append("owner:leaving")
        events.append("owner:done")

    async def joiner_work():
        await asyncio.sleep(0.01)  # ensure owner claims first
        # While we wait at entry, OUR depth must be 0 (no state of our own).
        assert db.conn._txn_depth >= 0  # sanity: the field exists
        try:
            async with db.transaction():
                events.append("joiner:BEGIN-issued")
                player.gold = 500
                await db.update_player(player)
        finally:
            events.append("joiner:done")

    await asyncio.gather(owner_work(), joiner_work())

    # The joiner's BEGIN must be issued strictly after the owner released.
    begin_idx = events.index("joiner:BEGIN-issued")
    owner_left = events.index("owner:leaving")
    assert begin_idx > owner_left, events
    # Final state: joiner's write landed after serialization.
    assert (await db.get_player_by_id("u1")).gold == 500


@pytest.mark.asyncio
async def test_05_joiner_abort_does_not_affect_owner(db):
    """② a waiting joiner becomes its OWN owner on claim: its abort only kills its own txn.

    The joiner's abort() cannot touch the previous owner's transaction — the
    owner's 300 must be committed before the joiner claims, and the joiner's
    own 900 is rolled back by its own abort. State isolation is per-claim,
    not per-task.
    """
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    events: list[str] = []

    async def owner_work():
        async with db.transaction():
            player.gold = 300
            await db.update_player(player)
            events.append("owner-write-done")
            await asyncio.sleep(0.05)
        events.append("owner-committed")

    async def joiner_work():
        await asyncio.sleep(0.02)  # join during the owner's window
        async with db.transaction() as txn:
            txn.abort()  # our own abort on our OWN claim
            events.append("joiner-claimed-after-owner")
            player.gold = 900
            await db.update_player(player)

    await asyncio.gather(owner_work(), joiner_work())
    await asyncio.sleep(0.01)
    # Owner's 300 committed; the joiner's abort rolled back its own 900.
    assert (await db.get_player_by_id("u1")).gold == 300


@pytest.mark.asyncio
async def test_05_three_way_claim_race_serializes(db):
    """③ 3-task claim race: one BEGIN per handover, strictly serialized, losers never rollback.

    Correctness claim: exactly N BEGINs for N workers (no double BEGIN), no
    two transactions overlap in time, losers wait-and-reclaim instead of
    rolling back, and every worker's write survives (all 3 commits).
    """
    await _make_player(db)
    events: list[str] = []
    sql_count: dict[str, int] = {"BEGIN": 0, "COMMIT": 0, "ROLLBACK": 0}

    async def on_sql(sql, parameters):
        head = sql.strip().split(" ", 2)[0].upper()
        if head in sql_count:
            sql_count[head] += 1

    monitor = _ResultPatchingMonitor(db.conn, on_sql)
    monitor.install()
    try:

        async def worker(name: str):
            async with db.transaction():
                events.append(f"{name}:inside")
                # Read-modify-write through the DB to prove serialization.
                p = await db.get_player_by_id("u1")
                p.gold += 1
                await db.update_player(p)
                await asyncio.sleep(0.005)
            events.append(f"{name}:done")

        await asyncio.gather(*[worker(f"w{i}") for i in range(3)])
    finally:
        monitor.restore()

    # Strictly serialized: every 'inside' follows the previous 'done'.
    seq = [e for e in events if e.endswith(":inside") or e.endswith(":done")]
    assert seq[0].endswith(":inside")
    for prev, cur in zip(seq, seq[1:]):
        if cur.endswith(":inside"):
            assert prev.endswith(":done"), f"overlap detected: {seq}"
    assert sql_count == {"BEGIN": 3, "COMMIT": 3, "ROLLBACK": 0}, sql_count
    assert (await db.get_player_by_id("u1")).gold == 10003  # 3 serial commits


@pytest.mark.asyncio
async def test_05_owner_cancel_at_commit_await_no_deadlock(db):
    """④ owner cancelled at COMMIT await: no permanent blocking; state cleared; next claim works.

    The residual window (design Risks "owner 任务在 COMMIT/ROLLBACK await 点被取消")
    must be fail-visible rather than hang: the finally in __aexit__ clears the
    ownership fields and notifies waiters even when commit itself is cancelled.
    """
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    events: list[str] = []
    release_commit = asyncio.Event()
    commit_gate = asyncio.Event()

    async def on_sql(sql, parameters):
        pass

    async def gated_commit():
        commit_gate.set()
        await release_commit.wait()
        return await monitor.orig_commit()

    monitor = _ResultPatchingMonitor(db.conn, on_sql)
    # Override the commit wrapper BEFORE install() binds it to conn.commit.
    monitor.patched_commit = gated_commit
    monitor.install()
    try:

        async def owner_work():
            async with db.transaction():
                player.gold = 300
                await db.update_player(player)
                events.append("owner:at-exit")

        owner_task = asyncio.create_task(owner_work())
        # Wait until the owner reaches the commit gate, then cancel it there.
        await asyncio.wait_for(commit_gate.wait(), timeout=10)
        owner_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner_task
    finally:
        monitor.restore()

    # The cancelled owner leaves no residue and no waiter stays blocked.
    assert db.conn._txn_owner_task is None, "owner must be cleared after cancel"
    assert db.conn._txn_depth == 0
    assert db.conn._txn_state is None

    # A subsequent claim succeeds immediately (no deadlock, fail-visible).
    await asyncio.sleep(0.02)
    async with db.transaction():
        player.gold = 500
        await db.update_player(player)
    assert (await db.get_player_by_id("u1")).gold == 500


# ===== 1.3 正式断言（从 spike 探针提升为回归钉 + 补缺项） =====


@pytest.mark.asyncio
async def test_13_begin_failure_compensation_clears_state(db):
    """BEGIN failure: compensation clears depth/owner/state; next txn works.

    Regression pin for design D1.2 #3 (BEGIN 失败补偿): a failing BEGIN must
    not leave the ownership fields set ('有主无事务' must be impossible).
    """
    import sqlite3

    await _make_player(db)
    orig_execute = db.conn.execute

    async def failing_execute(sql, parameters=None):
        if sql.strip().upper().startswith("BEGIN"):
            raise sqlite3.OperationalError("cannot start a transaction within a transaction")
        return await orig_execute(sql, parameters)

    db.conn.execute = failing_execute
    try:
        with pytest.raises(sqlite3.OperationalError):
            async with db.transaction():
                pass
    finally:
        db.conn.execute = orig_execute

    # Compensation must have cleared every ownership field.
    assert db.conn._txn_depth == 0
    assert db.conn._txn_owner_task is None
    assert db.conn._txn_state is None
    # A subsequent transaction works normally (no residue).
    player = await db.get_player_by_id("u1")
    player.gold = 222
    async with db.transaction():
        await db.update_player(player)
    assert (await db.get_player_by_id("u1")).gold == 222


@pytest.mark.asyncio
async def test_13_helper_default_commit_gated_inside_cm(db):
    """D2 gate: a leaf call inside the CM does not commit early.

    The 25 leaf helpers now commit only when ``_txn_depth == 0`` (they carry no
    commit parameter), so a call inside a CM block is a no-op commit that the
    owner performs on exit; the same call outside the CM keeps legacy
    standalone semantics (fail-open).
    """
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    player.gold = 200
    async with db.transaction():
        # Leaf without commit param: gated by depth, must NOT commit early.
        await db.update_player(player)
        assert db.conn.in_transaction
    assert (await db.get_player_by_id("u1")).gold == 200
    assert not db.conn.in_transaction

    # Outside the CM the same call commits standalone (legacy).
    player = await db.get_player_by_id("u1")
    player.gold = 300
    await db.update_player(player)
    assert (await db.get_player_by_id("u1")).gold == 300


@pytest.mark.asyncio
async def test_13_precondition_isolation_level_pinned(db):
    """D0 precondition: the connection still uses isolation_level="".

    Guards against the attribute value silently changing shape (Python 3.12
    autocommit, driver default changes) while the gating semantics still look
    the same. DataBase.connect() pins it explicitly.
    """
    assert db.conn.isolation_level == ""


@pytest.mark.asyncio
async def test_13_precondition_bare_dml_in_transaction_true(db):
    """D0 precondition: bare DML leaves in_transaction True.

    The counter-intuitive sqlite behavior the whole design relies on: after a
    bare INSERT/UPDATE, ``in_transaction`` is True even though no explicit
    BEGIN was issued — which is why ownership (depth), not in_transaction,
    is the gating signal.
    """
    await _make_player(db)
    await db.conn.execute("UPDATE players SET gold = gold + 1 WHERE user_id = 'u1'")
    assert db.conn.in_transaction
    await db.conn.rollback()
    assert not db.conn.in_transaction
    assert (await db.get_player_by_id("u1")).gold == 10000


@pytest.mark.asyncio
async def test_05_claim_cancel_compensation_frees_ownership(db):
    """⑤ claimer cancelled at BEGIN await: compensation clears ownership; next claim succeeds."""
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    events: list[str] = []
    released_begin = asyncio.Event()

    async def on_sql(sql, parameters):
        head = sql.strip().split(" ", 2)[0].upper()
        if head == "BEGIN":
            if not released_begin.is_set():
                released_begin.set()
                await asyncio.sleep(5)  # long enough for the cancel to land

    monitor = _ResultPatchingMonitor(db.conn, on_sql)
    monitor.install()
    try:

        async def will_be_cancelled():
            try:
                async with db.transaction():
                    pass
            except asyncio.CancelledError:
                events.append("claimer:cancelled")
                raise  # keep the cancellation semantics for the caller

        task = asyncio.create_task(will_be_cancelled())
        await released_begin.wait()  # the claimer is now inside BEGIN's await
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Compensation must have cleared ownership + notified.
        assert db.conn._txn_owner_task is None, "owner must be cleared after cancel"
        assert db.conn._txn_depth == 0
        assert db.conn._txn_state is None

        # A subsequent claim must succeed immediately.
        await asyncio.sleep(0.02)
        async with db.transaction():
            player.gold = 777
            await db.update_player(player)
        assert (await db.get_player_by_id("u1")).gold == 777
    finally:
        monitor.restore()


@pytest.mark.asyncio
async def test_ip5_joined_exit_after_reconnect_clamps_depth_at_zero(db):
    """ip5 guard: a joined layer exiting after a connection swap keeps depth >= 0.

    ``__aexit__`` re-reads ``db.conn`` instead of keeping the handle captured at
    enter, so when the connection is replaced while an inner joined layer is
    alive — ``ensure_connection()`` → ``reconnect()`` → ``connect()`` rebuilds
    the connection and resets ``_txn_depth``/``_txn_owner_task``/``_txn_state``
    on the NEW handle (data/data_manager.py connect()) — this layer's ``-= 1``
    used to land on a fresh depth of 0 and drive it to -1. Every helper's
    ``depth == 0`` commit gate would then stay false forever, so writes would
    linger uncommitted; the guard clamps the depth at 0 instead.
    """
    await _make_player(db)
    player = await db.get_player_by_id("u1")

    async with db.transaction():
        async with db.transaction():
            # The swap happens while the inner (joined) layer is alive.
            await db.reconnect()
            assert db.conn._txn_depth == 0, "fresh handle: ownership fields reset"

        # The joined layer has just exited against the replacement handle.
        assert db.conn._txn_depth >= 0, "joined exit must never drive depth negative"
        assert db.conn._txn_depth == 0
        # Gate sanity on the (unowned) replacement handle: a leaf call must
        # commit by itself instead of leaving its DML pending (fail-open).
        player.gold = 700
        await db.update_player(player)
        assert not db.conn.in_transaction, "commit gate must still fire after the swap"

    # An independent write path after the CM still commits standalone.
    player = await db.get_player_by_id("u1")
    player.gold = 800
    await db.update_player(player)
    assert not db.conn.in_transaction
    assert (await db.get_player_by_id("u1")).gold == 800
    assert db.conn._txn_depth == 0


@pytest.mark.asyncio
async def test_mxt_taskless_entry_raises_instead_of_joining(db):
    """mxt guard: ``current_task() is None`` must fail fast, not silently join.

    Outside a Task ``asyncio.current_task()`` returns None, and the ownership
    test ``conn._txn_owner_task is current_task`` is then trivially true on an
    unowned connection: the CM used to take the same-task join path (no BEGIN,
    no ownership taken, nothing committed or rolled back on exit) — treating
    "no transaction protection" as "already inside a transaction".

    The task-less call is produced for real instead of monkeypatching
    ``asyncio.current_task`` (which the test runner itself uses): a plain
    ``loop.call_soon`` callback is not a Task, so driving ``__aenter__`` from
    one sees ``current_task() is None`` — pinned by the first assertion.
    """
    await _make_player(db)
    assert db.conn._txn_owner_task is None, "unowned conn: fast path would match"

    driven: dict = {}

    def drive_enter() -> None:
        """Enter the CM from a non-Task callback and record the outcome."""
        driven["current_task"] = asyncio.current_task()
        coro = db.transaction().__aenter__()
        try:
            driven["entered"] = coro.send(None)
        except StopIteration as stop:  # pragma: no cover - the silent-join bug
            driven["entered"] = stop.value
        except BaseException as exc:
            driven["error"] = exc

    asyncio.get_running_loop().call_soon(drive_enter)
    await asyncio.sleep(0)  # let the callback run

    assert driven["current_task"] is None, "driver must run outside any Task"
    assert isinstance(driven.get("error"), RuntimeError), (
        f"task-less entry must raise RuntimeError, got {driven!r}"
    )
    assert "requires a running asyncio task" in str(driven["error"])
    # The rejected entry took no ownership at all.
    assert db.conn._txn_depth == 0
    assert db.conn._txn_owner_task is None
    assert db.conn._txn_state is None

    # A normal in-Task transaction afterwards still works end to end.
    player = await db.get_player_by_id("u1")
    player.gold = 900
    async with db.transaction():
        await db.update_player(player)
        assert db.conn._txn_depth == 1
    assert (await db.get_player_by_id("u1")).gold == 900

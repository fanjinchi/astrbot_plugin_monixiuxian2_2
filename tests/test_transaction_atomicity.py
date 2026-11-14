"""Regression tests for transaction atomicity (openspec: add-transaction-unit-of-work).

Covers design D1/D1.2 + D2:
1. Helper contract — every data-layer leaf carries NO commit parameter; the
   D2 depth gate commits only when ``conn._txn_depth == 0`` (fail-open keeps
   legacy standalone semantics). Inside a ``db.transaction()`` CM block the
   write stays in the transaction (same-connection SELECT sees it, rollback
   undoes it); the owner commits on clean exit.
2. Mid-transaction failure rollback — bank deposit, storage-ring retrieve,
   shop purchase and the overdue-loan kill path must roll back every write
   when the last write of the block raises.
3. Nesting guard — inside each repaired transaction block, the connection must
   still be in a transaction right after every helper call (machine-checked
   "nobody committed early").
4. Shop purchase success path — buying equipment/material items must persist
   both the item in the storage ring and the gold deduction (D5 stale-player
   overwrite regression), and pill purchases must credit the pill inventory.
5. bd 9jt — claim_interest and the overdue-loan kill loop, previously
   multi-write-without-transaction, now join the rollback/nesting contracts
   above (plus a repaid-after-snapshot guard so a closed loan never kills).
"""

import asyncio
import json
import sys
import time
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from tests.helpers import load_package_module, make_busy_state

# Load-order note: shop_handler uses package-attribute imports
# (``from ..core import ...`` / ``from ..data import ...``). Loading it FIRST lets
# the synthetic root package's ``__path__`` resolve the REAL core/data/models
# packages; pre-registering synthetic stubs for them (which load_package_module
# would do) shadows them with empty modules and breaks those imports.
_shop_mod = load_package_module(
    "handlers/shop_handler.py", "astrbot_plugin_monixiuxian2_2.handlers.shop_handler"
)
ShopHandler = _shop_mod.ShopHandler

_repo_mod = load_package_module(
    "data/pve_repository.py", "astrbot_plugin_monixiuxian2_2.data.pve_repository"
)
_data_pkg = sys.modules["astrbot_plugin_monixiuxian2_2.data"]
DataBase = _data_pkg.DataBase
MigrationManager = _data_pkg.MigrationManager
_core_pkg = sys.modules["astrbot_plugin_monixiuxian2_2.core"]
StorageRingManager = _core_pkg.StorageRingManager
PillManager = _core_pkg.PillManager
Player = sys.modules["astrbot_plugin_monixiuxian2_2.models"].Player
_check_loan_status = sys.modules[
    "astrbot_plugin_monixiuxian2_2.handlers.utils"
]._check_loan_status

_bank_mod = load_package_module(
    "managers/bank_manager.py", "astrbot_plugin_monixiuxian2_2.managers.bank_manager"
)
BankManager = _bank_mod.BankManager


class FakeConfigManager:
    """Minimal config stub for storage-ring/pill managers used in these tests."""

    def __init__(self):
        self.storage_rings_data = {
            "基础储物戒": {"type": "storage_ring", "capacity": 20, "rank": "凡品"}
        }
        self.pills_data = {"回气丹": {"name": "回气丹", "rank": "凡品"}}

    def is_pill(self, item_name: str) -> bool:
        return item_name in self.pills_data

    def get_pill_config(self, name: str) -> dict | None:
        # This fake only carries the breakthrough-pill table; the production
        # ConfigManager also checks exp/utility/items sources.
        return self.pills_data.get(name)

    def get_level_name(self, level_index: int, cultivation_type: str = "灵修") -> str:
        return f"境界{level_index}"


@pytest_asyncio.fixture
async def db(tmp_path):
    """Provide a migrated temp-file database and close it after the test."""
    database = DataBase(str(tmp_path / "test.db"))
    await database.connect()
    # Fresh-install path never touches config_manager; a mock is sufficient.
    await MigrationManager(database.conn, MagicMock()).migrate_or_reset()
    yield database
    await database.close()


async def _make_player(
    db: DataBase,
    user_id: str = "u1",
    gold: int = 10000,
    storage_items: dict | None = None,
) -> Player:
    player = Player(
        user_id=user_id, user_name=f"道友{user_id}", spiritual_root="天灵根", gold=gold
    )
    if storage_items is not None:
        player.set_storage_ring_items(storage_items)
    await db.create_player(player)
    return player


async def _fetchone(db: DataBase, sql: str, params: tuple = ()):
    """Run a SELECT on the shared connection and return the first row."""
    async with db.conn.execute(sql, params) as cursor:
        return await cursor.fetchone()


def _make_event(message: str, sender_id: str = "u1") -> MagicMock:
    """Build a minimal AstrMessageEvent stand-in for handler tests."""
    event = MagicMock()
    event.get_sender_id.return_value = sender_id
    event.get_message_str.return_value = message
    event.plain_result.side_effect = lambda text: text
    return event


def _make_shop_handler(db: DataBase) -> ShopHandler:
    """Assemble a ShopHandler with real db/ring/pill managers (only shop_manager mocked)."""
    handler = ShopHandler.__new__(ShopHandler)
    handler.db = db
    config_manager = FakeConfigManager()
    handler.config_manager = config_manager
    handler.shop_manager = MagicMock()
    handler.shop_manager.get_sect_shop_discount.return_value = 1.0
    handler.storage_ring_manager = StorageRingManager(db, config_manager)
    handler.pill_manager = PillManager(db, config_manager)
    # child A：尾部气血保底现在会经 health 域夹取；__new__ 绕过构造器需补默认属性
    handler.health_service = None
    return handler


def _spy_in_transaction(db: DataBase, monkeypatch, obj, name: str, states: list):
    """Wrap a helper so each call records (name, in_transaction, _txn_depth).

    No commit kwarg exists anymore (D2 gate is depth-based). Two signals are
    captured: in_transaction catches an early leaf commit, _txn_depth is the
    ownership signal proving the call ran inside a CM block (depth > 0) —
    bare DML keeps in_transaction True by itself, so depth is what proves
    the transaction was actually owned by the CM.
    """
    original = getattr(obj, name)

    async def spy(*args, **kwargs):
        await original(*args, **kwargs)
        states.append((name, db.conn.in_transaction, db.conn._txn_depth))

    monkeypatch.setattr(obj, name, spy)


# ===== 7.1 helper 守约测试：无 commit 参数（D2 深度门控）；CM 内不提交、abort 可回滚、干净退出提交；独立调用落盘 =====


@pytest.mark.asyncio
async def test_update_bank_account_commit_contract(db):
    # CM 内调用：不提前提交，abort 后回滚可撤销
    async with db.transaction() as txn:
        await db.ext.update_bank_account("u1", 500, 123)
        assert db.conn.in_transaction  # 未提前提交
        assert await db.ext.get_bank_account("u1") == {
            "balance": 500,
            "last_interest_time": 123,
        }
        txn.abort()
    assert await db.ext.get_bank_account("u1") is None  # 回滚可撤销

    # CM 干净退出 → 提交
    async with db.transaction():
        await db.ext.update_bank_account("u1", 500, 123)
    assert not db.conn.in_transaction
    assert (await db.ext.get_bank_account("u1"))["balance"] == 500

    # 独立调用（无 CM）：fail-open 提交，存量语义不变
    await db.ext.update_bank_account("u1", 700, 456)
    assert not db.conn.in_transaction
    assert (await db.ext.get_bank_account("u1"))["balance"] == 700


@pytest.mark.asyncio
async def test_create_loan_commit_contract(db):
    now = int(time.time())
    # CM 内：last_insert_rowid 是连接级状态，事务内查询仍能取到 id（design D2）
    async with db.transaction() as txn:
        loan_id = await db.ext.create_loan("u1", 1000, 0.005, now, now + 7 * 86400)
        assert loan_id > 0
        assert db.conn.in_transaction
        assert (await db.ext.get_active_loan("u1"))["principal"] == 1000
        txn.abort()
    assert await db.ext.get_active_loan("u1") is None

    async with db.transaction():
        loan_id = await db.ext.create_loan("u1", 1000, 0.005, now, now + 7 * 86400)
        assert loan_id > 0
    assert not db.conn.in_transaction
    assert (await db.ext.get_active_loan("u1"))["id"] == loan_id


@pytest.mark.asyncio
async def test_close_loan_commit_contract(db):
    now = int(time.time())
    loan_id = await db.ext.create_loan("u1", 1000, 0.005, now, now + 7 * 86400)

    async with db.transaction() as txn:
        await db.ext.close_loan(loan_id)
        assert db.conn.in_transaction
        row = await _fetchone(
            db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,)
        )
        assert row[0] == "closed"
        txn.abort()
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,))
    assert row[0] == "active"

    async with db.transaction():
        await db.ext.close_loan(loan_id)
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,))
    assert row[0] == "closed"


@pytest.mark.asyncio
async def test_mark_loan_overdue_commit_contract(db):
    now = int(time.time())
    loan_id = await db.ext.create_loan("u1", 1000, 0.005, now, now + 7 * 86400)

    async with db.transaction() as txn:
        await db.ext.mark_loan_overdue(loan_id)
        assert db.conn.in_transaction
        row = await _fetchone(
            db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,)
        )
        assert row[0] == "overdue"
        txn.abort()
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,))
    assert row[0] == "active"

    async with db.transaction():
        await db.ext.mark_loan_overdue(loan_id)
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,))
    assert row[0] == "overdue"


@pytest.mark.asyncio
async def test_add_bank_transaction_commit_contract(db):
    async with db.transaction() as txn:
        await db.ext.add_bank_transaction("u1", "deposit", 100, 600, "存入灵石", 1)
        assert db.conn.in_transaction
        txs = await db.ext.get_bank_transactions("u1")
        assert len(txs) == 1 and txs[0]["amount"] == 100
        txn.abort()
    assert await db.ext.get_bank_transactions("u1") == []

    async with db.transaction():
        await db.ext.add_bank_transaction("u1", "deposit", 100, 600, "存入灵石", 1)
    assert not db.conn.in_transaction
    assert len(await db.ext.get_bank_transactions("u1")) == 1


@pytest.mark.asyncio
async def test_delete_player_cascade_commit_contract(db):
    await _make_player(db)

    async with db.transaction() as txn:
        await db.delete_player_cascade("u1")
        assert db.conn.in_transaction
        assert (
            await _fetchone(db, "SELECT user_id FROM players WHERE user_id = 'u1'")
            is None
        )
        txn.abort()
    assert await db.get_player_by_id("u1") is not None  # 回滚可撤销

    async with db.transaction():
        await db.delete_player_cascade("u1")
    assert not db.conn.in_transaction
    assert await db.get_player_by_id("u1") is None

    await db.delete_player_cascade("u1")  # 独立调用：fail-open 提交，存量语义不变
    assert not db.conn.in_transaction
    assert await db.get_player_by_id("u1") is None


@pytest.mark.asyncio
async def test_bank_manager_add_transaction_commit_contract(db):
    mgr = BankManager(db)

    async with db.transaction() as txn:
        await mgr._add_transaction("u1", "deposit", 100, 600, "存入灵石")
        assert db.conn.in_transaction
        assert len(await db.ext.get_bank_transactions("u1")) == 1
        txn.abort()
    assert await db.ext.get_bank_transactions("u1") == []

    await mgr._add_transaction("u1", "deposit", 100, 600, "存入灵石")
    assert not db.conn.in_transaction
    assert len(await db.ext.get_bank_transactions("u1")) == 1


@pytest.mark.asyncio
async def test_add_pill_to_inventory_commit_contract(db):
    pill_mgr = PillManager(db, FakeConfigManager())
    await _make_player(db)

    player = await db.get_player_by_id("u1")
    async with db.transaction() as txn:
        await pill_mgr.add_pill_to_inventory(player, "回气丹", 2)
        assert db.conn.in_transaction
        row = await _fetchone(
            db, "SELECT pills_inventory FROM players WHERE user_id = 'u1'"
        )
        assert "回气丹" in row[0]
        txn.abort()
    assert (await db.get_player_by_id("u1")).get_pills_inventory() == {}

    player = await db.get_player_by_id("u1")  # 重取，避免沿用被 mutation 的旧对象
    await pill_mgr.add_pill_to_inventory(
        player, "回气丹", 2
    )  # 独立调用：fail-open 提交
    assert not db.conn.in_transaction
    assert (await db.get_player_by_id("u1")).get_pills_inventory() == {"回气丹": 2}


@pytest.mark.asyncio
async def test_apply_legacy_pill_effects_commit_contract(db):
    handler = _make_shop_handler(db)
    await _make_player(db)
    item = {
        "name": "小还丹",
        "type": "legacy_pill",
        "data": {"effect": {"add_experience": 100}},
    }

    player = await db.get_player_by_id("u1")
    async with db.transaction() as txn:
        ok, _ = await handler._apply_legacy_pill_effects(player, item, 1)
        assert ok
        assert db.conn.in_transaction
        row = await _fetchone(db, "SELECT experience FROM players WHERE user_id = 'u1'")
        assert row[0] == 100
        txn.abort()
    assert (await db.get_player_by_id("u1")).experience == 0

    player = await db.get_player_by_id("u1")  # 重取，避免沿用被 mutation 的旧对象
    ok, _ = await handler._apply_legacy_pill_effects(player, item, 1)  # 独立调用
    assert ok
    assert not db.conn.in_transaction
    assert (await db.get_player_by_id("u1")).experience == 100


# ===== 7.2 中途失败回滚测试：块内最后一个写操作注入异常，中间状态全部回滚 =====


@pytest.mark.asyncio
async def test_deposit_rolls_back_when_last_write_fails(db, monkeypatch):
    """存款块：_add_transaction 抛错时，灵石扣除与账户写入都必须回滚。"""
    mgr = BankManager(db)
    await _make_player(db, gold=1000)

    async def boom(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(mgr, "_add_transaction", boom)

    with pytest.raises(RuntimeError):
        await mgr.deposit(await db.get_player_by_id("u1"), 500)

    assert (await db.get_player_by_id("u1")).gold == 1000  # 灵石未扣
    assert await db.ext.get_bank_account("u1") is None  # 账户未落账
    assert await db.ext.get_bank_transactions("u1") == []  # 无流水残留


@pytest.mark.asyncio
async def test_retrieve_item_rolls_back_when_write_fails(db, monkeypatch):
    """储物戒取出块：update_player 执行后抛错，物品移除必须回滚。"""
    ring = StorageRingManager(db, FakeConfigManager())
    await _make_player(db, storage_items={"青铜剑": 2})

    original = db.update_player

    async def update_then_boom(player):
        await original(player)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(db, "update_player", update_then_boom)

    player = await db.get_player_by_id("u1")
    with pytest.raises(RuntimeError):
        await ring.retrieve_item(player, "青铜剑", 1)

    fresh = await db.get_player_by_id("u1")
    assert fresh.get_storage_ring_items() == {"青铜剑": 2}  # 物品未被移除


@pytest.mark.asyncio
async def test_shop_buy_rolls_back_when_pill_write_fails(db, monkeypatch):
    """商店购买块：pill 入账后抛错，库存扣减与背包写入都必须回滚。"""
    handler = _make_shop_handler(db)
    await _make_player(db, gold=10000)
    await db.update_shop_data(
        "pill_pavilion",
        int(time.time()),
        [{"name": "回气丹", "type": "pill", "price": 100, "stock": 5}],
    )

    original = handler.pill_manager.add_pill_to_inventory

    async def add_then_boom(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(handler.pill_manager, "add_pill_to_inventory", add_then_boom)

    event = _make_event("购买 回气丹")
    with pytest.raises(RuntimeError):
        _ = [item async for item in handler.handle_buy(event, "回气丹")]

    fresh = await db.get_player_by_id("u1")
    assert fresh.gold == 10000  # 灵石未扣
    assert fresh.get_pills_inventory() == {}  # 背包未入账
    _, items = await db.get_shop_data("pill_pavilion")
    assert items[0]["stock"] == 5  # 库存回滚


@pytest.mark.asyncio
async def test_check_loan_status_rolls_back_when_kill_fails(db, monkeypatch):
    """逾期追杀块：记流水抛错时，级联删除与逾期标记都必须回滚。

    Note: _check_loan_status 的外层 except 会吞掉异常并返回 None（既有语义），
    因此这里断言返回 None 而非 raises。
    """
    await _make_player(db)
    now = int(time.time())
    # 已逾期贷款（due_at 在过去）
    await db.ext.create_loan("u1", 1000, 0.005, now - 10 * 86400, now - 1)

    original = db.ext.add_bank_transaction

    async def add_then_boom(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(db.ext, "add_bank_transaction", add_then_boom)

    player = await db.get_player_by_id("u1")
    result = await _check_loan_status(db, player)
    assert result is None

    assert await db.get_player_by_id("u1") is not None  # 玩家未被删除
    loan = await db.ext.get_active_loan("u1")
    assert loan is not None and loan["status"] == "active"  # 贷款仍 active
    assert await db.ext.get_bank_transactions("u1") == []  # 无流水残留


# ===== 7.3 嵌套防护：块内每个 helper 调用后 conn.in_transaction 仍为 True =====


@pytest.mark.asyncio
async def test_bank_blocks_never_leave_transaction(db, monkeypatch):
    """deposit/withdraw/borrow/repay 四块：无 commit 参数，深度门控下均不提前提交。"""
    mgr = BankManager(db)
    await _make_player(db, gold=20000)

    states = []
    for obj, name in [
        (db, "update_player"),
        (db.ext, "update_bank_account"),
        (db.ext, "create_loan"),
        (db.ext, "close_loan"),
        (db.ext, "add_bank_transaction"),
    ]:
        _spy_in_transaction(db, monkeypatch, obj, name, states)

    ok, msg = await mgr.deposit(await db.get_player_by_id("u1"), 500)
    assert ok, msg
    ok, msg = await mgr.withdraw(await db.get_player_by_id("u1"), 200)
    assert ok, msg
    ok, msg = await mgr.borrow(await db.get_player_by_id("u1"), 5000)
    assert ok, msg
    ok, msg = await mgr.repay(await db.get_player_by_id("u1"))
    assert ok, msg

    # 四个块共触发 12 次 helper 写：全程在事务内且 CM 层 depth > 0（无提前提交、
    # 所有权确在 CM）；块结束后 depth 归零（仅 owner 层提交）
    assert len(states) == 12, states
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    assert db.conn._txn_depth == 0


@pytest.mark.asyncio
async def test_storage_ring_blocks_never_leave_transaction(db, monkeypatch):
    """store/retrieve/discard 三块：块内 update_player 均不提前提交。"""
    ring = StorageRingManager(db, FakeConfigManager())
    await _make_player(db, storage_items={"青铜剑": 2})

    states = []
    _spy_in_transaction(db, monkeypatch, db, "update_player", states)

    player = await db.get_player_by_id("u1")
    ok, msg = await ring.store_item(player, "玄铁", 1)
    assert ok, msg
    player = await db.get_player_by_id("u1")
    ok, msg = await ring.retrieve_item(player, "青铜剑", 1)
    assert ok, msg
    player = await db.get_player_by_id("u1")
    ok, msg = await ring.discard_item(player, "青铜剑", 1)
    assert ok, msg

    assert len(states) == 3, states
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    assert db.conn._txn_depth == 0


@pytest.mark.asyncio
async def test_shop_buy_block_never_leaves_transaction(db, monkeypatch):
    """商店购买块（装备路径）：store_item 与最终扣款两次 update_player 均不提前提交。"""
    handler = _make_shop_handler(db)
    await _make_player(db, gold=10000)
    await db.update_shop_data(
        "weapon_pavilion",
        int(time.time()),
        [{"name": "青铜剑", "type": "weapon", "price": 200, "stock": 3}],
    )

    states = []
    _spy_in_transaction(db, monkeypatch, db, "update_player", states)

    event = _make_event("购买 青铜剑")
    _ = [item async for item in handler.handle_buy(event, "青铜剑")]

    assert len(states) == 2, states  # store_item 一次 + 最终扣款一次
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    assert db.conn._txn_depth == 0


@pytest.mark.asyncio
async def test_check_loan_status_block_never_leaves_transaction(db, monkeypatch):
    """逾期追杀块：cascade/mark_overdue/add_bank_transaction 均不提前提交。"""
    await _make_player(db)
    now = int(time.time())
    await db.ext.create_loan("u1", 1000, 0.005, now - 10 * 86400, now - 1)

    states = []
    for obj, name in [
        (db, "delete_player_cascade"),
        (db.ext, "mark_loan_overdue"),
        (db.ext, "add_bank_transaction"),
    ]:
        _spy_in_transaction(db, monkeypatch, obj, name, states)

    player = await db.get_player_by_id("u1")
    result = await _check_loan_status(db, player)
    assert result is not None and result["is_dead"] is True

    assert [s[0] for s in states] == [
        "delete_player_cascade",
        "mark_loan_overdue",
        "add_bank_transaction",
    ]
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    assert db.conn._txn_depth == 0

    # 追杀成功路径语义不变：玩家删除、贷款 overdue、流水入账
    assert await db.get_player_by_id("u1") is None
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE user_id = 'u1'")
    assert row[0] == "overdue"
    txs = await db.ext.get_bank_transactions("u1")
    assert len(txs) == 1 and txs[0]["trans_type"] == "bank_kill"


# ===== 7.4 购买成功路径回归（D5）：物品写入与扣款落在同一 player 对象 =====


@pytest.mark.asyncio
async def test_buy_weapon_stores_item_and_deducts_gold(db):
    """购买武器：储物戒确有该物品且灵石正确扣除（修复前陈旧 player 覆盖必红）。"""
    handler = _make_shop_handler(db)
    await _make_player(db, gold=1000)
    await db.update_shop_data(
        "weapon_pavilion",
        int(time.time()),
        [{"name": "青铜剑", "type": "weapon", "price": 200, "stock": 3}],
    )

    event = _make_event("购买 青铜剑")
    outputs = [item async for item in handler.handle_buy(event, "青铜剑")]

    assert any("成功购买武器【青铜剑】x1" in str(o) for o in outputs)
    fresh = await db.get_player_by_id("u1")
    assert fresh.gold == 800  # 扣款未被覆盖
    assert fresh.get_storage_ring_items() == {"青铜剑": 1}  # 物品未被旧对象整行覆盖
    _, items = await db.get_shop_data("weapon_pavilion")
    assert items[0]["stock"] == 2


@pytest.mark.asyncio
async def test_buy_material_stores_item_and_deducts_gold(db):
    """购买材料：储物戒确有该物品且灵石正确扣除。"""
    handler = _make_shop_handler(db)
    await _make_player(db, gold=1000)
    await db.update_shop_data(
        "treasure_pavilion",
        int(time.time()),
        [{"name": "玄铁", "type": "material", "price": 50, "stock": 10}],
    )

    event = _make_event("购买 玄铁 2")
    outputs = [item async for item in handler.handle_buy(event, "玄铁 2")]

    assert any("成功购买材料【玄铁】x2" in str(o) for o in outputs)
    fresh = await db.get_player_by_id("u1")
    assert fresh.gold == 900
    assert fresh.get_storage_ring_items() == {"玄铁": 2}


@pytest.mark.asyncio
async def test_buy_pill_credits_inventory_and_deducts_gold(db):
    """购买丹药：背包正确入账且灵石正确扣除（防 D5 方案 B 引入 pill 回归）。"""
    handler = _make_shop_handler(db)
    await _make_player(db, gold=1000)
    await db.update_shop_data(
        "pill_pavilion",
        int(time.time()),
        [{"name": "回气丹", "type": "pill", "price": 100, "stock": 5}],
    )

    event = _make_event("购买 回气丹")
    outputs = [item async for item in handler.handle_buy(event, "回气丹")]

    assert any("成功购买【回气丹】x1" in str(o) for o in outputs)
    fresh = await db.get_player_by_id("u1")
    assert fresh.gold == 900
    assert fresh.get_pills_inventory() == {"回气丹": 1}


@pytest.mark.asyncio
async def test_store_item_standalone_still_refetches(db):
    """无外层 CM 的独立调用路径保持重取语义（D5 不改变的行为）。"""
    ring = StorageRingManager(db, FakeConfigManager())
    await _make_player(db, gold=100)

    # 调用方传入的是陈旧对象（储物戒为空），DB 里实际已有物品；
    # 独立路径必须基于重取的最新数据累加，而不是覆盖回旧值。
    stale_player = await db.get_player_by_id("u1")
    db_player = await db.get_player_by_id("u1")
    db_player.set_storage_ring_items({"青铜剑": 1})
    await db.update_player(db_player)

    ok, msg = await ring.store_item(stale_player, "玄铁", 1)
    assert ok, msg
    fresh = await db.get_player_by_id("u1")
    assert fresh.get_storage_ring_items() == {"青铜剑": 1, "玄铁": 1}


@pytest.mark.asyncio
async def test_store_item_foreign_cm_waits_then_merges_latest_player(db, monkeypatch):
    """Two tasks storing different items must not overwrite each other's ring.

    A owns a CM and pauses after storing 青铜剑. B then calls the real
    ``store_item`` with a snapshot taken before A's write. The old depth-only
    check treats A's foreign CM as B's own outer transaction, so B eventually
    writes its stale whole Player row and loses 青铜剑. The fixed path waits
    for A, rereads the player inside B's CM, and applies 玄铁 to that fresh row.
    """
    ring = StorageRingManager(db, FakeConfigManager())
    await _make_player(db)
    stale_b = await db.get_player_by_id("u1")
    player_a = await db.get_player_by_id("u1")
    a_stored = asyncio.Event()
    release_a = asyncio.Event()
    b_update_attempted = asyncio.Event()
    b_cm_attempted = asyncio.Event()
    b_task = None

    original_update = db.update_player
    original_transaction = db.transaction

    async def observed_update(player):
        if player is stale_b:
            b_update_attempted.set()
        await original_update(player)

    def observed_transaction():
        if b_task is not None and asyncio.current_task() is b_task:
            b_cm_attempted.set()
        return original_transaction()

    monkeypatch.setattr(db, "update_player", observed_update)
    monkeypatch.setattr(db, "transaction", observed_transaction)

    async def store_as_owner():
        async with db.transaction():
            ok, msg = await ring.store_item(player_a, "青铜剑")
            assert ok, msg
            a_stored.set()
            await release_a.wait()

    async def store_from_stale_snapshot():
        return await ring.store_item(stale_b, "玄铁")

    owner_task = asyncio.create_task(store_as_owner())
    await asyncio.wait_for(a_stored.wait(), timeout=2)
    assert db.conn.in_transaction
    assert (await db.get_player_by_id("u1")).get_storage_ring_items() == {"青铜剑": 1}

    b_task = asyncio.create_task(store_from_stale_snapshot())
    for _ in range(100):
        if b_update_attempted.is_set() or b_cm_attempted.is_set():
            break
        await asyncio.sleep(0)
    else:
        pytest.fail("B never reached its write/transaction boundary")

    assert b_cm_attempted.is_set()
    assert not b_update_attempted.is_set(), "B must wait before writing its stale row"
    assert db.conn._txn_owner_task is owner_task

    release_a.set()
    await asyncio.wait_for(asyncio.gather(owner_task, b_task), timeout=2)

    fresh = await db.get_player_by_id("u1")
    assert fresh.get_storage_ring_items() == {"青铜剑": 1, "玄铁": 1}
    assert not db.conn.in_transaction
    assert db.conn._txn_owner_task is None


@pytest.mark.asyncio
async def test_store_item_same_task_cm_join_does_not_reread_or_commit(db, monkeypatch):
    """A same-task CM caller keeps its Player object and owns final commit."""
    ring = StorageRingManager(db, FakeConfigManager())
    await _make_player(db)
    player = await db.get_player_by_id("u1")
    original_get = db.get_player_by_id

    async def unexpected_reread(user_id):
        raise AssertionError(f"same-task store unexpectedly reread {user_id}")

    monkeypatch.setattr(db, "get_player_by_id", unexpected_reread)
    async with db.transaction() as txn:
        ok, msg = await ring.store_item(player, "青铜剑")
        assert ok, msg
        assert db.conn.in_transaction
        assert db.conn._txn_depth == 1
        assert db.conn._txn_owner_task is asyncio.current_task()
        txn.abort()

    assert not db.conn.in_transaction
    # Aborting the outer CM proves the inner store did not commit early.
    monkeypatch.setattr(db, "get_player_by_id", original_get)
    fresh = await original_get("u1")
    assert fresh.get_storage_ring_items() == {}


# ===== 7.5 bd 9jt：claim_interest / check_and_process_overdue_loans 补事务后的守约测试 =====


@pytest_asyncio.fixture
async def bank_mgr(db):
    """BankManager on default config (daily rate 0.1%)."""
    return BankManager(db)


async def _seed_claimable_account(db: DataBase, user_id: str = "u1") -> int:
    """Create a player and an account whose last settlement was 1 day ago.

    Returns:
        The seeded balance (200_000), whose 1-day compound interest is 200.
    """
    await _make_player(db, user_id=user_id)
    now = int(time.time())
    await db.ext.update_bank_account(user_id, 200_000, now - 86400)
    return 200_000


@pytest.mark.asyncio
async def test_claim_interest_success_credits_and_records(db, bank_mgr):
    """Success path: interest compounds into balance and an interest row lands."""
    balance = await _seed_claimable_account(db)

    ok, msg = await bank_mgr.claim_interest(await db.get_player_by_id("u1"))
    assert ok, msg
    assert not db.conn.in_transaction

    account = await db.ext.get_bank_account("u1")
    assert account["balance"] == balance + 200
    assert account["last_interest_time"] > 0
    txs = await db.ext.get_bank_transactions("u1")
    assert len(txs) == 1
    assert txs[0]["trans_type"] == "interest" and txs[0]["amount"] == 200


@pytest.mark.asyncio
async def test_claim_interest_rolls_back_when_transaction_fails(
    db, bank_mgr, monkeypatch
):
    """claim_interest block: a failing transaction write must roll back the credit."""

    async def boom(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(bank_mgr, "_add_transaction", boom)
    await _seed_claimable_account(db)

    with pytest.raises(RuntimeError):
        await bank_mgr.claim_interest(await db.get_player_by_id("u1"))

    account = await db.ext.get_bank_account("u1")
    assert account["balance"] == 200_000  # 利息未入账
    assert await db.ext.get_bank_transactions("u1") == []  # 无流水残留


@pytest.mark.asyncio
async def test_claim_interest_block_never_leaves_transaction(db, bank_mgr, monkeypatch):
    """claim_interest: both writes stay inside the tx (depth gate, no early commit)."""
    await _seed_claimable_account(db)

    states = []
    for obj, name in [
        (db.ext, "update_bank_account"),
        (db.ext, "add_bank_transaction"),
    ]:
        _spy_in_transaction(db, monkeypatch, obj, name, states)

    ok, msg = await bank_mgr.claim_interest(await db.get_player_by_id("u1"))
    assert ok, msg

    assert [s[0] for s in states] == ["update_bank_account", "add_bank_transaction"]
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    assert db.conn._txn_depth == 0


async def _seed_overdue_loan(db: DataBase, user_id: str = "u1") -> None:
    """Create a player carrying a loan whose due_at is already past."""
    await _make_player(db, user_id=user_id)
    now = int(time.time())
    await db.ext.create_loan(user_id, 1000, 0.005, now - 10 * 86400, now - 1)


@pytest.mark.asyncio
async def test_overdue_loans_kill_success_is_atomic(db, bank_mgr):
    """Kill path: player deleted, loan overdue and bank_kill row land together."""
    await _seed_overdue_loan(db)

    processed = await bank_mgr.check_and_process_overdue_loans()
    assert not db.conn.in_transaction

    assert len(processed) == 1 and processed[0]["death"] is True
    assert await db.get_player_by_id("u1") is None
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE user_id = 'u1'")
    assert row[0] == "overdue"
    txs = await db.ext.get_bank_transactions("u1")
    assert len(txs) == 1 and txs[0]["trans_type"] == "bank_kill"


@pytest.mark.asyncio
async def test_overdue_loans_skips_repaid_loan(db, bank_mgr):
    """Snapshot staleness guard: a loan closed after the snapshot must not kill."""
    await _seed_overdue_loan(db)
    active = await db.ext.get_active_loan("u1")
    await db.ext.close_loan(active["id"])  # 模拟快照后、处理前已还款

    processed = await bank_mgr.check_and_process_overdue_loans()

    assert processed == []
    assert await db.get_player_by_id("u1") is not None  # 玩家未被误杀
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE user_id = 'u1'")
    assert row[0] == "closed"  # 还款状态不被追杀覆写
    assert await db.ext.get_bank_transactions("u1") == []


@pytest.mark.asyncio
async def test_overdue_loans_rolls_back_when_transaction_fails(
    db, bank_mgr, monkeypatch
):
    """Kill loop: a failing bank_kill write must resurrect the cascade delete."""

    original = db.ext.add_bank_transaction

    async def add_then_boom(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(db.ext, "add_bank_transaction", add_then_boom)
    await _seed_overdue_loan(db)

    with pytest.raises(RuntimeError):
        await bank_mgr.check_and_process_overdue_loans()

    assert await db.get_player_by_id("u1") is not None  # 级联删除已回滚
    loan = await db.ext.get_active_loan("u1")
    assert loan is not None and loan["status"] == "active"  # 逾期标记已回滚
    assert await db.ext.get_bank_transactions("u1") == []  # 流水已回滚


@pytest.mark.asyncio
async def test_overdue_loans_loop_block_never_leaves_transaction(
    db, bank_mgr, monkeypatch
):
    """Kill loop: cascade/mark_overdue/transaction stay inside one tx."""
    await _seed_overdue_loan(db)

    states = []
    for obj, name in [
        (db, "delete_player_cascade"),
        (db.ext, "mark_loan_overdue"),
        (db.ext, "add_bank_transaction"),
    ]:
        _spy_in_transaction(db, monkeypatch, obj, name, states)

    processed = await bank_mgr.check_and_process_overdue_loans()
    assert len(processed) == 1

    assert [s[0] for s in states] == [
        "delete_player_cascade",
        "mark_loan_overdue",
        "add_bank_transaction",
    ]
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    assert db.conn._txn_depth == 0


# ===== 8. bd 2w1：两段式提交收编（S1-S10，openspec fix-two-stage-commit-atomicity）=====
# Each spot below was two-stage (segment 1 committed before segment 2 was written):
# a failure between the two stages left a half-applied state (gold deducted without
# the farm, EXP paid without the collect timestamp, bounty cancelled without the
# cooldown...). All ten spots now run inside one unit-of-work CM, so the failure
# path is all-or-nothing and the D2 depth gate keeps every leaf from committing
# early. Assertions per spot:
#   (a) inject an exception in the SECOND stage -> the FIRST stage is rolled back;
#   (b) success path -> both stages persist, the CM leaves no open transaction;
#   (c) every leaf called inside the block reports ``_txn_depth > 0`` (ownership).

_farm_mod = load_package_module(
    "managers/spirit_farm_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.spirit_farm_manager",
)
SpiritFarmManager = _farm_mod.SpiritFarmManager
_eye_mod = load_package_module(
    "managers/spirit_eye_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.spirit_eye_manager",
)
SpiritEyeManager = _eye_mod.SpiritEyeManager
_land_mod = load_package_module(
    "managers/blessed_land_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.blessed_land_manager",
)
BlessedLandManager = _land_mod.BlessedLandManager
_dual_mod = load_package_module(
    "managers/dual_cultivation_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.dual_cultivation_manager",
)
DualCultivationManager = _dual_mod.DualCultivationManager

_cultivation_mod = load_package_module(
    "core/cultivation_manager.py",
    "astrbot_plugin_monixiuxian2_2.core.cultivation_manager",
)
_bounty_mod = load_package_module(
    "managers/bounty_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.bounty_manager",
)
BountyManager = _bounty_mod.BountyManager
GMManager = _core_pkg.GMManager


class _RaisingResult:
    """aiosqlite ``execute()`` stand-in that raises on both await and async-with."""

    def __init__(self, exc: BaseException):
        self._exc = exc

    async def __aenter__(self):
        raise self._exc

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __await__(self):
        async def _fail():
            raise self._exc

        return _fail().__await__()


def _boom_on_sql(db: DataBase, monkeypatch, marker: str):
    """Make any ``conn.execute()`` whose SQL contains ``marker`` raise RuntimeError.

    Used to fail the raw-SQL second stage of a converted spot (INSERT/UPDATE that
    has no leaf helper to monkeypatch), so the first stage's rollback is proven.
    """
    original = db.conn.execute

    def execute(sql, *args, **kwargs):
        if marker in sql:
            return _RaisingResult(RuntimeError("injected failure"))
        return original(sql, *args, **kwargs)

    monkeypatch.setattr(db.conn, "execute", execute)


def _assert_committed_and_idle(db: DataBase):
    """A finished CM block must leave no open transaction and zero depth."""
    assert db.conn.in_transaction is False
    assert db.conn._txn_depth == 0


def _make_dual_manager(db: DataBase) -> DualCultivationManager:
    """Build a DualCultivationManager with real db and dict-based config stubs."""
    config_manager = MagicMock()
    config_manager.game_config = {
        "dual_cultivation": {"k_hours": 2, "realm_factor": "linear"}
    }
    return DualCultivationManager(
        db,
        {"VALUES": {"BASE_EXP_PER_MINUTE": 100}},
        config_manager,
        cultivation_manager=_cultivation_mod.CultivationManager(
            {"VALUES": {"BASE_EXP_PER_MINUTE": 100}}, config_manager, None
        ),
        busy_state=make_busy_state(db),
    )


async def _seed_mature_farm(db: DataBase, user_id: str = "u1") -> None:
    """Insert a farm holding one mature (not withered) 灵草."""
    now = int(time.time())
    crops = json.dumps(
        [{"name": "灵草", "plant_time": now - 7200, "mature_time": now - 3600}]
    )
    await db.conn.execute(
        "INSERT INTO spirit_farms (user_id, level, crops) VALUES (?, 1, ?)",
        (user_id, crops),
    )
    await db.conn.commit()


async def _seed_spirit_eye(db: DataBase, user_id: str = "u1") -> None:
    """Insert a claimed spirit eye whose 2-hour collection window is due."""
    now = int(time.time())
    await db.conn.execute(
        "INSERT INTO spirit_eyes (eye_type, eye_name, exp_per_hour, spawn_time, "
        "owner_id, owner_name, claim_time, last_collect_time) "
        "VALUES (1, '下品灵眼', 500, ?, ?, ?, ?, ?)",
        (now - 7200, user_id, f"道友{user_id}", now - 7200, now - 7200),
    )
    await db.conn.commit()


async def _seed_blessed_land(
    db: DataBase, user_id: str = "u1", last_collect_time: int | None = None
) -> None:
    """Insert a Lv.1 小洞天 for the given user."""
    await db.conn.execute(
        "INSERT INTO blessed_lands (user_id, land_type, land_name, level, exp_bonus, "
        "gold_per_hour, last_collect_time) VALUES (?, 1, '小洞天', 1, 0.05, 100, ?)",
        (user_id, int(time.time()) if last_collect_time is None else last_collect_time),
    )
    await db.conn.commit()


async def _seed_dual_request(
    db: DataBase, from_id: str = "u1", target_id: str = "u2"
) -> None:
    """Insert one pending (non-expired) dual-cultivation request."""
    now = int(time.time())
    await db.conn.execute(
        "INSERT INTO dual_cultivation_requests (from_id, from_name, target_id, "
        "created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (from_id, f"道友{from_id}", target_id, now, now + 600),
    )
    await db.conn.commit()


async def _seed_active_bounty(db: DataBase, user_id: str = "u1") -> None:
    """Insert one in-progress bounty row.

    ``bounty_id`` is deliberately unknown to the template config: a template that
    is gone classifies as ``None`` and must not block the abandon path.
    """
    now = int(time.time())
    await db.conn.execute(
        "INSERT INTO bounty_tasks (user_id, bounty_id, bounty_name, target_type, "
        "target_count, rewards, start_time, expire_time, status) "
        "VALUES (?, 999999, '后山巡视', 'adventure', 3, '{}', ?, ?, 1)",
        (user_id, now - 10, now + 7200),
    )
    await db.conn.commit()


# -------- S1-S3: managers/spirit_farm_manager.py --------


@pytest.mark.asyncio
async def test_create_farm_rolls_back_when_farm_insert_fails(db, monkeypatch):
    """S1 create_farm: farm INSERT fails -> the 10,000-gold fee must roll back."""
    mgr = SpiritFarmManager(db, StorageRingManager(db, FakeConfigManager()))
    await _make_player(db, gold=10000)

    _boom_on_sql(db, monkeypatch, "INSERT INTO spirit_farms")

    with pytest.raises(RuntimeError):
        await mgr.create_farm(await db.get_player_by_id("u1"))

    assert (await db.get_player_by_id("u1")).gold == 10000  # 开垦费已回滚
    assert await mgr.get_user_farm("u1") is None  # 无半建成的灵田
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_create_farm_commits_fee_and_farm_together(db, monkeypatch):
    """S1 success path: both stages persist and the fee write stays gated."""
    mgr = SpiritFarmManager(db, StorageRingManager(db, FakeConfigManager()))
    await _make_player(db, gold=10000)

    states = []
    _spy_in_transaction(db, monkeypatch, db, "update_player", states)

    ok, msg = await mgr.create_farm(await db.get_player_by_id("u1"))

    assert ok and "灵田开垦成功" in msg
    assert (await db.get_player_by_id("u1")).gold == 0
    farm = await mgr.get_user_farm("u1")
    assert farm is not None and farm["level"] == 1
    assert [s[0] for s in states] == ["update_player"]
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_harvest_rolls_back_when_store_item_fails(db, monkeypatch):
    """S2 harvest: storage-ring write fails -> EXP/gold payout and crop reset roll back."""
    ring = StorageRingManager(db, FakeConfigManager())
    mgr = SpiritFarmManager(db, ring)
    await _make_player(db, gold=0)
    await _seed_mature_farm(db)

    async def boom(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(ring, "store_item", boom)

    with pytest.raises(RuntimeError):
        await mgr.harvest(await db.get_player_by_id("u1"))

    fresh = await db.get_player_by_id("u1")
    assert (fresh.experience, fresh.gold) == (0, 0)  # 发奖已回滚
    farm = await mgr.get_user_farm("u1")
    assert len(farm["crops"]) == 1  # 已收获的作物未被清空（可重试）
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_harvest_commits_payout_ring_and_crops_together(db, monkeypatch):
    """S2 success path: payout, ring deposit and crop reset commit as one unit."""
    ring = StorageRingManager(db, FakeConfigManager())
    mgr = SpiritFarmManager(db, ring)
    await _make_player(db, gold=0)
    await _seed_mature_farm(db)

    states = []
    _spy_in_transaction(db, monkeypatch, db, "update_player", states)
    # store_item is spied locally (not via the shared helper) because harvest
    # unpacks its return value — the local spy must forward it.
    original_store = ring.store_item

    async def spy_store(*args, **kwargs):
        result = await original_store(*args, **kwargs)
        states.append(("store_item", db.conn.in_transaction, db.conn._txn_depth))
        return result

    monkeypatch.setattr(ring, "store_item", spy_store)

    ok, msg = await mgr.harvest(await db.get_player_by_id("u1"))

    assert ok and "收获结果" in msg and "储物戒已满" not in msg
    fresh = await db.get_player_by_id("u1")
    assert (fresh.experience, fresh.gold) == (500, 100)  # 灵草收益
    assert fresh.get_storage_ring_items() == {"灵草": 1}
    assert (await mgr.get_user_farm("u1"))["crops"] == []
    # update_player 出现在 store_item 之前两次：一次是发奖，一次是 store_item
    # 内部持久化储物戒（储物戒与玩家同连接）
    assert states[0][0] == "update_player" and states[-1][0] == "store_item"
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_upgrade_farm_rolls_back_when_level_update_fails(db, monkeypatch):
    """S3 upgrade_farm: level UPDATE fails -> the 5,000-gold fee must roll back."""
    mgr = SpiritFarmManager(db, StorageRingManager(db, FakeConfigManager()))
    await _make_player(db, gold=5000)
    await db.conn.execute(
        "INSERT INTO spirit_farms (user_id, level, crops) VALUES ('u1', 1, '[]')"
    )
    await db.conn.commit()

    _boom_on_sql(db, monkeypatch, "UPDATE spirit_farms SET level")

    with pytest.raises(RuntimeError):
        await mgr.upgrade_farm(await db.get_player_by_id("u1"))

    assert (await db.get_player_by_id("u1")).gold == 5000  # 升级费已回滚
    assert (await mgr.get_user_farm("u1"))["level"] == 1
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_upgrade_farm_commits_fee_and_level_together(db, monkeypatch):
    """S3 success path: fee and new level persist in one transaction."""
    mgr = SpiritFarmManager(db, StorageRingManager(db, FakeConfigManager()))
    await _make_player(db, gold=10000)
    await db.conn.execute(
        "INSERT INTO spirit_farms (user_id, level, crops) VALUES ('u1', 1, '[]')"
    )
    await db.conn.commit()

    states = []
    _spy_in_transaction(db, monkeypatch, db, "update_player", states)

    ok, msg = await mgr.upgrade_farm(await db.get_player_by_id("u1"))

    assert ok and "灵田升级到 Lv.2" in msg
    assert (await db.get_player_by_id("u1")).gold == 5000
    assert (await mgr.get_user_farm("u1"))["level"] == 2
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    _assert_committed_and_idle(db)


# -------- S4: managers/spirit_eye_manager.py --------


@pytest.mark.asyncio
async def test_collect_spirit_eye_rolls_back_when_timestamp_update_fails(
    db, monkeypatch
):
    """S4 collect_spirit_eye: timestamp UPDATE fails -> the EXP payout must roll back."""
    mgr = SpiritEyeManager(db)
    await _make_player(db, gold=0)
    await _seed_spirit_eye(db)
    before = await _fetchone(
        db, "SELECT last_collect_time FROM spirit_eyes WHERE owner_id = 'u1'"
    )

    _boom_on_sql(db, monkeypatch, "UPDATE spirit_eyes SET last_collect_time")

    with pytest.raises(RuntimeError):
        await mgr.collect_spirit_eye(await db.get_player_by_id("u1"))

    assert (await db.get_player_by_id("u1")).experience == 0  # 修为已回滚
    after = await _fetchone(
        db, "SELECT last_collect_time FROM spirit_eyes WHERE owner_id = 'u1'"
    )
    assert after[0] == before[0]  # 领取时间戳未推进（不会重复领取）
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_collect_spirit_eye_commits_exp_and_timestamp_together(db, monkeypatch):
    """S4 success path: 2-hour payout and its timestamp commit as one unit."""
    mgr = SpiritEyeManager(db)
    await _make_player(db, gold=0)
    await _seed_spirit_eye(db)
    before = await _fetchone(
        db, "SELECT last_collect_time FROM spirit_eyes WHERE owner_id = 'u1'"
    )

    states = []
    _spy_in_transaction(db, monkeypatch, db, "update_player", states)

    ok, msg = await mgr.collect_spirit_eye(await db.get_player_by_id("u1"))

    assert ok and "灵眼收取成功" in msg
    assert (await db.get_player_by_id("u1")).experience == 1000  # 500/h × 2h
    after = await _fetchone(
        db, "SELECT last_collect_time FROM spirit_eyes WHERE owner_id = 'u1'"
    )
    assert after[0] > before[0]
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    _assert_committed_and_idle(db)


# -------- S5-S7: managers/blessed_land_manager.py --------


@pytest.mark.asyncio
async def test_purchase_blessed_land_rolls_back_when_insert_fails(db, monkeypatch):
    """S5 purchase_blessed_land: INSERT fails -> the land price must roll back."""
    mgr = BlessedLandManager(db)
    await _make_player(db, gold=10000)

    _boom_on_sql(db, monkeypatch, "INSERT INTO blessed_lands")

    with pytest.raises(RuntimeError):
        await mgr.purchase_blessed_land(await db.get_player_by_id("u1"), 1)

    assert (await db.get_player_by_id("u1")).gold == 10000  # 购买费已回滚
    assert await mgr.get_user_blessed_land("u1") is None
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_purchase_blessed_land_commits_price_and_land_together(db, monkeypatch):
    """S5 success path: price deduction and land row persist as one unit."""
    mgr = BlessedLandManager(db)
    await _make_player(db, gold=10000)

    states = []
    _spy_in_transaction(db, monkeypatch, db, "update_player", states)

    ok, msg = await mgr.purchase_blessed_land(await db.get_player_by_id("u1"), 1)

    assert ok and "恭喜获得【小洞天】" in msg
    assert (await db.get_player_by_id("u1")).gold == 0
    land = await mgr.get_user_blessed_land("u1")
    assert land is not None and land["level"] == 1
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_upgrade_blessed_land_rolls_back_when_update_fails(db, monkeypatch):
    """S6 upgrade_blessed_land: UPDATE fails -> the upgrade cost must roll back."""
    mgr = BlessedLandManager(db)
    await _make_player(db, gold=5000)
    await _seed_blessed_land(db)

    _boom_on_sql(db, monkeypatch, "UPDATE blessed_lands SET level")

    with pytest.raises(RuntimeError):
        await mgr.upgrade_blessed_land(await db.get_player_by_id("u1"))

    assert (await db.get_player_by_id("u1")).gold == 5000  # 升级费用已回滚
    assert (await mgr.get_user_blessed_land("u1"))["level"] == 1
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_upgrade_blessed_land_commits_cost_and_level_together(db, monkeypatch):
    """S6 success path: cost and land upgrade persist in one transaction."""
    mgr = BlessedLandManager(db)
    await _make_player(db, gold=5000)
    await _seed_blessed_land(db)

    states = []
    _spy_in_transaction(db, monkeypatch, db, "update_player", states)

    ok, msg = await mgr.upgrade_blessed_land(await db.get_player_by_id("u1"))

    assert ok and "升级到 Lv.2" in msg
    assert (await db.get_player_by_id("u1")).gold == 0
    assert (await mgr.get_user_blessed_land("u1"))["level"] == 2
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_collect_income_rolls_back_when_timestamp_update_fails(db, monkeypatch):
    """S7 collect_income: timestamp UPDATE fails -> the income payout must roll back."""
    mgr = BlessedLandManager(db)
    await _make_player(db, gold=1234)
    await _seed_blessed_land(db, last_collect_time=int(time.time()) - 7200)
    before = await _fetchone(
        db, "SELECT last_collect_time FROM blessed_lands WHERE user_id = 'u1'"
    )

    _boom_on_sql(db, monkeypatch, "UPDATE blessed_lands SET last_collect_time")

    with pytest.raises(RuntimeError):
        await mgr.collect_income(await db.get_player_by_id("u1"))

    assert (await db.get_player_by_id("u1")).gold == 1234  # 产出已回滚
    after = await _fetchone(
        db, "SELECT last_collect_time FROM blessed_lands WHERE user_id = 'u1'"
    )
    assert after[0] == before[0]  # 领取时间戳未推进（不会重复领取）
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_collect_income_commits_payout_and_timestamp_together(db, monkeypatch):
    """S7 success path: 2-hour income and its timestamp commit as one unit."""
    mgr = BlessedLandManager(db)
    await _make_player(db, gold=1234)
    await _seed_blessed_land(db, last_collect_time=int(time.time()) - 7200)
    before = await _fetchone(
        db, "SELECT last_collect_time FROM blessed_lands WHERE user_id = 'u1'"
    )

    states = []
    _spy_in_transaction(db, monkeypatch, db, "update_player", states)

    ok, msg = await mgr.collect_income(await db.get_player_by_id("u1"))

    assert ok and "洞天收取成功" in msg
    assert (await db.get_player_by_id("u1")).gold == 1434  # 100/h × 2h
    after = await _fetchone(
        db, "SELECT last_collect_time FROM blessed_lands WHERE user_id = 'u1'"
    )
    assert after[0] > before[0]
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    _assert_committed_and_idle(db)


# -------- S8: managers/dual_cultivation_manager.py --------


@pytest.mark.asyncio
async def test_accept_request_rolls_back_when_request_delete_fails(db, monkeypatch):
    """S8 accept_request: last write fails -> EXP, cooldowns and the request all roll back."""
    mgr = _make_dual_manager(db)
    await _make_player(db, gold=0)
    await _make_player(db, user_id="u2", gold=0)
    await _seed_dual_request(db)

    async def boom(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(mgr, "_delete_request", boom)

    with pytest.raises(RuntimeError):
        await mgr.accept_request(await db.get_player_by_id("u2"))

    for uid in ("u1", "u2"):
        assert (await db.get_player_by_id(uid)).experience == 0  # 修为未结算
        assert await mgr._get_last_dual_time(uid) is None  # 冷却未记录
    # 请求保留，玩家可重试（不会出现「修为已加但请求仍在」的重复结算）
    assert (await mgr._get_pending_request("u2"))["from_id"] == "u1"
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_accept_request_commits_all_five_writes(db, monkeypatch):
    """S8 success path: 2 EXP + 2 cooldown + 1 request delete commit as one unit."""
    mgr = _make_dual_manager(db)
    await _make_player(db, gold=0)
    await _make_player(db, user_id="u2", gold=0)
    await _seed_dual_request(db)
    expected_gain = mgr._calculate_exp_gain(await db.get_player_by_id("u1"))

    states = []
    for obj, name in [
        (db, "update_player"),
        (mgr, "_set_last_dual_time"),
        (mgr, "_delete_request"),
    ]:
        _spy_in_transaction(db, monkeypatch, obj, name, states)

    ok, msg = await mgr.accept_request(await db.get_player_by_id("u2"))

    assert ok and "双修成功" in msg
    for uid in ("u1", "u2"):
        assert (await db.get_player_by_id(uid)).experience == expected_gain
        assert await mgr._get_last_dual_time(uid) is not None
    assert await mgr._get_pending_request("u2") is None  # 请求已清除
    assert [s[0] for s in states] == [
        "update_player",
        "update_player",
        "_set_last_dual_time",
        "_set_last_dual_time",
        "_delete_request",
    ]
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    _assert_committed_and_idle(db)


# -------- S9: core/gm_manager.py cmd_clear_all_cooldowns --------


async def _seed_clear_all_cooldowns_state(db: DataBase, user_id: str = "u1") -> int:
    """Seed one row per cleared domain; returns the seeded duel timestamp."""
    now = int(time.time())
    await _make_player(db, gold=0)
    await db.ext.set_user_busy(user_id, 1, now + 3600)
    await db.conn.execute(
        "UPDATE players SET state = '修炼中' WHERE user_id = ?", (user_id,)
    )
    await db.conn.execute(
        "INSERT INTO combat_cooldowns (user_id, last_duel_time, last_spar_time) "
        "VALUES (?, ?, ?)",
        (user_id, now - 100, now - 50),
    )
    await db.conn.execute(
        "INSERT INTO dual_cultivation (user_id, last_dual_time) VALUES (?, ?)",
        (user_id, now - 200),
    )
    await _seed_active_bounty(db, user_id)
    await db.conn.execute(
        "INSERT INTO adventure_fatigue (user_id, route_id, fatigue_until) "
        "VALUES (?, 'route_a', ?)",
        (user_id, now + 300),
    )
    # 末笔走叶子 helper：standalone 时自带提交，不给后续 BEGIN 留隐式事务
    await db.ext.set_system_config(f"bounty_abandon_cd_{user_id}", str(now + 1800))
    return now - 100


class _FatigueClearer:
    """Stand-in for AdventureManager clearing the persisted 休整 row.

    GM 只用到 ``clear_fatigue``，这里保留真实语义：走仓储 CAS 清理且**不自行提交**
    （叶子按 ``_txn_depth`` 门控），所以休整行的消失与调用方事务同生死。
    """

    def __init__(self, db):
        self._db = db
        self.calls: list[str] = []

    async def clear_fatigue(self, user_id: str) -> bool:
        self.calls.append(user_id)
        repo = _repo_mod.AdventureRepository(self._db.conn)
        row = await repo.get_fatigue(user_id)
        if not row:
            return False
        return await repo.cas_clear_fatigue(
            user_id, expected_cas_version=int(row["cas_version"])
        )


@pytest.mark.asyncio
async def test_clear_all_cooldowns_rolls_back_and_keeps_fatigue(db, monkeypatch):
    """S9: step-3 failure -> earlier steps roll back AND the fatigue row stays."""
    uid = "u1"
    duel_before = await _seed_clear_all_cooldowns_state(db, uid)
    adventure = _FatigueClearer(db)
    gm = GMManager(
        db=db,
        config_manager=MagicMock(),
        storage_ring_manager=MagicMock(),
        equipment_manager=MagicMock(),
        adventure_manager=adventure,
        busy_state=make_busy_state(db),
    )
    event = _make_event(f"{uid} 确认")
    event.message_obj = None

    # marker 必须取到 "= 0"：与 GM 时间快进注册表（core/time_skip_registry.py
    # 双修条目，"... last_dual_time - ?"）只差运算符，前缀重名会误伤/漏检
    _boom_on_sql(db, monkeypatch, "UPDATE dual_cultivation SET last_dual_time = 0")

    with pytest.raises(RuntimeError):
        await gm.cmd_clear_all_cooldowns(event, f"{uid} 确认")

    # 步骤 1-2 已回滚（忙碌状态与决斗冷却保持原值）
    assert (await db.get_player_by_id(uid)).state == "修炼中"
    row = await _fetchone(
        db, "SELECT last_duel_time FROM combat_cooldowns WHERE user_id = ?", (uid,)
    )
    assert row[0] == duel_before
    # 步骤 1 的 user_cd 行同样回滚：只断言 player.state 时，这一层的门控回退不会变红
    row = await _fetchone(db, "SELECT type FROM user_cd WHERE user_id = ?", (uid,))
    assert (
        row[0] == 1
    )  # 仍为忙碌（_seed_clear_all_cooldowns_state 的 set_user_busy 种子值）
    # 步骤 3 抛错，休整清理根本没跑；就算跑了也在同一事务里，回滚照样保留
    assert adventure.calls == []
    row = await _fetchone(
        db, "SELECT fatigue_until FROM adventure_fatigue WHERE user_id = ?", (uid,)
    )
    assert row[0] > 0  # 休整窗口原样保留
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_clear_all_cooldowns_clears_fatigue_in_same_transaction(db, monkeypatch):
    """S9 success path: all domains cleared, 休整 window cleared inside the CM."""
    uid = "u1"
    await _seed_clear_all_cooldowns_state(db, uid)
    adventure = _FatigueClearer(db)
    gm = GMManager(
        db=db,
        config_manager=MagicMock(),
        storage_ring_manager=MagicMock(),
        equipment_manager=MagicMock(),
        adventure_manager=adventure,
        busy_state=make_busy_state(db),
    )
    event = _make_event(f"{uid} 确认")
    event.message_obj = None

    states = []
    for obj, name in [
        (db.ext, "set_user_free"),
        (db.ext, "cancel_bounty"),
        (db.ext, "set_system_config"),
    ]:
        _spy_in_transaction(db, monkeypatch, obj, name, states)

    ok, msg = await gm.cmd_clear_all_cooldowns(event, f"{uid} 确认")

    assert ok and "已清除【道友u1】的全部冷却状态" in msg
    assert "忙碌状态：1 条" in msg
    assert "决斗/切磋冷却：1 条" in msg
    assert "双修冷却：1 条" in msg
    assert "进行中悬赏：1 条（后山巡视）" in msg
    assert "悬赏放弃冷却：1 条" in msg
    assert "历练休整冷却：1 条" in msg

    assert (await db.get_player_by_id(uid)).state == "空闲"
    assert (await db.ext.get_user_cd(uid)).type == 0
    row = await _fetchone(
        db,
        "SELECT last_duel_time, last_spar_time FROM combat_cooldowns WHERE user_id = ?",
        (uid,),
    )
    assert (row[0], row[1]) == (0, 0)
    dual = await _fetchone(
        db, "SELECT last_dual_time FROM dual_cultivation WHERE user_id = ?", (uid,)
    )
    assert dual[0] == 0
    assert await db.ext.get_active_bounty(uid) is None
    assert await db.ext.get_system_config(f"bounty_abandon_cd_{uid}") == "0"
    assert adventure.calls == [uid]
    row = await _fetchone(
        db, "SELECT fatigue_until FROM adventure_fatigue WHERE user_id = ?", (uid,)
    )
    assert row[0] == 0  # 清理与其余域同事务提交
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    _assert_committed_and_idle(db)


# -------- S10: managers/bounty_manager.py abandon_bounty --------


@pytest.mark.asyncio
async def test_abandon_bounty_rolls_back_when_cooldown_write_fails(db, monkeypatch):
    """S10 abandon_bounty: cooldown write fails -> the bounty must stay in progress."""
    uid = "u1"
    mgr = BountyManager(db)
    await _make_player(db, gold=0)
    await _seed_active_bounty(db, uid)

    async def boom(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(db.ext, "set_system_config", boom)

    with pytest.raises(RuntimeError):
        await mgr.abandon_bounty(await db.get_player_by_id(uid))

    assert await db.ext.get_active_bounty(uid) is not None  # 悬赏未被取消
    assert await db.ext.get_system_config(f"bounty_abandon_cd_{uid}") is None
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_abandon_bounty_commits_cancel_and_cooldown_together(db, monkeypatch):
    """S10 success path: cancel + 30-minute cooldown commit as one unit (message carries its own ✅)."""
    uid = "u1"
    mgr = BountyManager(db)
    await _make_player(db, gold=0)
    await _seed_active_bounty(db, uid)

    states = []
    _spy_in_transaction(db, monkeypatch, db.ext, "cancel_bounty", states)
    _spy_in_transaction(db, monkeypatch, db.ext, "set_system_config", states)

    ok, msg = await mgr.abandon_bounty(await db.get_player_by_id(uid))

    assert ok
    assert msg == "✅ 已放弃悬赏：后山巡视\n⚠️ 30分钟内无法接取新悬赏"
    assert await db.ext.get_active_bounty(uid) is None  # status=0
    cooldown = await db.ext.get_system_config(f"bounty_abandon_cd_{uid}")
    assert cooldown is not None and int(cooldown) > time.time()
    assert [s[0] for s in states] == ["cancel_bounty", "set_system_config"]
    assert all(in_tx and depth > 0 for _, in_tx, depth in states), states
    _assert_committed_and_idle(db)


# -------- 8.6 门控回归：CM 外独立调用仍提交（fail-open 语义不变）--------


@pytest.mark.asyncio
async def test_dual_cultivation_leaf_gates_commit_when_standalone(db):
    """S8 leaves keep their standalone-commit semantics outside any CM block."""
    mgr = _make_dual_manager(db)

    await mgr._set_last_dual_time("u9", 111)
    assert db.conn.in_transaction is False  # 门控提交已生效
    assert await mgr._get_last_dual_time("u9") == 111

    # _get_pending_request 会先清理过期请求，独立调用时必须自行提交
    await _seed_dual_request(db, from_id="u8", target_id="u9")
    request = await mgr._get_pending_request("u9")
    assert request is not None and db.conn.in_transaction is False

    await mgr._delete_request(request["id"])
    assert db.conn.in_transaction is False
    remaining = await _fetchone(
        db, "SELECT COUNT(*) FROM dual_cultivation_requests WHERE target_id = 'u9'"
    )
    assert remaining[0] == 0
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_ext_leaf_gates_commit_when_standalone(db):
    """S9/S10 leaves (cancel_bounty / set_system_config) commit when called outside a CM."""
    await _make_player(db, gold=0)
    await _seed_active_bounty(db, "u1")

    await db.ext.cancel_bounty("u1")
    assert db.conn.in_transaction is False
    assert await db.ext.get_active_bounty("u1") is None

    await db.ext.set_system_config("bounty_abandon_cd_u1", "123")
    assert db.conn.in_transaction is False
    assert await db.ext.get_system_config("bounty_abandon_cd_u1") == "123"
    _assert_committed_and_idle(db)


# -------- bd 3ar: S9 同族残留（GM 清除悬赏 / 清除传承状态 / 弃道重修）--------
# 三处都是「两段写各自提交、无 CM」（bd astrbot_plugin_monixiuxian2_2-3ar，S9 扫描
# 口径外的新发现），中途失败留下半提交状态：悬赏已取消 / 挑战冷却已清 / 角色已删
# 而 7 天冷却键未写。修复形态与 S1-S10 相同——包一个 CM，失败即整段回滚，异常向上
# 传播（不得静默成功）。每例注入第二段（或第三段）失败，用真实 DB 查询断言第一段
# 的写入已回滚，并断言第一段叶子观察到 ``_txn_depth > 0``（CM 确实生效）。

_player_mod = load_package_module(
    "handlers/player_handler.py",
    "astrbot_plugin_monixiuxian2_2.handlers.player_handler",
)
PlayerHandler = _player_mod.PlayerHandler
_sect_mod = load_package_module(
    "managers/sect_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.sect_manager",
)
SectManager = _sect_mod.SectManager


class _SectFakeConfig(FakeConfigManager):
    """FakeConfigManager + one sect treasure, so 弃道重修 的第一段真的落库。

    ``SectManager._find_item_config`` 查的是 weapons_data/items_data 等表；
    基类 FakeConfigManager 没有这些表（getattr 落到 None），回收会空手而回，
    第一段的回滚断言就成了空断言。
    """

    def __init__(self):
        super().__init__()
        self.weapons_data = {
            "青云镇山剑": {"id": "wpn_qy_001", "sect_id": "qingyun", "treasure": True}
        }
        self.items_data = {}
        self.heart_methods_data = {}


def _make_gm(db: DataBase) -> GMManager:
    """Assemble a GMManager with a real db and mocked collaborators."""
    return GMManager(
        db=db,
        config_manager=MagicMock(),
        storage_ring_manager=MagicMock(),
        equipment_manager=MagicMock(),
        adventure_manager=MagicMock(),
        impart_manager=MagicMock(),
        busy_state=make_busy_state(db),
    )


async def _raise_on_leaf(monkeypatch, obj, name: str) -> None:
    """Make one leaf helper raise, so the caller's CM must roll stage 1 back.

    Patches the bound helper on the shared ``db``/``db.ext`` instance, which is
    the object the code under test resolves the leaf through.
    """

    async def boom(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(obj, name, boom)


@pytest.mark.asyncio
async def test_clear_bounty_rolls_back_cancel_when_cooldown_write_fails(
    db, monkeypatch
):
    """bd 3ar GM 清除悬赏: stage-2 failure -> the cancelled bounty comes back."""
    uid = "u1"
    await _make_player(db, gold=0)
    await _seed_active_bounty(db, uid)
    cd_key = f"bounty_abandon_cd_{uid}"
    cd_before = str(int(time.time()) + 1800)
    await db.ext.set_system_config(cd_key, cd_before)
    gm = _make_gm(db)
    event = _make_event(f"{uid} 确认")
    event.message_obj = None

    states: list = []
    _spy_in_transaction(db, monkeypatch, db.ext, "cancel_bounty", states)
    await _raise_on_leaf(monkeypatch, db.ext, "set_system_config")

    with pytest.raises(RuntimeError):
        await gm.cmd_clear_bounty(event, f"{uid} 确认")

    # 第一段（取消悬赏）已回滚：悬赏仍在进行中、冷却键保持原值（无残留写）
    assert await db.ext.get_active_bounty(uid) is not None
    assert await db.ext.get_system_config(cd_key) == cd_before
    # CM 生效：第一段叶子在事务内执行（包 CM 前 depth 恒为 0，即提前提交）
    assert states == [("cancel_bounty", True, 1)]
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_clear_bounty_commits_cancel_and_cooldown_together(db, monkeypatch):
    """bd 3ar GM 清除悬赏 success path: both stages persist, message unchanged."""
    uid = "u1"
    await _make_player(db, gold=0)
    await _seed_active_bounty(db, uid)
    cd_key = f"bounty_abandon_cd_{uid}"
    await db.ext.set_system_config(cd_key, str(int(time.time()) + 1800))
    gm = _make_gm(db)
    event = _make_event(f"{uid} 确认")
    event.message_obj = None

    ok, msg = await gm.cmd_clear_bounty(event, f"{uid} 确认")

    assert ok
    assert msg == "✅ 已清除【道友u1】的进行中悬赏【后山巡视】、放弃冷却"
    assert await db.ext.get_active_bounty(uid) is None
    assert await db.ext.get_system_config(cd_key) == "0"
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_clear_legacy_state_rolls_back_cooldowns_when_protection_fails(
    db, monkeypatch
):
    """bd 3ar GM 清除传承状态: stage-2 failure -> deleted cooldowns come back."""
    uid = "u1"
    now = int(time.time())
    await _make_player(db, gold=0)
    await db.conn.execute(
        "INSERT INTO impart_pk_cooldown (challenger_id, target_id, failed_at) "
        "VALUES (?, ?, ?)",
        (uid, "u2", now - 10),
    )
    await db.conn.execute(
        "INSERT INTO impart_snatch_protection (user_id, snatched_at) VALUES (?, ?)",
        (uid, now - 10),
    )
    await db.conn.commit()
    gm = _make_gm(db)
    event = _make_event(f"{uid} 确认")
    event.message_obj = None

    states: list = []
    _spy_in_transaction(db, monkeypatch, db.ext, "delete_impart_pk_cooldowns", states)
    await _raise_on_leaf(monkeypatch, db.ext, "delete_impart_snatch_protection")

    with pytest.raises(RuntimeError):
        await gm.cmd_clear_legacy_state(event, f"{uid} 确认")

    # 第一段（挑战冷却删除）已回滚：DELE 未落盘，冷却行仍在
    row = await _fetchone(
        db, "SELECT COUNT(*) FROM impart_pk_cooldown WHERE challenger_id = ?", (uid,)
    )
    assert row[0] == 1
    row = await _fetchone(
        db, "SELECT COUNT(*) FROM impart_snatch_protection WHERE user_id = ?", (uid,)
    )
    assert row[0] == 1  # 第二段自身也未曾生效
    # CM 生效：第一段叶子在事务内执行
    assert states == [("delete_impart_pk_cooldowns", True, 1)]
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_clear_legacy_state_commits_both_deletes(db, monkeypatch):
    """bd 3ar GM 清除传承状态 success path: both deletes persist, message unchanged."""
    uid = "u1"
    now = int(time.time())
    await _make_player(db, gold=0)
    await db.conn.execute(
        "INSERT INTO impart_pk_cooldown (challenger_id, target_id, failed_at) "
        "VALUES (?, ?, ?)",
        (uid, "u2", now - 10),
    )
    await db.conn.execute(
        "INSERT INTO impart_snatch_protection (user_id, snatched_at) VALUES (?, ?)",
        (uid, now - 10),
    )
    await db.conn.commit()
    gm = _make_gm(db)
    event = _make_event(f"{uid} 确认")
    event.message_obj = None

    ok, msg = await gm.cmd_clear_legacy_state(event, f"{uid} 确认")

    assert ok
    assert msg == "✅ 已清除 道友u1 的传承状态：挑战冷却 1 条、保护期 1 条"
    row = await _fetchone(
        db, "SELECT COUNT(*) FROM impart_pk_cooldown WHERE challenger_id = ?", (uid,)
    )
    assert row[0] == 0
    row = await _fetchone(
        db, "SELECT COUNT(*) FROM impart_snatch_protection WHERE user_id = ?", (uid,)
    )
    assert row[0] == 0
    _assert_committed_and_idle(db)


async def _seed_sect_treasure_state(db: DataBase, user_id: str = "u1") -> None:
    """Put the player in a sect holding one sect treasure (青云镇山剑)."""
    await db.conn.execute(
        "INSERT INTO sects (sect_name, sect_owner, faction_id) "
        "VALUES ('青云门', ?, 'qingyun')",
        (user_id,),
    )
    sect_id = (
        await _fetchone(db, "SELECT sect_id FROM sects WHERE sect_name = '青云门'")
    )[0]
    await db.conn.commit()
    await _make_player(db, user_id, storage_items={"青云镇山剑": 1})
    await db.conn.execute(
        "UPDATE players SET sect_id = ? WHERE user_id = ?", (sect_id, user_id)
    )
    await db.conn.commit()


@pytest.mark.asyncio
async def test_rebirth_rolls_back_delete_when_cooldown_write_fails(db, monkeypatch):
    """bd 3ar 弃道重修: stage-3 failure -> character delete and reclaim roll back.

    The pre-fix bug this test pins: ``delete_player_cascade`` committed on its
    own, so a failure in the following cooldown-key write left the character
    deleted with NO 7-day cooldown — the player could immediately restart
    cultivation, and the reclaimed sect treasures were gone as well.
    """
    uid = "u1"
    await _seed_sect_treasure_state(db, uid)
    handler = PlayerHandler.__new__(PlayerHandler)
    handler.db = db
    handler.sect_mgr = SectManager(
        db, _SectFakeConfig(), busy_state=make_busy_state(db)
    )
    handler.busy_state = make_busy_state(db)
    event = _make_event("弃道重修 确认", sender_id=uid)

    await _raise_on_leaf(monkeypatch, db.ext, "set_system_config")

    outputs = []
    with pytest.raises(RuntimeError):
        async for item in handler.handle_rebirth(event, "确认"):
            outputs.append(item)

    assert outputs == []  # 失败不得吐告别词（不得静默成功）
    player = await db.get_player_by_id(uid)
    assert player is not None  # 角色级联删除已回滚
    assert "青云镇山剑" in player.get_storage_ring_items()  # 宗门之宝回收已回滚
    assert await db.ext.get_system_config(f"rebirth_last_{uid}") is None  # 冷却键未写
    _assert_committed_and_idle(db)


@pytest.mark.asyncio
async def test_rebirth_commits_reclaim_delete_and_cooldown(db):
    """bd 3ar 弃道重修 success path: reclaim + delete + cooldown key all persist."""
    uid = "u1"
    await _seed_sect_treasure_state(db, uid)
    handler = PlayerHandler.__new__(PlayerHandler)
    handler.db = db
    handler.sect_mgr = SectManager(
        db, _SectFakeConfig(), busy_state=make_busy_state(db)
    )
    handler.busy_state = make_busy_state(db)
    event = _make_event("弃道重修 确认", sender_id=uid)

    outputs = [item async for item in handler.handle_rebirth(event, "确认")]

    assert len(outputs) == 1
    assert "青云镇山剑" in str(outputs[0]) and "已归还宗门" in str(outputs[0])
    assert await db.get_player_by_id(uid) is None  # 角色已删除
    assert await db.ext.get_system_config(f"rebirth_last_{uid}") is not None
    _assert_committed_and_idle(db)

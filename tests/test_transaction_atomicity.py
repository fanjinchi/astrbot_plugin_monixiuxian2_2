"""Regression tests for transaction atomicity (openspec: fix-fake-atomic-transactions).

Covers design D6:
1. Helper contract — every helper that gained a ``commit`` parameter must not
   commit when called with ``commit=False`` (same-connection SELECT sees the
   write, rollback undoes it), while the default ``commit=True`` keeps the
   legacy standalone behavior.
2. Mid-transaction failure rollback — bank deposit, storage-ring retrieve,
   shop purchase and the overdue-loan kill path must roll back every write
   when the last write of the block raises.
3. Nesting guard — inside each repaired transaction block, the connection must
   still be in a transaction right after every helper call (machine-checked
   "nobody committed early").
4. Shop purchase success path — buying equipment/material items must persist
   both the item in the storage ring and the gold deduction (D5 stale-player
   overwrite regression), and pill purchases must credit the pill inventory.
"""

import sys
import time
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from tests.helpers import load_package_module

# Load-order note: shop_handler uses package-attribute imports
# (``from ..core import ...`` / ``from ..data import ...``). Loading it FIRST lets
# the synthetic root package's ``__path__`` resolve the REAL core/data/models
# packages; pre-registering synthetic stubs for them (which load_package_module
# would do) shadows them with empty modules and breaks those imports.
_shop_mod = load_package_module(
    "handlers/shop_handler.py", "astrbot_plugin_monixiuxian2_2.handlers.shop_handler"
)
ShopHandler = _shop_mod.ShopHandler

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

    def get_level_name(self, level_index: int, cultivation_type: str = "灵修") -> str:
        return f"境界{level_index}"


@pytest_asyncio.fixture
async def db(tmp_path):
    """Provide a migrated temp-file database and close it after the test."""
    database = DataBase(str(tmp_path / "test.db"))
    await database.connect()
    # Fresh-install path never touches config_manager; a mock is sufficient.
    await MigrationManager(database.conn, MagicMock()).migrate()
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
    return handler


def _spy_in_transaction(db: DataBase, monkeypatch, obj, name: str, states: list):
    """Wrap a helper so each call records (name, commit kwarg, in_transaction)."""
    original = getattr(obj, name)

    async def spy(*args, **kwargs):
        await original(*args, **kwargs)
        states.append((name, kwargs.get("commit", True), db.conn.in_transaction))

    monkeypatch.setattr(obj, name, spy)


# ===== 7.1 helper 守约测试：commit=False 不提交、可回滚；默认 commit=True 落盘 =====


@pytest.mark.asyncio
async def test_update_bank_account_commit_contract(db):
    await db.conn.execute("BEGIN IMMEDIATE")
    await db.ext.update_bank_account("u1", 500, 123, commit=False)
    assert db.conn.in_transaction  # 未提前提交
    assert await db.ext.get_bank_account("u1") == {
        "balance": 500,
        "last_interest_time": 123,
    }
    await db.conn.rollback()
    assert await db.ext.get_bank_account("u1") is None  # 回滚可撤销

    await db.ext.update_bank_account("u1", 500, 123)  # 默认提交，存量语义不变
    assert not db.conn.in_transaction
    assert (await db.ext.get_bank_account("u1"))["balance"] == 500


@pytest.mark.asyncio
async def test_create_loan_commit_contract(db):
    now = int(time.time())
    await db.conn.execute("BEGIN IMMEDIATE")
    # last_insert_rowid 是连接级状态，commit=False 时查询留在事务内仍能取到 id（design D2）
    loan_id = await db.ext.create_loan(
        "u1", 1000, 0.005, now, now + 7 * 86400, commit=False
    )
    assert loan_id > 0
    assert db.conn.in_transaction
    assert (await db.ext.get_active_loan("u1"))["principal"] == 1000
    await db.conn.rollback()
    assert await db.ext.get_active_loan("u1") is None

    loan_id = await db.ext.create_loan("u1", 1000, 0.005, now, now + 7 * 86400)
    assert loan_id > 0
    assert not db.conn.in_transaction
    assert (await db.ext.get_active_loan("u1"))["id"] == loan_id


@pytest.mark.asyncio
async def test_close_loan_commit_contract(db):
    now = int(time.time())
    loan_id = await db.ext.create_loan("u1", 1000, 0.005, now, now + 7 * 86400)

    await db.conn.execute("BEGIN IMMEDIATE")
    await db.ext.close_loan(loan_id, commit=False)
    assert db.conn.in_transaction
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,))
    assert row[0] == "closed"
    await db.conn.rollback()
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,))
    assert row[0] == "active"

    await db.ext.close_loan(loan_id)
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,))
    assert row[0] == "closed"


@pytest.mark.asyncio
async def test_mark_loan_overdue_commit_contract(db):
    now = int(time.time())
    loan_id = await db.ext.create_loan("u1", 1000, 0.005, now, now + 7 * 86400)

    await db.conn.execute("BEGIN IMMEDIATE")
    await db.ext.mark_loan_overdue(loan_id, commit=False)
    assert db.conn.in_transaction
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,))
    assert row[0] == "overdue"
    await db.conn.rollback()
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,))
    assert row[0] == "active"

    await db.ext.mark_loan_overdue(loan_id)
    row = await _fetchone(db, "SELECT status FROM bank_loans WHERE id = ?", (loan_id,))
    assert row[0] == "overdue"


@pytest.mark.asyncio
async def test_add_bank_transaction_commit_contract(db):
    await db.conn.execute("BEGIN IMMEDIATE")
    await db.ext.add_bank_transaction(
        "u1", "deposit", 100, 600, "存入灵石", 1, commit=False
    )
    assert db.conn.in_transaction
    txs = await db.ext.get_bank_transactions("u1")
    assert len(txs) == 1 and txs[0]["amount"] == 100
    await db.conn.rollback()
    assert await db.ext.get_bank_transactions("u1") == []

    await db.ext.add_bank_transaction("u1", "deposit", 100, 600, "存入灵石", 1)
    assert not db.conn.in_transaction
    assert len(await db.ext.get_bank_transactions("u1")) == 1


@pytest.mark.asyncio
async def test_delete_player_cascade_commit_contract(db):
    await _make_player(db)

    await db.conn.execute("BEGIN IMMEDIATE")
    await db.delete_player_cascade("u1", commit=False)
    assert db.conn.in_transaction
    assert (
        await _fetchone(db, "SELECT user_id FROM players WHERE user_id = 'u1'") is None
    )
    await db.conn.rollback()
    assert await db.get_player_by_id("u1") is not None  # 回滚可撤销

    await db.delete_player_cascade("u1")  # 默认提交，存量语义不变
    assert not db.conn.in_transaction
    assert await db.get_player_by_id("u1") is None


@pytest.mark.asyncio
async def test_bank_manager_add_transaction_commit_contract(db):
    mgr = BankManager(db)

    await db.conn.execute("BEGIN IMMEDIATE")
    await mgr._add_transaction("u1", "deposit", 100, 600, "存入灵石", commit=False)
    assert db.conn.in_transaction
    assert len(await db.ext.get_bank_transactions("u1")) == 1
    await db.conn.rollback()
    assert await db.ext.get_bank_transactions("u1") == []

    await mgr._add_transaction("u1", "deposit", 100, 600, "存入灵石")
    assert not db.conn.in_transaction
    assert len(await db.ext.get_bank_transactions("u1")) == 1


@pytest.mark.asyncio
async def test_add_pill_to_inventory_commit_contract(db):
    pill_mgr = PillManager(db, FakeConfigManager())
    await _make_player(db)

    player = await db.get_player_by_id("u1")
    await db.conn.execute("BEGIN IMMEDIATE")
    await pill_mgr.add_pill_to_inventory(player, "回气丹", 2, commit=False)
    assert db.conn.in_transaction
    row = await _fetchone(
        db, "SELECT pills_inventory FROM players WHERE user_id = 'u1'"
    )
    assert "回气丹" in row[0]
    await db.conn.rollback()
    assert (await db.get_player_by_id("u1")).get_pills_inventory() == {}

    player = await db.get_player_by_id("u1")  # 重取，避免沿用被 mutation 的旧对象
    await pill_mgr.add_pill_to_inventory(player, "回气丹", 2)
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
    await db.conn.execute("BEGIN IMMEDIATE")
    ok, _ = await handler._apply_legacy_pill_effects(player, item, 1, commit=False)
    assert ok
    assert db.conn.in_transaction
    row = await _fetchone(db, "SELECT experience FROM players WHERE user_id = 'u1'")
    assert row[0] == 100
    await db.conn.rollback()
    assert (await db.get_player_by_id("u1")).experience == 0

    player = await db.get_player_by_id("u1")  # 重取，避免沿用被 mutation 的旧对象
    ok, _ = await handler._apply_legacy_pill_effects(player, item, 1)
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

    async def update_then_boom(player, commit=True):
        await original(player, commit=commit)
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
    """deposit/withdraw/borrow/repay 四块：helper 全部 commit=False 且不提前提交。"""
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

    # 四个块共触发 12 次 helper 写，全部 commit=False 且调用后仍在事务内
    assert len(states) == 12, states
    assert all(commit is False and in_tx for _, commit, in_tx in states), states


@pytest.mark.asyncio
async def test_storage_ring_blocks_never_leave_transaction(db, monkeypatch):
    """store/retrieve/discard 三块：块内 update_player 全部 commit=False 且不提前提交。"""
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
    assert all(commit is False and in_tx for _, commit, in_tx in states), states


@pytest.mark.asyncio
async def test_shop_buy_block_never_leaves_transaction(db, monkeypatch):
    """商店购买块（装备路径）：store_item 与最终扣款两次 update_player 均 commit=False。"""
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
    assert all(commit is False and in_tx for _, commit, in_tx in states), states


@pytest.mark.asyncio
async def test_check_loan_status_block_never_leaves_transaction(db, monkeypatch):
    """逾期追杀块：cascade/mark_overdue/add_bank_transaction 均 commit=False 且不提前提交。"""
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
    assert all(commit is False and in_tx for _, commit, in_tx in states), states

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
    """external_transaction=False 的独立调用路径保持重取语义（D5 不改变的行为）。"""
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

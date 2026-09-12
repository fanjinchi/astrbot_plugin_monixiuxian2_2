# add-transaction-unit-of-work

## Why

"多步写是否在同一事务"目前是一条**调用约定**（写 helper 接 `commit: bool = True` / `external_transaction: bool = False`，调用方手动 `BEGIN IMMEDIATE` 并逐点放 rollback），而非可强制的接口。该约定已产生复发 bug 类：git 历史有 `fix-fake-atomic-transactions`、bd 9jt、bd 9yg 连续三处补丁，且养着 `tests/test_transaction_atomicity.py` 28 个测试函数作为机器检查——测试在为缺失的 seam 买单。

## What Changes

- `data/data_manager.py` 的 `DataBase` 新增 `async with db.transaction():` 单元工作上下文管理器：entry 时若 `conn.in_transaction` 为 False 则 `BEGIN IMMEDIATE`，否则 no-op join（内层放行，最外层全权 commit/rollback）；提供显式 `txn.abort()` 供锁内复查后放弃的场景。
- 写 helper（~33 个定义）改为依据 `conn.in_transaction` 决定是否提交（连接自身已知道的事，替代 flag）；`commit`/`external_transaction` 参数标记为过渡兼容，第二阶段移除。
- 绞杀者迁移 ~27 个手工 `BEGIN IMMEDIATE` 块 / 50 处穿参点（sect 15、bank 18、shop 3+4、utils 3、storage_ring 3、player_handler 2、impart 2），按块推进（bank_manager 6 块试点 → 其余模块）；early-exit 模式按"能前置的复查前置，必须锁内复查的用 `txn.abort()`"收编。
- `tests/test_transaction_atomicity.py`：§7.2/7.4/7.5（与设计无关的原子性核心）全程守护；§7.1 kwarg 相关断言与 6 个 spy 测试（§7.3 ×4 + §7.5 ×2，spy `commit=False` kwarg）随 flag 移除改写为 CM 级测试（嵌套 no-op join / 仅最外层提交 / abort 走 rollback；改写时只断言 `in_transaction` 状态，不再依赖 kwarg 默认值回读）。
- 同步创建 `CONTEXT.md` 并登记新概念 `unit-of-work`。

**非目标**：不引入 SAVEPOINT 嵌套语义（无调用点需要）；不改任何对外可观察行为（原子性已是由测试钉住的现状契约）；不做候选2（`BusyState`）——本 change 是其前置基建。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 — 事务原子性是工程约束，由测试钉住、无 spec 需求条目；本 change 不修改任何需求级行为。故 `.openspec.yaml` 设 `skip_specs: true`。）

## Impact

- **代码**：`data/data_manager.py`（+CM）、`data/database_extended.py`（~21 个 helper）、`managers/`（sect、bank、bounty、impart、spirit_eye…）、`handlers/`（shop、utils、player_handler…）、`core/storage_ring_manager.py` —— ~12 文件，纯机械替换为主。
- **测试**：`tests/test_transaction_atomicity.py` 改写部分断言；新增 CM 级测试。
- **文档**：`CONTEXT.md` 新建；AGENTS.md §3 数据库操作规范补一句 CM 用法（指针式）。
- **依赖**：aiosqlite 0.22.1 已验证提供 `Connection.in_transaction`（跨线程读正确性列入 spike）。
- **无**数据库迁移、无配置变更。

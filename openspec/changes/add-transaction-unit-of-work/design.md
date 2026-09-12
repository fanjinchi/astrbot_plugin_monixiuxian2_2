# Design — add-transaction-unit-of-work

## Context

`DataBase`（data/data_manager.py:50）与 `DatabaseExtended`（data/database_extended.py:13）是共享一个连接的兄弟类（组合：`DataBase` 持有 `self.conn`，构造 `self.ext = DatabaseExtended(self.conn)`）。连接经 `aiosqlite.connect(self.db_path)` 创建，**未设 `isolation_level`** → sqlite3 旧版默认 `""`：DML 前隐式 BEGIN，任何 `conn.commit()` 结束事务并释放写锁——这是归档 change `2026-09-01-fix-fake-atomic-transactions` 的物理根源。

约定现状两种 flag 形态：`commit: bool = True`（**34 个定义**：`data_manager.py` 2、`database_extended.py` 25、`core/pill_manager.py` 1、`managers/bank_manager.py` 1、`managers/impart_manager.py` 4、`handlers/shop_handler.py` 1，commit=False 意为"外层拥有提交权"）与 `external_transaction: bool = False`（仅 2 个自事务 helper：自己 BEGIN 或完全跳过）。其中 **2 个 helper（`set_active_legacy_instance` :446、`learn_or_star_up` :793）用 commit 门控自己的 `BEGIN IMMEDIATE`** 而非 `conn.commit()`——D2 变换不覆盖它们，随第二阶段收编。另有 2 个 helper 自事务无 flag（`decrement_shop_item_stock` 有 flag、`increment_shop_item_stock` 无条件 BEGIN）。调用盘：50 处穿参点 + **26 个**手工 `BEGIN IMMEDIATE` 块（sect 8、bank 6、storage_ring 3、bounty 3、shop 1、utils 1、player_handler 1、spirit_eye 1、impart 1、gm 1）。

aiosqlite 0.22.1（已在 AstrBot venv 验证）：`Connection.in_transaction` 存在（sync property，直连底层 sqlite3 连接，跨 worker 线程读）；`execute("BEGIN IMMEDIATE")` 在旧版 isolation_level 下按原样下发。**风险**：`in_transaction` 在连接关闭时抛 `ValueError`（`_conn` 守卫）；属性是 SimpleQueue 工作线程外的未同步读（实践安全：协程恢复前队列已排空，但列入 spike 压力验证）。

## Goals / Non-Goals

**Goals:**
- 事务边界跟着缩进走：`async with db.transaction():` 一眼可见，"提前 commit"在构造上不可能。
- 行为与现状等价：原子性语义（块内任一步失败全回滚）不变，对外可观察行为零变化。
- 绞杀者迁移：flag 与 CM 共存期内全部现有测试保持通过，作为逐块迁移的安全网。

**Non-Goals:**
- SAVEPOINT / 内层独立回滚（无调用点需要；逾期贷款的逐条容错用顺序兄弟事务，no-op join 天然支持）。
- 改连接的 `isolation_level` / autocommit 配置。
- 候选2（BusyState owner）——本 change 只做基建，owner 是其首个真实消费者（后续 change）。

## Decisions

**D1 · CM 归属 `DataBase`（data/data_manager.py），签名 `async with db.transaction():`，句柄暴露 `abort()`。**
`DataBase` 拥有 `self.conn`，manager 层处处持有 `self.db`。语义：entry 时 `if not self.conn.in_transaction: BEGIN IMMEDIATE`（连接关闭时按 ValueError 视为 False 前先 ensure_connection 由调用方负责——本 change 不加事务内 ensure_connection，见风险 R5）；干净退出且无 abort → commit；异常 → rollback 后 re-raise。嵌套 = no-op join：内层只记深度标记，**内层块异常冒泡 = 整体回滚**（写进 docstring，等价于今天手工写法）。**`__aexit__` 按 `exc_type is not None` 分支判定异常路径（不得 `except Exception`）**——`CancelledError`/`GeneratorExit` 是 BaseException，`except Exception` 实现会在取消/生成器关闭时泄漏未关闭的事务。**嵌套 abort 传播**：任一层（含 no-op join 内层）调用 `txn.abort()` 都把标记传至最外层拥有者，内层 abort 不会被外层提交盖过。**abort 契约（对外承诺，下游 change 依赖）**：`txn.abort()` 只置标记不抛异常（幂等）；标记后块内 clean exit（return）→ `__aexit__` 走 rollback 且不 re-raise（调用方拿失败文案返回）；abort 与异常并存时按异常路径 rollback + re-raise。

**D2 · helper 先行切 `in_transaction` 判定，block 迁移随后。**
**25 个叶子 helper**（`data_manager.py` 2、`database_extended.py` 23）体内有 `if commit: await self.conn.commit()`，改为 `if commit and not self.conn.in_transaction: commit`（等价：事务外 = 今天的行为；事务内 = 不再提前提交——今天靠约定、今后靠构造）。**7 个纯透传 wrapper**（`core/pill_manager.py:654`、`managers/bank_manager.py:458`、`handlers/shop_handler.py:345`、`managers/impart_manager.py` ×4）无本地提交门控，第一阶段零改动，随叶子行为自动继承。**例外**：`set_active_legacy_instance` / `learn_or_star_up` 的 commit 门控的是 BEGIN IMMEDIATE（:460-461、:830-831），本阶段不动，随 4.2 收编时把 BEGIN 条件一并改为 `commit and not in_transaction`。已核验：全部 26 个块内调用均为 `commit=False`/`external_transaction=True` 或裸 SQL，生产代码不存在"事务内 commit=True 调用"——D2 不破坏任何现有 §7.1/§7.3 测试。这一步行为保持，且使之后每个块的转换"进 CM 即安全"，调用点的 `commit=False` 可留待第二阶段一并清理。

**D3 · early-exit 收编策略（Q2 决策 = c 混合）。**
现状 8+ 处 sect 块与若干 bank 块是"BEGIN → 锁内复查 → 显式 rollback → return 失败文案"。能前置的复查挪到 CM 之前（多数 bank 块成立）；必须锁内复查的（sect `complete_construction_task` 的锁内 re-read 正是其 BEGIN 目的）用 `txn.abort()`。commit-on-clean-exit + abort 标记实现，不改 return 文案。

**D4 · 迁移顺序：bank 试点 → 其余模块逐块 → 第二阶段删 flag。**
bank_manager 6 块几乎同构（含 bd 9jt 刚修过的 claim_interest / 逾期追杀，回归价值最高）作试点；sect_manager 8 块（含锁内复查最复杂场景）随后；其余按模块清。每块转换 = "一个事务块 + 其调用点"，不是整个文件。第二阶段：50 处穿参清零后，从 34 个定义移除 flag（其中 2 个 BEGIN 门控 helper 随 4.2 收编），自事务 helper 收编为 CM，§7.1 kwarg 断言与 6 个 spy 测试改写为 CM 级测试。

**D5 · 测试策略：§7.2/7.4/7.5 全程不动。**
这三组（中途注入失败全回滚、D5 stale-player 回归、bd 9jt 贷款原子性）与设计无关，是原子性契约的核心守护，迁移期原样运行。flag 退役时仅动 §7.1/§7.3。

## Risks / Trade-offs

- [生成器 handler `handle_buy` 在事务体内 yield，`except Exception`（:311）捕不到 GeneratorExit——**今天是预存的写锁泄漏**（生成器在任一 yield 点被关闭则 BEGIN 的写锁残留），CM 的 `__aexit__` 会静默修复它] → 转换时**删除块内现已失效的手工 `except Exception: rollback`**（勿与 CM 嵌套造成双 rollback）；spike 0.2 显式断言修复生效且无 "cannot rollback - no transaction" 告警。
- [`_check_loan_status` 外层 except 吞异常返回 None，与 CM 的 rollback 叠加] → 内层 re-raise → CM rollback → 外层吞异常，组合正确；sqlite rollback 无事务时的告警行为未验证，spike 0.2 加"无活动事务时 rollback"探针确认无告警。
- [abort 语义误用：调用方 abort 后继续写] → docstring 明示 abort 后块内写入仍会随事务回滚；CM 内不做运行时禁用（YAGNI）。
- [`in_transaction` 在已关闭连接抛 ValueError] → helper 判定前先走既有 `_connection_alive`/ensure_connection 路径的调用方纪律不变；本 change 不新增事务内重连（`ensure_connection` 仅定时任务调用，现状已安全）。
- [迁移中途信号模糊：新旧两套检查并存] → 接受；§7.3 spy 测试在迁移完成前持续给出"哪块还没转"的信号，这正是保留它们到第二阶段的理由。
- [某未转换块依赖 helper "在事务内也提交"的隐式行为] → 不存在：事务内 commit 即 bug 本体，D2 反而修复之；若注入测试暴露意外依赖，按 bug 处理并登记 bd。

## Migration Plan

无部署步骤，随插件重载生效；无 DB/配置变更。回滚 = revert 对应 commit（按块提交，块间可独立回滚）。

## Open Questions

- spike（任务 0）回答，不影响本设计：`in_transaction` 跨线程读在并发事务压力下的正确性；`GeneratorExit` 进 `handle_buy` 的 rollback 行为（含写锁泄漏修复断言）与无活动事务时 rollback 的告警探针；`txn.abort()` 原型在 deposit 与一个 sect 块上的手感（按上文 abort 契约实现）。
- 非目标备注：`data/migration.py:555,590,615` 迁移期 plain `BEGIN` 不在本 change 范围。

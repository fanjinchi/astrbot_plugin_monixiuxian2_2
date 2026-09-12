# Tasks — add-transaction-unit-of-work

## 0. Spike（先行，回答 design.md Open Questions，产出原型验证笔记）

- [ ] 0.1 并发压力验证：写 stress 测试（多协程并发开事务/写/提交），确认 aiosqlite 0.22.1 `in_transaction` 跨线程读在压力下无陈旧读
- [ ] 0.2 `GeneratorExit`/`CancelledError` 抛进 `handlers/shop_handler.py` `handle_buy`（事务体内 yield 的生成器）时 CM 的 rollback 正确、无 "cannot rollback - no transaction" 告警
- [ ] 0.3 `txn.abort()` 原型：在 `managers/bank_manager.py` deposit 与一个 sect 锁内复查块上试装，确认"复查失败 → abort → return 失败文案"手感成立
- [ ] 0.4 核对 `tests/test_transaction_atomicity.py` 文件头 "28 个检查" 与实计 22 个测试函数的出入（文档滞后 or 漏测试），结论记入 spike 笔记
- [ ] 0.5 spike 结论回写 design.md Open Questions；若有推翻性发现，停下重新走提案修订

## 1. 核心基建（DataBase.transaction() + helper 先行切换）

- [ ] 1.1 `data/data_manager.py` 的 `DataBase` 新增 `transaction()` 异步上下文管理器：entry 时 `in_transaction` 为 False 则 `BEGIN IMMEDIATE`，否则 no-op join（记深度）；干净退出且无 abort → commit，异常或 `txn.abort()` → rollback 后 re-raise；docstring 写明"内层块异常 = 整体回滚"与 abort 语义；英文 Google 风格 docstring
- [ ] 1.2 ~31 个 `commit` flag helper（`data/data_manager.py` 2 个、`data/database_extended.py` ~21 个、manager 层重导出若干）的提交判定改为 `if commit and not self.conn.in_transaction`；`external_transaction` 两 helper 本阶段不动
- [ ] 1.3 新增 CM 级单测：嵌套 no-op join、仅最外层提交、abort 走 rollback；`uv run python -m pytest tests/test_transaction_atomicity.py -v` 现有 22 测试保持全绿

## 2. 试点迁移（bank_manager 6 块）

- [ ] 2.1 `managers/bank_manager.py` 6 个手工块（:109、:153、:195、:281、:346、:414，含 bd 9jt 的 claim_interest / 逾期追杀）改为 `async with self.db.transaction() as txn:`；能前置的复查前置，锁内复查用 `txn.abort()`；调用点 `commit=False` 可暂留（第二阶段清理）
- [ ] 2.2 验证：bank 相关测试全绿 + 注入回归（§7.2/7.5 对应场景）通过

## 3. 其余块迁移（~21 块）

- [ ] 3.1 `managers/sect_manager.py` 8 块（含 `complete_construction_task` 锁内复查复杂场景，abort 的主要用武之地）
- [ ] 3.2 `core/storage_ring_manager.py` 3 块 + `managers/bounty_manager.py` 3 块
- [ ] 3.3 `handlers/shop_handler.py`（生成器 handler，按 spike 0.2 结论处理）、`handlers/utils.py`（`_check_loan_status`，注意吞异常路径）、`handlers/player_handler.py`、`managers/spirit_eye_manager.py`（或对应文件）、`managers/impart_manager.py`、`core/gm_manager.py`（time skip 循环，保持顺序兄弟事务语义）各 1 块
- [ ] 3.4 每块转换后跑对应模块测试；`tests/test_transaction_atomicity.py` §7.3 spy 测试保持全绿（它们此刻是"哪块还没转"的信号源）

## 4. 第二阶段：flag 退役

- [ ] 4.1 确认 54 处穿参点清零后，从 ~33 个定义移除 `commit`/`external_transaction` 参数（含 manager 层重导出）
- [ ] 4.2 4 个自事务 helper（`decrement_shop_item_stock`、`increment_shop_item_stock`、`set_active_legacy_instance`、`learn_or_star_up`）收编为 CM
- [ ] 4.3 `tests/test_transaction_atomicity.py`：§7.1 kwarg 相关断言随 flag 退役移除/改写，§7.3 的 5 个 spy 测试改写为 CM 级测试（合并进 1.3 的测试组，去重）
- [ ] 4.4 全量质量门：`uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过

## 5. 文档与收尾

- [ ] 5.1 新建 `CONTEXT.md`：登记 `unit-of-work`（`async with db.transaction():`，no-op join 嵌套，seam 在 `DataBase`）与（预留）`BusyState` 条目标注"后续 change 落地"
- [ ] 5.2 AGENTS.md §3 数据库操作规范补 CM 用法指针（一两句，不展开）
- [ ] 5.3 用 `bd` 登记 spike 暴露的新发现（如有）；`openspec validate --changes add-transaction-unit-of-work` 通过；按块 conventional commit（试点/迁移/退役各自独立 commit）

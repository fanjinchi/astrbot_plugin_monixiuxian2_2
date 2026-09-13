# Tasks — add-transaction-unit-of-work

## 0. Spike（先行，回答 design.md Open Questions，产出原型验证笔记）

- [ ] 0.1 深度计数器原型：按 design D0/D1 实现最小版（`connect()` 初始化 `conn._txn_depth`、重连重建、`depth==0` 才 BEGIN、owner-only 提交/回滚、嵌套 abort 传播），并原型验证 §7.1 场景共存（hand-BEGIN + `commit=False` helper 调用不提交、独立调用正常提交）——确认初版 `in_transaction` 判据的实测缺陷被彻底绕开
- [ ] 0.2 生成器探针：`GeneratorExit`/`CancelledError` 抛进 `handlers/shop_handler.py` `handle_buy`（事务体内 yield 的生成器）时 CM rollback 正确、**写锁泄漏修复生效**（今天 :311 的 `except Exception` 捕不到 GeneratorExit，BEGIN 写锁会残留）、无 "cannot rollback - no transaction" 告警；另加"无活动事务时 rollback"探针
- [ ] 0.3 `txn.abort()` 原型：在 `managers/bank_manager.py` deposit 与一个 sect 锁内复查块上试装，确认"复查失败 → abort → return 失败文案"手感成立（按 design D1 的 abort 契约：abort 标记后 clean exit = owner 层 rollback 不 re-raise）
- [ ] 0.4 spike 结论回写 design.md Open Questions；若有推翻性发现，停下重新走提案修订

## 1. 核心基建（DataBase.transaction() + helper 先行切换）

- [ ] 1.0 `connect()` 显式声明 `isolation_level=""`（钉住现状默认值）+ 注释说明 CM/门控依赖隐式 BEGIN 语义；`conn._txn_depth = 0` 初始化（含 `ensure_connection` 重建路径）
- [ ] 1.1 `data/data_manager.py` 的 `DataBase` 新增 `transaction()` 异步上下文管理器（按 design D1/D1.1 完整语义）：**一次性 `TxnState` 对象**（owner 入口创建、句柄共享引用、abort 标记随 owner 退出整体丢弃）；**`await BEGIN IMMEDIATE` 成功返回后同步置 `depth = 1`**（与置位间无 await 点），owner 层退出做 commit/rollback，**未发 BEGIN 层完全被动**；`depth` 递减与 state 丢弃用 **finally 语义**（owner 层 commit/rollback 自身抛异常也不残留状态）；**`__aenter__` 异常路径 best-effort rollback**；**`__aexit__` 按 `exc_type is not None` 分支（BaseException 安全，不得 `except Exception`）**；`txn.abort()` 按 design D1 契约（幂等标记；clean exit 走 rollback 不 re-raise）；docstring 写明 owner 语义、fail-open 门控的理由（3 个裸 conn 测试构造依赖默认 0=旧提交语义）、abort 语义与"CM 不得进入 raw BEGIN 块"过渡约束；英文 Google 风格 docstring
- [ ] 1.2 **25 个叶子 helper**（`data_manager.py` 2、`database_extended.py` 23）的提交判定改为 `if commit and getattr(self.conn, "_txn_depth", 0) == 0`（所有权判据；**fail-open 默认 0 是设计**——data/database_extended 或 tests 的裸 conn 构造退回旧提交语义，行内注释说明）；**7 个纯透传 wrapper**（`core/pill_manager.py:654`、`bank_manager.py:458`、`shop_handler.py:345`、`impart_manager.py` ×4）零改动；**`set_active_legacy_instance` / `learn_or_star_up` 例外**（commit 门控 BEGIN），本阶段不动、随 4.2 收编
- [ ] 1.3 新增 CM 级单测：嵌套 no-op join、仅 owner 层提交、abort 走 rollback、**abort 标记不泄漏到下一笔事务**（①的回归钉）、**BEGIN 失败时 depth 不残留**（②的回归钉）、**前提断言**（连接 `isolation_level` 仍为 `""`）；`uv run python -m pytest tests/test_transaction_atomicity.py -v` 现有 **28 个测试函数**不改保持全绿

## 2. 试点迁移（bank_manager 6 块）

- [ ] 2.1 `managers/bank_manager.py` 6 个手工块（:109、:153、:195、:281、:346、:414，含 bd 9jt 的 claim_interest / 逾期追杀——逾期追杀循环保持**顺序兄弟事务**语义：逐条独立事务、单条失败不影响其他）改为 `async with self.db.transaction() as txn:`；能前置的复查前置，锁内复查用 `txn.abort()`；调用点 `commit=False` 可暂留（第二阶段清理）
- [ ] 2.2 验证：bank 相关测试全绿 + 注入回归（§7.2/7.5 对应场景）通过

## 3. 其余块迁移（20 块）

- [ ] 3.1 `managers/sect_manager.py` 8 块（:839、:1049、:1198、:1369、:1588、:1708、:1831、:2129，含 `complete_construction_task` 锁内复查复杂场景，abort 的主要用武之地）
- [ ] 3.2 `core/storage_ring_manager.py` 3 块（:123、:169、:206）+ `managers/bounty_manager.py` 3 块（:331、:445、:599）
- [ ] 3.3 `handlers/shop_handler.py`（生成器 handler，按 spike 0.2 结论处理，**删除块内失效的手工 except**）、`handlers/utils.py`（`_check_loan_status` :161，注意外层吞异常路径与内层 re-raise 的组合）、`handlers/player_handler.py`（:540）、`managers/spirit_eye_manager.py`（:72，`claim_spirit_eye`）、`managers/impart_manager.py`（:225）、`core/gm_manager.py`（:1187，time skip 为**单事务**包住整个 `_TIME_SKIP_RULES` 循环，保持全有或全无语义）各 1 块
- [ ] 3.4 每块转换后跑对应模块测试；§7.3 spy 测试（覆盖 bank/storage_ring/shop/utils）保持全绿——**注意其信号范围仅限这 4 个模块**，sect/bounty/spirit_eye/impart/gm/player_handler 各块以模块测试 + 人工核对为验证手段

## 4. 第二阶段：flag 退役

- [ ] 4.1 确认 50 处穿参点（sect 15、bank 18、shop 3+4、utils 3、storage_ring 3、player_handler 2、impart 2）清零后，从 34 个定义移除 `commit`/`external_transaction` 参数（含 manager 层重导出）
- [ ] 4.2 5 个自事务 helper 收编为 CM：`decrement_shop_item_stock`、`increment_shop_item_stock`（**收编时须加 `depth == 0` 门控**，其当前无条件 BEGIN 在 CM 内会撞 "cannot start a transaction"）、`set_active_legacy_instance`、`learn_or_star_up`（后两者 BEGIN 条件一并改为 `depth == 0` 判定，替换其碰巧正确的 `in_transaction` 检查）、**`StorageRingManager.store_item`**（`core/storage_ring_manager.py:101`，第二个 `external_transaction` 持有者；~11 个独立调用方在事务外依赖其自 BEGIN 路径——equipment/storage_ring handlers、boss/adventure/spirit_farm/bounty/rift managers、gm_manager ×2、equipment_manager，收编后这些独立调用保持原语义）
- [ ] 4.3 `tests/test_transaction_atomicity.py`：§7.1 kwarg 相关断言随 flag 退役移除/改写；**6 个 spy 测试**（§7.3 ×4 + §7.5 ×2）改写为 CM 级断言——**断 `conn._txn_depth` ownership 信号**（CM 内 >0、CM 外 == 0、仅 owner 层提交），不只断 `in_transaction`（裸 DML 后恒真，会"因错误的原因通过"）；不依赖 `kwargs.get("commit", True)` 默认值回读；合并进 1.3 的测试组去重
- [ ] 4.4 全量质量门：`uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过

## 5. 文档与收尾

- [ ] 5.1 新建 `CONTEXT.md`（仓库根，中文）：**条目三字段格式——术语 / 一句话定义 / 权威代码符号（seam 位置 + 落地 change 链接）**；登记 `unit-of-work`（`async with db.transaction():`，`conn._txn_depth` 所有权判据，owner-only 提交，seam 在 `DataBase`）与（预留）`BusyState` 占位条目（busy-state-owner 按此格式替换落实）
- [ ] 5.2 AGENTS.md 两处：§3 数据库操作规范替换纯手写 BEGIN 惯例为 CM 指针，并写入**转换规则**（任何手工提交点未来包进 CM 时必须同步删除体内裸 `conn.commit()`）；**文档地图表登记 `CONTEXT.md`**（维护责任：新增/重命名领域概念时同步登记条目）
- [ ] 5.3 用 `bd` 登记 spike 暴露的新发现（如有）；`openspec validate --changes add-transaction-unit-of-work` 通过；按块 conventional commit（试点/迁移/退役各自独立 commit）

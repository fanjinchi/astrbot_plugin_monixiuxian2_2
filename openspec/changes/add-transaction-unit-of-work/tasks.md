# Tasks — add-transaction-unit-of-work

> **行号重锚（2026-09-16）**：hygiene 批次落地后已对照当前代码修正漂移引用（pill_manager wrapper :654→:628 等，详见 design.md 注记）；实施前仍按 0.1 复核。**二次校正（2026-09-17 评审）**：player_handler 签到跨日重置块在 :533（原写 :540）；gm time-skip 块 :1187 内另含裸 commit :1193（随 3.3 转换删除）；dual_cultivation accept_request 为四叶提交（非双叶，仅知识性修正）。

## 0. Spike（先行，回答 design.md Open Questions，产出原型验证笔记）

^- [x] 0.1 深度计数器原型：按 design D0/D1/D1.2 实现最小版（`connect()` 初始化 `conn._txn_depth = 0`、`conn._txn_owner_task = None`、`DataBase._txn_free = asyncio.Condition()`，重连重建；owner 空闲且 `depth==0` 才 BEGIN、同任务嵌套 no-op join、owner-only 提交/回滚、嵌套 abort 传播、**跨任务进入锁内等待 + 按 D1.2 认领（锁内置位 → 出锁 BEGIN → 失败补偿）**），并原型验证 §7.1 场景共存（hand-BEGIN + `commit=False` helper 调用不提交、独立调用正常提交）——确认初版 `in_transaction` 判据的实测缺陷被彻底绕开
^- [x] 0.2 生成器探针：`GeneratorExit`/`CancelledError` 抛进 `handlers/shop_handler.py` `handle_buy`（事务体内 yield 的生成器）时 CM rollback 正确、**写锁泄漏修复生效**（今天 :311 的 `except Exception` 捕不到 GeneratorExit，BEGIN 写锁会残留）、无 "cannot rollback - no transaction" 告警；另加"无活动事务时 rollback"探针
^- [x] 0.3 `txn.abort()` 原型：在 `managers/bank_manager.py` deposit 与一个 sect 锁内复查块上试装，确认"复查失败 → abort → return 失败文案"手感成立（按 design D1 的 abort 契约：abort 标记后 clean exit = owner 层 rollback 不 re-raise）
^- [x] 0.4 spike 结论回写 design.md Open Questions；若有推翻性发现，停下重新走提案修订
^- [x] 0.5 **跨任务交错探针（2026-09-17 评审新增；2026-09-18 随锁内认领协议修订，回答 design D1.2/F1/F2）**：`asyncio.gather` 并发 CM 块（先到者块内多次 await 制造窗口）——断言 ① 后到者的 BEGIN 严格发生在先到者退出之后（事件标记先后断言；等待期后到者自身 `_txn_depth == 0`、`_txn_owner_task` 非 None——持有着是先到者）；② 后到者先 `txn.abort()` 时先到者事务照常提交（abort 不跨任务）；③ **3 任务认领竞争探针（F1 闭合）**：owner + 两个等待者被同一次 `notify_all()` 唤醒 → 锁内认领下**恰好一次 BEGIN 发出**、输家回锁重查后继续等待且**未执行 rollback**、赢家最终 commit 成功；④ owner 在 COMMIT await 点被取消时等待者行为实测记录（决定是否需要等待超时）；⑤ 认领者在 BEGIN await 点被取消 → 补偿清位后等待者能正常认领（孤儿事务冲突实测）。结论回写 design D1.2/Risks；若静默共享事务或双 BEGIN 可复现，停下重新走提案修订

## 1. 核心基建（DataBase.transaction() + helper 先行切换）

- [x] 1.0 `connect()` 显式声明 `isolation_level=""`（钉住现状默认值）+ 注释说明 CM/门控依赖隐式 BEGIN 语义；`conn._txn_depth = 0`、`conn._txn_owner_task = None` 初始化 + `DataBase._txn_free = asyncio.Condition()`（含 `ensure_connection` 重建路径）
- [x] 1.1 `data/data_manager.py` 的 `DataBase` 新增 `transaction()` 异步上下文管理器（按 design D0/D1/D1.1/D1.2 完整语义）：**存储选型 (a)——`conn._txn_depth: int`（门控/断言读它）+ `conn._txn_state: TxnState | None`（只装 abort 标记，owner 退出置 None；内层 CM 经它发现共享 state）**；一次性 `TxnState`（owner 入口创建、句柄共享引用）；**认领协议按 D1.2：锁内置 `_txn_owner_task = current`、`depth = 1`、`state = TxnState()`，出锁后再 `await BEGIN IMMEDIATE`**（失败走补偿清位，『有主无事务』不可能持续；同一时刻最多一个任务发出 BEGIN），owner 层退出做 commit/rollback，**未发 BEGIN 层完全被动**；owner 提交路径 **try: commit → except: best-effort `conn.rollback()` → raise**（commit 失败不留开着的事务）；`depth` 递减、`_txn_owner_task` 置 None、`state` 置 None 用 **finally 语义（按序复位）**；**`__aenter__` 异常路径 = 补偿子句**（BEGIN 失败或认领期间被取消：锁内清位 + `notify_all()` + best-effort rollback + re-raise）；**`__aexit__` 按 `exc_type is not None` 分支（BaseException 安全，不得 `except Exception`）**；`txn.abort()` 按 design D1 契约（幂等标记；clean exit 走 rollback 不 re-raise）；docstring 写明 owner 语义、fail-open 门控的理由（3 个裸 conn 测试构造依赖默认 0=旧提交语义）、abort 语义与"CM 不得进入 raw BEGIN 块"过渡约束；**跨任务互斥（D1.2 锁内认领 + 失败补偿）**：`_txn_owner_task`（owner 判定，`is` 身份比较）+ `DataBase._txn_free`（等待/唤醒）——同任务快速路径（`owner is current`）直接 `depth += 1`、不进 Condition；否则 `async with self._txn_free:` 内 `while _txn_owner_task is not None: await self._txn_free.wait()` → 锁内认领 → 出锁 BEGIN；**等待者永不自行 BEGIN**（唤醒后锁内重查，非 None 继续 wait）；owner 退出 finally 按序 depth 归零 → `_txn_owner_task = None` → state 置 None → **锁内 `notify_all()`（F2 复位顺序）**；**配套断言随 1.3 落地：owner 退出后等待者观察到 `owner is None` 并能完成认领（F2 回归钉）+ 3 任务认领竞争（F1 回归钉）**；英文 Google 风格 docstring（并发语义、断连静默窗口一并写明）
- [x] 1.2 **25 个叶子 helper**（`data_manager.py` 2、`database_extended.py` 23）的提交判定改为 `if commit and getattr(self.conn, "_txn_depth", 0) == 0`（所有权判据；**fail-open 默认 0 是设计**——data/database_extended 或 tests 的裸 conn 构造退回旧提交语义，行内注释说明）；**7 个纯透传 wrapper**（`core/pill_manager.py:628`、`bank_manager.py:458`、`shop_handler.py:345`、`impart_manager.py` ×4）零改动；**`set_active_legacy_instance` / `learn_or_star_up` 例外**（commit 门控 BEGIN），本阶段不动、随 4.2 收编
- [x] 1.3 新增 CM 级单测：嵌套 no-op join、仅 owner 层提交、abort 走 rollback、**abort 标记不泄漏到下一笔事务**（①的回归钉）、**BEGIN 失败时 depth/owner/state 不残留**（②的回归钉）、**前提断言**（连接 `isolation_level` 仍为 `""`，另加裸 DML 后 `in_transaction` 为 True 的行为断言——防"属性值没变但语义已变"的假绿）、**跨任务互斥（D1.2/F1/F2 回归钉）**（asyncio.gather 双 CM：后到者 BEGIN 严格在先到者退出后；后到者 abort 不影响先到者；**owner 退出后等待者观察到 `_txn_owner_task is None` 并能完成认领（F2）**；**3 任务认领竞争：同一次 `notify_all()` 唤醒两个等待者 → 恰好一次 BEGIN 发出、输家继续等待且未执行 rollback（F1）**——0.5 探针转正式断言）；`uv run python -m pytest tests/test_transaction_atomicity.py -v` 现有 **28 个测试函数**不改保持全绿

## 2. 试点迁移（bank_manager 6 块）

- [x] 1.4 **mutation check（守卫有效性验证）**：新 CM 级测试落地后，故意改坏两处实现——①删去 owner 退出时的复位（state 丢弃 / owner 置 None）、②BEGIN 失败后跳过补偿清位（owner/depth/state 残留）——确认对应测试**变红**；两处均变红即守卫有效，随后恢复实现复绿。防"测试因错误原因通过"（新断言从未经历过失败，可能是纸面守卫）
- [x] 2.1 `managers/bank_manager.py` 6 个手工块（:109、:153、:195、:281、:346、:414，含 bd 9jt 的 claim_interest / 逾期追杀——逾期追杀循环保持**顺序兄弟事务**语义：逐条独立事务、单条失败不影响其他）改为 `async with self.db.transaction() as txn:`；能前置的复查前置，锁内复查用 `txn.abort()`；调用点 `commit=False` 可暂留（第二阶段清理）。**每块转换前的裸 commit 闸门（2026-09-17 评审增补）**：grep 核验块体与可达 helper 无裸 `conn.commit()`/`in_transaction` 依赖——有则按转换规则同步删除；无法删除的登记 bd 并回退该块（防"迁移把 fake-atomicity 原样搬进 CM"）
- [x] 2.2 验证：bank 相关测试全绿 + 注入回归（§7.2/7.5 对应场景）通过

## 3. 其余块迁移（20 块）

- [x] 3.1 `managers/sect_manager.py` 8 块（:839、:1049、:1198、:1369、:1588、:1708、:1831、:2129，含 `complete_construction_task` 锁内复查复杂场景，abort 的主要用武之地）
- [x] 3.2 `core/storage_ring_manager.py` 3 块（:123、:169、:206——:123 是 `store_item` 的 flag-gated BEGIN，转换须保留 `external_transaction=True` 下的"三不"：不 BEGIN/不 commit/不 rollback，与 4.2 收编衔接）+ `managers/bounty_manager.py` 3 块（:331、:445、:599）
- [x] 3.3 `handlers/shop_handler.py`（生成器 handler，按 spike 0.2 结论处理，**删除块内失效的手工 except**）、`handlers/utils.py`（`_check_loan_status` :161，注意外层吞异常路径与内层 re-raise 的组合）、`handlers/player_handler.py`（**:533**，签到跨日重置块，2026-09-17 校正）、`managers/spirit_eye_manager.py`（:72，`claim_spirit_eye`）、`managers/impart_manager.py`（:225）、`core/gm_manager.py`（**:1187**，time skip 为**单事务**包住整个 `_TIME_SKIP_RULES` 循环，保持全有或全无语义；**块内裸 commit :1193 按转换规则随转换删除**）各 1 块
- [x] 3.4 每块转换后跑对应模块测试；§7.3 spy 测试（覆盖 bank/storage_ring/shop/utils）保持全绿——**注意其信号范围仅限这 4 个模块**，sect/bounty/spirit_eye/impart/gm/player_handler 各块以模块测试 + 人工核对为验证手段

## 4. 第二阶段：flag 退役

- [x] 4.1 确认 50 处穿参点（sect 15、bank 18、shop 3+4、utils 3、storage_ring 3、player_handler 2、impart 2）清零后，从 34 个定义移除 `commit`/`external_transaction` 参数（含 manager 层重导出）
- [x] 4.2 4 个自事务 helper 收编为 CM：`decrement_shop_item_stock`、`set_active_legacy_instance`、`learn_or_star_up`（后两者 BEGIN 条件一并改为 `depth == 0` 判定，替换其碰巧正确的 `in_transaction` 检查）、**`StorageRingManager.store_item`**（`core/storage_ring_manager.py:101`，第二个 `external_transaction` 持有者；~11 个独立调用方在事务外依赖其自 BEGIN 路径——equipment/storage_ring handlers、boss/adventure/spirit_farm/bounty/rift managers、gm_manager ×2、equipment_manager，收编后这些独立调用保持原语义）；**`increment_shop_item_stock` 不收编——它是死代码**（data/data_manager.py:336，全库无调用点，已 grep 核实），直接删除
- [x] 4.3 `tests/test_transaction_atomicity.py`：§7.1 kwarg 相关断言随 flag 退役移除/改写；**6 个 spy 测试**（§7.3 ×4 + §7.5 ×2）改写为 CM 级断言——**断 `conn._txn_depth` ownership 信号**（CM 内 >0、CM 外 == 0、仅 owner 层提交），不只断 `in_transaction`（裸 DML 后恒真，会"因错误的原因通过"）；不依赖 `kwargs.get("commit", True)` 默认值回读；合并进 1.3 的测试组去重
- [x] 4.4 全量质量门：`uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过

## 5. 文档与收尾

- [ ] 5.1 新建本地临时文件 `CONTEXT.md`（仓库根，中文，**已入 `.gitignore`、不进 commit、不登记 AGENTS.md 文档地图、本批 change 工作结束后不维护**——仅用于领域词汇对齐）：条目三字段格式——术语 / 一句话定义 / 权威代码符号（seam 位置 + 落地 change 链接）；登记 `unit-of-work`（`async with db.transaction():`，`conn._txn_depth` 所有权判据，owner-only 提交，seam 在 `DataBase`）与（预留）`BusyState` 占位条目（busy-state-owner 按此格式替换落实）
- [ ] 5.2 AGENTS.md §3 数据库操作规范替换纯手写 BEGIN 惯例为 CM 指针，并写入**转换规则**（任何手工提交点未来包进 CM 时必须同步删除体内裸 `conn.commit()`）与 CM 并发语义摘要（同任务 join / 跨任务串行化，指向 design D1.2）
- [ ] 5.3 用 `bd` 登记 spike 暴露的新发现（如有）；`openspec validate --changes add-transaction-unit-of-work` 通过；按块 conventional commit（试点/迁移/退役各自独立 commit）

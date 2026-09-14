# add-transaction-unit-of-work

## Why

"多步写是否在同一事务"目前是一条**调用约定**（写 helper 接 `commit: bool = True` / `external_transaction: bool = False`，调用方手动 `BEGIN IMMEDIATE` 并逐点放 rollback），而非可强制的接口。该约定已产生复发 bug 类：git 历史有 `fix-fake-atomic-transactions`、bd 9jt、bd 9yg 连续三处补丁，且养着 `tests/test_transaction_atomicity.py` 28 个测试函数作为机器检查——测试在为缺失的 seam 买单。

## What Changes

- `data/data_manager.py` 的 `DataBase` 新增 `async with db.transaction():` 单元工作上下文管理器：**所有权判据 = 连接对象上的深度计数器 `conn._txn_depth`**（实测 `in_transaction` 在 `isolation_level=""` 下 DML 后恒真，不可用——2026-09-14 评审复核拦下初版设计）。`depth == 0` 时 `BEGIN IMMEDIATE` 且该层为 owner（退出时 commit/rollback），否则 no-op join（**未发 BEGIN 的层退出时完全被动**：不 commit、不 rollback、只递减深度）；提供显式 `txn.abort()` 供锁内复查后放弃的场景。
- `connect()` 显式声明 `isolation_level=""`（钉住现状默认值，CM 单测含前提断言，默认值一变即红）。
- 写 helper（34 个定义：25 个叶子 helper 改 `depth == 0` 门控，7 个纯透传 wrapper 无需改动随叶子继承，2 个 BEGIN 门控 helper 随收编处理）改为依据**所有权**决定是否提交（连接自身已知道的事，替代 flag）；`commit`/`external_transaction` 参数标记为过渡兼容，第二阶段移除。
- 绞杀者迁移 26 个手工 `BEGIN IMMEDIATE` 块 / 50 处穿参点（sect 15、bank 18、shop 3+4、utils 3、storage_ring 3、player_handler 2、impart 2），按块推进（bank_manager 6 块试点 → 其余 20 块）；early-exit 模式按"能前置的复查前置，必须锁内复查的用 `txn.abort()`"收编。
- `tests/test_transaction_atomicity.py`：§7.2/7.4/7.5（与设计无关的原子性契约核心）全程守护；§7.1 kwarg 相关断言与 6 个 spy 测试随 flag 移除改写为 CM 级测试（断 `conn._txn_depth` ownership 信号）。
- **范围声明**：42 处无 flag 手工提交不属本 change 收敛范围——data 层 22 处经抽验为自包含单阶段；**manager/handler 层藏有 9 处两段式提交**（与 bd 9jt/9yg 同族的 fake-atomicity 隐患：8 处玩家向重复领取/双重扣费 + 1 处 GM cosmetic），已逐个分诊登记 bd，留待本 change 落地后以 CM 单模式修复。转换规则（未来包进 CM 必须删体内裸 commit）随 AGENTS.md §3 指针写入。
- **本地临时文件**：`CONTEXT.md` 为本地工作文件（已入 `.gitignore`、不进 commit、不登记 AGENTS.md 文档地图——仅在本批 change 工作期间用于领域词汇对齐）；`increment_shop_item_stock` 为死代码（全库无调用点），随本 change 删除而非收编。

**非目标**：不引入 SAVEPOINT 嵌套语义（无调用点需要）；**正常路径**不改任何对外可观察行为（**错误路径附带修复 `handle_buy` 写锁泄漏**——`except Exception` 捕不到 GeneratorExit 所致，spike 0.2 钉住，属修复非 scope 漂移）；不改 `isolation_level`（仅显式钉住现状默认值）；不做候选2（`BusyState`）——本 change 是其前置基建。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 — 事务原子性是工程约束，由测试钉住、无 spec 需求条目；本 change 不修改任何需求级行为。故 `.openspec.yaml` 设 `skip_specs: true`。）

## Impact

- **代码**：`data/data_manager.py`（+CM）、`data/database_extended.py`（25 个 helper）、`managers/`（sect、bank、bounty、impart、spirit_eye…）、`handlers/`（shop、utils、player_handler…）、`core/storage_ring_manager.py` —— ~12 文件，纯机械替换为主。
- **测试**：`tests/test_transaction_atomicity.py` 改写部分断言；新增 CM 级测试。
- **文档**：`CONTEXT.md` 为本地临时文件（不入库、不登记文档地图）；AGENTS.md §3 数据库操作规范补 CM 用法与转换规则指针。
- **依赖**：aiosqlite 0.22.1；`isolation_level=""` 的隐式 BEGIN 语义已实测钉住（评审复核：裸 DML 后 `in_transaction` 恒真、再 BEGIN 抛 OperationalError——初版以 `in_transaction` 为判据的设计因此作废，改用 `_txn_depth` 所有权计数器，见 design D0/D1）。
- **无**数据库迁移、无配置变更。

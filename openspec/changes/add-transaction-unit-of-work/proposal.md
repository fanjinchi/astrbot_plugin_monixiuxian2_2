# add-transaction-unit-of-work

## Why

"多步写是否在同一事务"目前是一条**调用约定**（写 helper 接 `commit: bool = True` / `external_transaction: bool = False`，调用方手动 `BEGIN IMMEDIATE` 并逐点放 rollback），而非可强制的接口。该约定已产生复发 bug 类：git 历史有 `fix-fake-atomic-transactions`、bd 9jt、bd 9yg 连续三处补丁，且养着 `tests/test_transaction_atomicity.py` 28 个测试函数作为机器检查——测试在为缺失的 seam 买单。

同时，插件是**单连接 + 生产代码全库无锁**（handlers/managers/core/data/main.py 无任何 asyncio.Lock/Semaphore/Condition），4 个后台定时任务（main.py:465-470：Boss 生成、贷款检查、灵眼生成、悬赏过期）与指令处理器并发跑在同一事件循环——两个事务块可能交错（`handle_buy` 事务体内 6 处 `yield` 即长窗口实证）。今天交错 = 后发者的 `BEGIN IMMEDIATE` 抛 `OperationalError` 且其 `except Exception: rollback` 误回滚先到者事务（响亮但破坏性）；CM 若按"depth>0 即 join"实现，交错会变成**静默共享事务**（后到者写入随先到者提交/回滚，后到者 `abort()` 甚至会取消先到者的事务）。并发语义是本 change 的显式设计目标（见 What Changes 第 1 条与 design D1.2）。

## What Changes

- `data/data_manager.py` 的 `DataBase` 新增 `async with db.transaction():` 单元工作上下文管理器：**同任务内所有权判据 = 深度计数器 `conn._txn_depth`**（实测 `in_transaction` 在 `isolation_level=""` 下 DML 后恒真，不可用——2026-09-14 评审复核拦下初版设计）+ **跨任务互斥判据 = 连接级 `asyncio.Condition` 与 `conn._txn_owner_task`**（2026-09-17 评审补：单连接并发下禁止跨任务静默 join，见 design D1.2）。`depth == 0` 且无他任务持有事务时 `BEGIN IMMEDIATE` 并成为 owner（退出时 commit/rollback）；同任务 `depth > 0` 时 no-op join（**未发 BEGIN 的层退出时完全被动**：不 commit、不 rollback、只递减深度）；**跨任务进入时锁内等待（`async with self._txn_free: await wait()`）直至 owner 释放后锁内认领、出锁再 BEGIN**（认领协议与失败补偿见 design D1.2；恢复今天 BEGIN IMMEDIATE 的串行化语义，同任务路径零 Condition 开销）；提供显式 `txn.abort()` 供锁内复查后放弃的场景。
- **并发行为变化（唯一新增的可观察行为变化，方向为修复）**：今天两个事务块交错 = 二重 BEGIN 的 `OperationalError` + 误回滚对方事务；新 CM = 自动串行化（后到者在 `__aenter__` 等待，等价今天"碰巧不撞车"时的行为）。跨任务等待不阻塞读请求（读无需写锁）。spike 0.5 探针钉住（含 3 任务认领竞争断言）。
- `connect()` 显式声明 `isolation_level=""`（钉住现状默认值，CM 单测含前提断言，默认值一变即红）。
- 写 helper（34 个定义：25 个叶子 helper 改 `depth == 0` 门控，7 个纯透传 wrapper 无需改动随叶子继承，2 个 BEGIN 门控 helper 随收编处理）改为依据**所有权**决定是否提交（连接自身已知道的事，替代 flag）；`commit`/`external_transaction` 参数标记为过渡兼容，第二阶段移除。
- 绞杀者迁移 26 个手工 `BEGIN IMMEDIATE` 块 / 50 处穿参点（sect 15、bank 18、shop 3+4、utils 3、storage_ring 3、player_handler 2、impart 2），按块推进（bank_manager 6 块试点 → 其余 20 块）；early-exit 模式按"能前置的复查前置，必须锁内复查的用 `txn.abort()`"收编。
- `tests/test_transaction_atomicity.py`：§7.2/7.4/7.5（与设计无关的原子性契约核心）全程守护；§7.1 kwarg 相关断言与 6 个 spy 测试随 flag 移除改写为 CM 级测试（断 `conn._txn_depth` ownership 信号）。
- **范围声明**：42 处无 flag 手工提交（data 层 25 + managers/handlers/core 层 17，经三轮补审按文件归属重算）不属本 change 收敛范围——data 层 25 处经抽验为自包含单阶段；**层 17 处中藏有 8 处两段式提交**（与 bd 9jt/9yg 同族的 fake-atomicity 隐患：崩溃在两段之间 = 重复领取/双重扣费），**另有 1 例四叶提交**（dual_cultivation `accept_request`:237——4 个独立自动提交点：`update_player` ×2 + `_set_last_dual_time` ×2，每个自带 commit；不在 42 之内、形态与两段式同族）——合计 9 例已逐个分诊登记 **bd `astrbot_plugin_monixiuxian2_2-2w1`（`-2w1`；模式清单：先提交后写）**，留待本 change 落地后以 CM 单模式修复。转换规则（未来包进 CM 必须删体内裸 commit）随 AGENTS.md §3 指针写入；迁移期每块转换前执行裸 commit grep 闸门（见 tasks 2.1）。
- **本地临时文件**：`CONTEXT.md` 为本地工作文件（已入 `.gitignore`、不进 commit、不登记 AGENTS.md 文档地图——仅在本批 change 工作期间用于领域词汇对齐）；`increment_shop_item_stock` 为死代码（全库无调用点），随本 change 删除而非收编。

**非目标**：不引入 SAVEPOINT 嵌套语义（无调用点需要）；**正常路径**不改任何对外可观察行为（**错误路径附带修复 `handle_buy` 写锁泄漏**——`except Exception` 捕不到 GeneratorExit 所致，spike 0.2 钉住；**并发冲突路径附带修复**——今天的二重 BEGIN 崩溃/误回滚改为等待串行化，spike 0.5 钉住——均属修复非 scope 漂移）；不改 `isolation_level`（仅显式钉住现状默认值）；不做跨进程/跨连接事务协调（单连接插件场景不需要）；不引入/不切换 pysqlite3-binary（保持标准库 sqlite3 驱动）；不做候选2（`BusyState`）——本 change 是其前置基建。

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

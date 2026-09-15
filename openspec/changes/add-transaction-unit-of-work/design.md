# Design — add-transaction-unit-of-work

## Context

`DataBase`（data/data_manager.py:50）与 `DatabaseExtended`（data/database_extended.py:13）是共享一个连接的兄弟类（组合：`DataBase` 持有 `self.conn`，构造 `self.ext = DatabaseExtended(self.conn)`）。连接经 `aiosqlite.connect(self.db_path)` 创建，**未设 `isolation_level`** → sqlite3 旧版默认 `""`：DML 前隐式 BEGIN，任何 `conn.commit()` 结束事务并释放写锁——这是归档 change `2026-09-01-fix-fake-atomic-transactions` 的物理根源。

约定现状两种 flag 形态：`commit: bool = True`（**34 个定义**：`data_manager.py` 2、`database_extended.py` 25、`core/pill_manager.py` 1、`managers/bank_manager.py` 1、`managers/impart_manager.py` 4、`handlers/shop_handler.py` 1，commit=False 意为"外层拥有提交权"）与 `external_transaction: bool = False`（仅 2 个自事务 helper：自己 BEGIN 或完全跳过）。其中 **2 个 helper（`set_active_legacy_instance` :446、`learn_or_star_up` :793）用 commit 门控自己的 `BEGIN IMMEDIATE`** 而非 `conn.commit()`——D2 变换不覆盖它们，随第二阶段收编。另有 2 个 helper 自事务无 flag（`decrement_shop_item_stock` 有 flag、`increment_shop_item_stock` 无条件 BEGIN——**后者是死代码**，data/data_manager.py:336 全库无调用点，二轮补审⑥核实，随 4.2 删除而非收编）。调用盘：50 处穿参点 + **26 个**手工 `BEGIN IMMEDIATE` 块（sect 8、bank 6、storage_ring 3、bounty 3、shop 1、utils 1、player_handler 1、spirit_eye 1、impart 1、gm 1）。

**已实测的机制事实（2026-09-14 复核，aiosqlite 0.22.1 / Python 3.12 / `isolation_level=""`）**：裸 DML 会带出隐式 BEGIN，**DML 之后 `conn.in_transaction` 恒为 True**（裸 INSERT 后 True；此时再发 `BEGIN IMMEDIATE` 抛 `OperationalError: cannot start a transaction within a transaction`）。因此 `in_transaction` **不能**作为"我是否在事务里"的判据——"先执行 DML 再判 in_transaction"的 helper 门控会让独立调用永不提交（本 change 初版 D2 即因此不成立，评审实测拦下）。可用判据只有**所有权**：我们是否发过 BEGIN。`set_active_legacy_instance`/`learn_or_star_up` 的 BEGIN 判定碰巧对，正因为检查点在 DML 之前。另：`in_transaction` 在连接关闭时抛 `ValueError`（`_conn` 守卫）。

## Goals / Non-Goals

**Goals:**
- 事务边界跟着缩进走：`async with db.transaction():` 一眼可见，"提前 commit"在构造上不可能。
- 行为与现状等价：原子性语义（块内任一步失败全回滚）不变；**正常路径**对外可观察行为零变化（**错误路径附带修复 `handle_buy` 写锁泄漏**，见 Risks 第一条——`except Exception` 捕不到 GeneratorExit，CM 的 `__aexit__` 顺手修复，spike 0.2 钉住）。
- 绞杀者迁移：flag 与 CM 共存期内全部现有测试保持通过，作为逐块迁移的安全网。

**Non-Goals:**
- SAVEPOINT / 内层独立回滚（无调用点需要；逾期贷款的逐条容错用顺序兄弟事务，no-op join 天然支持）。
- 改连接的 `isolation_level` / autocommit 配置（**例外**：`connect()` 显式声明 `isolation_level=""` 属于"钉住现状默认值"而非改配置，见 D0）。
- 候选2（BusyState owner）——本 change 只做基建，owner 是其首个真实消费者（后续 change）。

## Decisions

> **行号重锚（2026-09-16）**：本 change 引用 hygiene-cleanup-batch 触碰过的文件行号已对照当前代码修正（pill_manager wrapper 654→628、test_user_busy_upsert 27→31、test_migration 433→437/:475）；其余引用（data 层 helper、26 块、storage_ring、gm、sect、bank）经核未漂移。实施时仍按任务 0.1 复核。


**D0 · 物理前提钉住（评审第 3 问决策）。**
`connect()` 显式声明 `isolation_level=""`（现状默认值，显式化防静默变形——Python 3.12 引入 `autocommit` 属性、aiosqlite 换默认值都会改变隐式 BEGIN 行为）。钉住它的理由有两条：① CM 与 helper 门控的全部推理建立在 `""` 的隐式 BEGIN 语义上；② **42 处无 flag 手工提交的 data 层叶子操作**（create_player、delete_player_cascade、create_sect 等多语句 CRUD）的独立调用原子性靠隐式事务天然提供——改 autocommit 会让它们变成逐语句提交（这正是方案 C 被否决的实质代价）。加一行注释说明这两重依赖；CM 单测加**前提断言**（默认值一变即红，不静默变形）。

**D1 · CM 归属 `DataBase`（data/data_manager.py），签名 `async with db.transaction() as txn:`，句柄暴露 `abort()`；所有权判据 = 深度计数器（评审第 1/2 问决策 = 方案 A）。**
`DataBase` 拥有 `self.conn`，manager 层处处持有 `self.db`。**判据不用 `conn.in_transaction`（DML 后恒真，见 Context 实测），用挂在连接对象上的深度计数器 `conn._txn_depth`**（`DataBase` 与 `DatabaseExtended` 共享同一连接对象 data_manager.py:62，天然同见；`connect()` 初始化为 0、重连重建——插件单连接完全自有，一处私有属性可控；选 A 而非注入 `DatabaseExtended(conn, state)` 的理由：测试构造点零改动）。**事务状态对象（评审补问①）**：owner 入口创建一次性 `TxnState`（持有 abort 标记），CM 句柄持有其引用，内层句柄共享同一 state——`abort()` 置标记经 state 传至 owner 层；owner `__aexit__` 整体丢弃 state，**标记与事务严格同生命周期**，不存在"深度归零、标记残留"窗口。**存储口径钉死（三轮补审 · 存储选型 (a)）**：连接上两个属性各司其职——`conn._txn_depth: int`（门控用，D2/1.3/4.3 的断言读它）+ `conn._txn_state: TxnState | None`（只装 abort 标记，owner 退出置 None；内层 CM 经 `conn._txn_state` 发现共享 state，"内层从哪发现 state"由此有唯一答案）。不选 (b)（depth 并入 state）的理由：门控读 int 比读对象再取字段更直白，且 1.3/4.3 已写好的断言写法不用跟着改。语义：entry 时 **`await conn.execute("BEGIN IMMEDIATE")` 成功返回后同步置 `depth = 1`、`state = TxnState()`，该层为 owner**（评审补问②顺序约束：BEGIN 与置位之间无 await 点，不可能失衡——先置位再 BEGIN 会在 BEGIN 失败时留下"有主无事务"，所有 helper 永不提交）；若 entry 时 `depth > 0` 则 `depth += 1`、句柄共享既有 `state`（no-op join 内层）。退出时 `depth` 递减与 `state` 置 None 用 finally 语义保证（二轮补审 · finally 语义：owner 层 commit/rollback 自身抛异常——如磁盘错误——不留下残留状态），**仅 owner 层做提交/回滚动作**：干净且无 abort → **try: commit → except: best-effort `conn.rollback()` → raise**（三轮补审 · 提交失败回滚：commit 失败时事务可能仍开着，先回滚再抛，否则 depth 已归零、后续 helper 会把别人的开着的事务提交掉）；abort 或异常 → rollback 后（按异常路径）re-raise。未发 BEGIN 的层退出时**完全被动**——不 commit、不 rollback、只递减深度、异常照常传播（评审第 2 问钉死：否则就是把"提前提交"bug 搬进 CM 层）。**`__aenter__` 异常路径 best-effort rollback**（BEGIN 失败或协程在 await 点被取消：sqlite3 的 `rollback()` 无事务时是安全 no-op；BEGIN 已下发而被取消时借此关闭孤儿事务）；协程在 BEGIN 的 await 点被取消导致 `__aexit__` 不被调用的残余窗口写入 Risks，有意识接受。**`__aexit__` 按 `exc_type is not None` 分支判定异常路径（不得 `except Exception`）**——`CancelledError`/`GeneratorExit` 是 BaseException，`except Exception` 实现会在取消/生成器关闭时泄漏未关闭的事务。**嵌套 abort 传播**：任一层（含 no-op join 内层）调用 `txn.abort()` 都经共享 state 把标记传给 owner 层。**abort 契约（对外承诺，下游 change 依赖）**：`txn.abort()` 只置标记不抛异常（幂等）；标记后块内 clean exit（return）→ owner 层走 rollback 且不 re-raise（调用方拿失败文案返回）；abort 与异常并存时按异常路径 rollback + re-raise。**helper 门控的 fail-open 是设计而非防御（评审补问③）**：`getattr(self.conn, "_txn_depth", 0)` 默认 0 = 退回旧提交语义——3 个测试用裸 conn 构造 `DatabaseExtended`（tests/test_user_busy_upsert.py:31、tests/test_impart_manager.py:146、tests/test_migration.py:437/:475）依赖此行为，docstring 明示。**过渡约束（文档化，不做运行时检查）**：计数器看不见 raw BEGIN，CM 不得进入 raw BEGIN 块内部——AST 扫描已验证 26 个生产块无此嵌套、§7.1 测试 hand-BEGIN 后只调 helper 不进 CM。

**D1.1 · 42 处无 flag 手工提交的处置：out-of-scope 已知集 + 转换规则（评审补问④；两段式子集经分诊修正；分列数字经三轮补审按文件归属重算）。**
实测 42 处裸 `conn.execute` + `conn.commit()` 按文件归属分两类：**data 层 25 处**（`database_extended.py` 22 + `data_manager.py` 3：create_player、delete_player、update_shop_data）——经抽验 10 个确认自包含单阶段（delete_player_cascade 的 17 条语句共用一个 commit），声明成立；**managers/handlers/core 层 17 处**。**17 处中藏有 8 处两段式提交**（先提交、后继续写、再提交）——与 bd 9jt/9yg 同族的 fake-atomicity 隐患：spirit_farm create_farm:79 / harvest:149 / upgrade_farm:241（扣费/发奖后推进状态 → 重复扣费/重复收获）、spirit_eye collect_spirit_eye:124（发修为后推进时间 → 重复领取）、blessed_land purchase:72 / upgrade:127 / collect_income:174、gm cmd_clear_all_cooldowns:1207（幂等可重跑，cosmetic）。**另发现第 9 例不在 42 之内**：`dual_cultivation_manager.accept_request:237` 是**双叶提交**（两次 gated-leaf `update_player` :286/:287 各自独立提交 + `_set_last_dual_time` ×2）——函数体内无裸 `conn.commit()`，被"42 处子集"口径漏掉、靠人读才发现；形态与两段式相同（先发放后记冷却/删请求 → 重复双修刷修为），一并入 bd 清单。**这也说明 bd 清单的口径是"模式清单（先提交后写）"而非"42 处的子集"**——将来扫全库找同类须按模式扫，否则会漏掉 accept_request 这类。**处置**：本 change 不收敛它们（保持范围），已逐个分诊登记 **bd `-2w1`（两段式提交清单）**——8+1 同形，是本 change 落地后用 CM 包裹 + 删体内裸 commit 即可单模式修复的首选批次；bounty complete_bounty:441 的物品掉落事务外 best-effort 属声明过的有意设计，随 bd 挂 low。**转换规则（防未来复刻 bug）**：任何一处未来被包进 `async with db.transaction()` 时，必须**同步删除其体内裸 `conn.commit()`**——裸 commit 在 CM 内就是提前提交 bug 本体；此规则随 AGENTS.md §3 的 CM 指针一并写入。

**D2 · helper 先行切 `depth == 0` 门控，block 迁移随后。**
**25 个叶子 helper**（`data_manager.py` 2、`database_extended.py` 23）体内有 `if commit: await self.conn.commit()`，改为 `if commit and getattr(self.conn, "_txn_depth", 0) == 0: commit`——判的是**所有权**（我们是否发过 BEGIN）而非 autocommit 状态。已实测验证：§7.1 那 9 个测试不改也过（hand-BEGIN + `commit=False` 调用本就不该提交；默认 commit 的独立调用 depth==0 正常提交）。**7 个纯透传 wrapper**（`core/pill_manager.py:628`、`managers/bank_manager.py:458`、`handlers/shop_handler.py:345`、`managers/impart_manager.py` ×4）无本地提交门控，第一阶段零改动，随叶子行为自动继承。**例外**：`set_active_legacy_instance` / `learn_or_star_up` 的 commit 门控的是 BEGIN IMMEDIATE（:460-461、:830-831，检查点在 DML 之前所以碰巧正确），本阶段不动，随 4.2 收编时把 BEGIN 条件一并改为 `depth == 0` 判定。已核验：全部 26 个块内调用均为 `commit=False`/`external_transaction=True` 或裸 SQL，生产代码不存在"事务内 commit=True 调用"——D2 不破坏任何现有 §7.1/§7.3 测试。这一步行为保持，且使之后每个块的转换"进 CM 即安全"，调用点的 `commit=False` 可留待第二阶段一并清理。

**D3 · early-exit 收编策略（Q2 决策 = c 混合）。**
现状 8+ 处 sect 块与若干 bank 块是"BEGIN → 锁内复查 → 显式 rollback → return 失败文案"。能前置的复查挪到 CM 之前（多数 bank 块成立）；必须锁内复查的（sect `complete_construction_task` 的锁内 re-read 正是其 BEGIN 目的）用 `txn.abort()`。commit-on-clean-exit + abort 标记实现，不改 return 文案。

**D4 · 迁移顺序：bank 试点 → 其余模块逐块 → 第二阶段删 flag。**
bank_manager 6 块几乎同构（含 bd 9jt 刚修过的 claim_interest / 逾期追杀，回归价值最高）作试点；sect_manager 8 块（含锁内复查最复杂场景）随后；其余按模块清。每块转换 = "一个事务块 + 其调用点"，不是整个文件。第二阶段：50 处穿参清零后，从 34 个定义移除 flag（其中 2 个 BEGIN 门控 helper 随 4.2 收编），自事务 helper 收编为 CM，§7.1 kwarg 断言与 6 个 spy 测试改写为 CM 级测试。

**D5 · 测试策略：§7.2/7.4/7.5 全程不动；spy 断言断 ownership 信号（评审第 4 问决策）。**
这三组（中途注入失败全回滚、D5 stale-player 回归、bd 9jt 贷款原子性）与设计无关，是原子性契约的核心守护，迁移期原样运行。flag 退役时仅动 §7.1/§7.3——**6 个 spy 测试改写断 `conn._txn_depth` 信号**（CM 内 >0、CM 外 == 0、仅 owner 层提交），不只断 `in_transaction`：后者在裸 DML 后恒真，区分不了"在 CM 里"和"刚做过一条裸 DML"，会"因为错误的原因通过"。

## Risks / Trade-offs

- [生成器 handler `handle_buy` 在事务体内 yield，`except Exception`（:311）捕不到 GeneratorExit——**今天是预存的写锁泄漏**（生成器在任一 yield 点被关闭则 BEGIN 的写锁残留），CM 的 `__aexit__` 会**顺带修复**它（错误路径行为变化，属修复非漂移——已写入 Goals）] → 转换时**删除块内现已失效的手工 `except Exception: rollback`**（勿与 CM 嵌套造成双 rollback）；spike 0.2 显式断言修复生效且无 "cannot rollback - no transaction" 告警。
- [`_check_loan_status` 外层 except 吞异常返回 None，与 CM 的 rollback 叠加] → 内层 re-raise → CM rollback → 外层吞异常，组合正确；sqlite rollback 无事务时的告警行为未验证，spike 0.2 加"无活动事务时 rollback"探针确认无告警。
- [abort 语义误用：调用方 abort 后继续写] → docstring 明示 abort 后块内写入仍会随事务回滚；CM 内不做运行时禁用（YAGNI）。
- [`_txn_depth` 随重连丢失/残留] → `connect()` 统一初始化为 0（含 `ensure_connection` 重建路径），属性只在连接对象上由本插件读写；连接关闭后 getattr 读到的是代理对象上的初始化值，不触及已关闭的底层连接。
- [CM 误入 raw BEGIN 块内部 → 重复 BEGIN 抛 OperationalError] → 过渡约束已文档化（D1）：AST 扫描证明 26 个生产块无此嵌套；转换期每个块的迁移本身就是消除 raw BEGIN 的过程。
- [协程在 `BEGIN` 的 await 点被取消 → BEGIN 可能已下发而 depth 未置，`__aexit__` 不会被调用] → `__aenter__` 异常路径 best-effort rollback 已覆盖（D1）；BEGIN 下发前的取消则无副作用；残余窗口（worker 线程已执行 BEGIN、协程已取消、rollback 亦被取消）**有意识接受**——插件场景（单连接、任务取消罕见）不做 shield 重试。
- [迁移中途信号模糊：新旧两套检查并存] → 接受；§7.3 spy 测试在迁移完成前持续给出"哪块还没转"的信号，这正是保留它们到第二阶段的理由。
- [某未转换块依赖 helper "在事务内也提交"的隐式行为] → 不存在：事务内 commit 即 bug 本体，D2 反而修复之；若注入测试暴露意外依赖，按 bug 处理并登记 bd。

## Migration Plan

无部署步骤，随插件重载生效；无 DB/配置变更。回滚 = revert 对应 commit（按块提交，块间可独立回滚）。

## Open Questions

- spike（任务 0）回答，不影响本设计：`GeneratorExit` 进 `handle_buy` 的 rollback 行为（含写锁泄漏修复断言）与无活动事务时 rollback 的告警探针；`txn.abort()` 原型在 deposit 与一个 sect 块上的手感（按 D1 abort 契约实现）。注意：初版"in_transaction 跨线程读压力验证"问题已随判据改为 `_txn_depth`（纯 Python 属性、单事件循环内读写）而作废——Context 中已留实测记录。
- 非目标备注：`data/migration.py:555,590,615` 迁移期 plain `BEGIN` 不在本 change 范围。

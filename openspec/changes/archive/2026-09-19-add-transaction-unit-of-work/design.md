# Design — add-transaction-unit-of-work

## Context

`DataBase`（data/data_manager.py:50）与 `DatabaseExtended`（data/database_extended.py:13）是共享一个连接的兄弟类（组合：`DataBase` 持有 `self.conn`，构造 `self.ext = DatabaseExtended(self.conn)`）。连接经 `aiosqlite.connect(self.db_path)` 创建，**未设 `isolation_level`** → sqlite3 旧版默认 `""`：DML 前隐式 BEGIN，任何 `conn.commit()` 结束事务并释放写锁——这是归档 change `2026-09-01-fix-fake-atomic-transactions` 的物理根源。

约定现状两种 flag 形态：`commit: bool = True`（**34 个定义**：`data_manager.py` 2、`database_extended.py` 25、`core/pill_manager.py` 1、`managers/bank_manager.py` 1、`managers/impart_manager.py` 4、`handlers/shop_handler.py` 1，commit=False 意为"外层拥有提交权"）与 `external_transaction: bool = False`（仅 2 个自事务 helper：自己 BEGIN 或完全跳过）。其中 **2 个 helper（`set_active_legacy_instance` :446、`learn_or_star_up` :793）用 commit 门控自己的 `BEGIN IMMEDIATE`** 而非 `conn.commit()`——D2 变换不覆盖它们，随第二阶段收编。另有 2 个 helper 自事务无 flag（`decrement_shop_item_stock` 有 flag、`increment_shop_item_stock` 无条件 BEGIN——**后者是死代码**，data/data_manager.py:336 全库无调用点，二轮补审⑥核实，随 4.2 删除而非收编）。调用盘：50 处穿参点 + **26 个**手工 `BEGIN IMMEDIATE` 块（sect 8、bank 6、storage_ring 3、bounty 3、shop 1、utils 1、player_handler 1、spirit_eye 1、impart 1、gm 1）。**对账：26 手工块 + 2 个 BEGIN 门控 helper（`set_active_legacy_instance` :446、`learn_or_star_up` :793）+ 1 个 external_transaction 门控 helper（`store_item` :101，BEGIN :123）+ 1 处死代码（`increment_shop_item_stock` :336）＝ 30 处 BEGIN IMMEDIATE 执行点**。

**已实测的机制事实（2026-09-14 复核，aiosqlite 0.22.1 / Python 3.12 / `isolation_level=""`）**：裸 DML 会带出隐式 BEGIN，**DML 之后 `conn.in_transaction` 恒为 True**（裸 INSERT 后 True；此时再发 `BEGIN IMMEDIATE` 抛 `OperationalError: cannot start a transaction within a transaction`）。因此 `in_transaction` **不能**作为"我是否在事务里"的判据——"先执行 DML 再判 in_transaction"的 helper 门控会让独立调用永不提交（本 change 初版 D2 即因此不成立，评审实测拦下）。可用判据只有**所有权**：我们是否发过 BEGIN。`set_active_legacy_instance`/`learn_or_star_up` 的 BEGIN 判定碰巧对，正因为检查点在 DML 之前。另：`in_transaction` 在连接关闭时抛 `ValueError`（`_conn` 守卫）。

**并发现状（2026-09-17 复核）**：单连接（data_manager.py:62）+ 生产代码全库无锁（grep：handlers/managers/core/data/main.py 无 asyncio.Lock/Semaphore/Condition），4 个后台定时任务（main.py:465-470：Boss 生成、贷款检查、灵眼生成、悬赏过期）与指令处理器并发跑在同一事件循环。两个手工 BEGIN 块交错时，后发者抛 `OperationalError: cannot start a transaction within a transaction`，且其后的 `except Exception: rollback` 会误回滚先到者的事务；`handlers/shop_handler.py` `handle_buy` 在事务体内有 6 处 `yield`（生成器 handler 逐条吐消息），挂起时写锁跨多个消息循环保持——并发冲突非理论（详见 D1.2）。

## Goals / Non-Goals

**Goals:**
- 事务边界跟着缩进走：`async with db.transaction():` 一眼可见，"提前 commit"在构造上不可能。
- 行为与现状等价：原子性语义（块内任一步失败全回滚）不变；**正常路径**对外可观察行为零变化（**错误路径附带修复 `handle_buy` 写锁泄漏**，见 Risks 第一条——`except Exception` 捕不到 GeneratorExit，CM 的 `__aexit__` 顺手修复，spike 0.2 钉住）。
- 绞杀者迁移：flag 与 CM 共存期内全部现有测试保持通过，作为逐块迁移的安全网。
- 并发语义不劣化：跨任务交错时后到者串行化等待（等价今天"没撞车"路径），**禁止静默共享事务**（D1.2）。

**Non-Goals:**
- SAVEPOINT / 内层独立回滚（无调用点需要；逾期贷款的逐条容错用顺序兄弟事务，no-op join 天然支持）。
- 改连接的 `isolation_level` / autocommit 配置（**例外**：`connect()` 显式声明 `isolation_level=""` 属于"钉住现状默认值"而非改配置，见 D0）。
- 候选2（BusyState owner）——本 change 只做基建，owner 是其首个真实消费者（后续 change）。
- 跨进程/跨连接事务协调（单连接插件场景不需要）。

## Decisions

> **行号重锚（2026-09-16）**：本 change 引用 hygiene-cleanup-batch 触碰过的文件行号已对照当前代码修正（pill_manager wrapper 654→628、test_user_busy_upsert 27→31、test_migration 433→437/:475）；其余引用（data 层 helper、26 块、storage_ring、gm、sect、bank）经核未漂移。实施时仍按任务 0.1 复核。**二次校正（2026-09-17 评审）**：`handlers/player_handler.py` 签到跨日重置块在 :533（tasks 原写 :540）；`core/gm_manager.py` time-skip 块 :1187 内另含裸 commit :1193（随 3.3 转换删除，与 :1249/:1260 的两段式提交区分——后者在 bd `astrbot_plugin_monixiuxian2_2-2w1`（`-2w1`））。


**D0 · 物理前提钉住（评审第 3 问决策）。**
`connect()` 显式声明 `isolation_level=""`（现状默认值，显式化防静默变形——Python 3.12 引入 `autocommit` 属性、aiosqlite 换默认值都会改变隐式 BEGIN 行为）。钉住它的理由有两条：① CM 与 helper 门控的全部推理建立在 `""` 的隐式 BEGIN 语义上；② **42 处无 flag 手工提交的 data 层叶子操作**（create_player、delete_player_cascade、create_sect 等多语句 CRUD）的独立调用原子性靠隐式事务天然提供——改 autocommit 会让它们变成逐语句提交（这正是方案 C 被否决的实质代价）。加一行注释说明这两重依赖；CM 单测加**前提断言**（默认值一变即红，不静默变形）。

**D1 · CM 归属 `DataBase`（data/data_manager.py），签名 `async with db.transaction() as txn:`，句柄暴露 `abort()`；所有权判据 = 深度计数器（评审第 1/2 问决策 = 方案 A）。**
`DataBase` 拥有 `self.conn`，manager 层处处持有 `self.db`。**判据不用 `conn.in_transaction`（DML 后恒真，见 Context 实测），用挂在连接对象上的深度计数器 `conn._txn_depth`**（`DataBase` 与 `DatabaseExtended` 共享同一连接对象 data_manager.py:62，天然同见；`connect()` 初始化为 0、重连重建——插件单连接完全自有，一处私有属性可控；选 A 而非注入 `DatabaseExtended(conn, state)` 的理由：测试构造点零改动）。**事务状态对象（评审补问①）**：owner 入口创建一次性 `TxnState`（持有 abort 标记），CM 句柄持有其引用，内层句柄共享同一 state——`abort()` 置标记经 state 传至 owner 层；owner `__aexit__` 整体丢弃 state，**标记与事务严格同生命周期**，不存在"深度归零、标记残留"窗口。**存储口径钉死（三轮补审 · 存储选型 (a)）**：连接上两个属性各司其职——`conn._txn_depth: int`（门控用，D2/1.3/4.3 的断言读它）+ `conn._txn_state: TxnState | None`（只装 abort 标记，owner 退出置 None；内层 CM 经 `conn._txn_state` 发现共享 state，"内层从哪发现 state"由此有唯一答案）。不选 (b)（depth 并入 state）的理由：门控读 int 比读对象再取字段更直白，且 1.3/4.3 已写好的断言写法不用跟着改。语义：entry 的认领与 BEGIN 顺序统一由 **D1.2 锁内认领协议**规定（锁内置 `_txn_owner_task = current`/`depth = 1`/`state = TxnState()` → 出锁 → `await conn.execute("BEGIN IMMEDIATE")`；BEGIN 失败走补偿清位，见 D1.2——原「先 BEGIN 后置位、两者间无 await 点」的顺序约束因两任务并发 BEGIN 竞态（评审 F1）作废，『有主无事务』不可能持续）；若 entry 时 `depth > 0` 则 `depth += 1`、句柄共享既有 `state`（no-op join 内层）。退出时 `depth` 递减、`_txn_owner_task` 置 None、`state` 置 None 用 finally 语义保证（二轮补审 · finally 语义：owner 层 commit/rollback 自身抛异常——如磁盘错误——不留下残留状态；复位顺序 depth → owner → state，随后锁内 `notify_all()`，见 D1.2 F2），**仅 owner 层做提交/回滚动作**：干净且无 abort → **try: commit → except: best-effort `conn.rollback()` → raise**（三轮补审 · 提交失败回滚：commit 失败时事务可能仍开着，先回滚再抛，否则 depth 已归零、后续 helper 会把别人的开着的事务提交掉）；abort 或异常 → rollback 后（按异常路径）re-raise。未发 BEGIN 的层退出时**完全被动**——不 commit、不 rollback、只递减深度、异常照常传播（评审第 2 问钉死：否则就是把"提前提交"bug 搬进 CM 层）。**`__aenter__` 异常路径 = D1.2 补偿子句**（BEGIN 失败或协程在 BEGIN await 点被取消：锁内清位 `_txn_owner_task = None`/`depth = 0`/`state = None` + `notify_all()` + best-effort rollback + re-raise；sqlite3 的 `rollback()` 无事务时是安全 no-op；BEGIN 已下发而被取消时借此关闭孤儿事务）；补偿 rollback 亦被取消的残余窗口写入 Risks，有意识接受。**`__aexit__` 按 `exc_type is not None` 分支判定异常路径（不得 `except Exception`）**——`CancelledError`/`GeneratorExit` 是 BaseException，`except Exception` 实现会在取消/生成器关闭时泄漏未关闭的事务。**嵌套 abort 传播**：任一层（含 no-op join 内层）调用 `txn.abort()` 都经共享 state 把标记传给 owner 层。**abort 契约（对外承诺，下游 change 依赖）**：`txn.abort()` 只置标记不抛异常（幂等）；标记后块内 clean exit（return）→ owner 层走 rollback 且不 re-raise（调用方拿失败文案返回）；abort 与异常并存时按异常路径 rollback + re-raise。**helper 门控的 fail-open 是设计而非防御（评审补问③）**：`getattr(self.conn, "_txn_depth", 0)` 默认 0 = 退回旧提交语义——3 个测试用裸 conn 构造 `DatabaseExtended`（tests/test_user_busy_upsert.py:31、tests/test_impart_manager.py:146、tests/test_migration.py:437/:475）依赖此行为，docstring 明示。**过渡约束（文档化，不做运行时检查）**：计数器看不见 raw BEGIN，CM 不得进入 raw BEGIN 块内部——AST 扫描已验证 26 个生产块无此嵌套、§7.1 测试 hand-BEGIN 后只调 helper 不进 CM。

**D1.1 · 42 处无 flag 手工提交的处置：out-of-scope 已知集 + 转换规则（评审补问④；两段式子集经分诊修正；分列数字经三轮补审按文件归属重算）。**
实测 42 处裸 `conn.execute` + `conn.commit()` 按文件归属分两类：**data 层 25 处**（`database_extended.py` 22 + `data_manager.py` 3：create_player、delete_player、update_shop_data）——经抽验 10 个确认自包含单阶段（delete_player_cascade 的 17 条语句共用一个 commit），声明成立；**managers/handlers/core 层 17 处**。**17 处中藏有 8 处两段式提交**（先提交、后继续写、再提交）——与 bd 9jt/9yg 同族的 fake-atomicity 隐患：spirit_farm create_farm:79 / harvest:149 / upgrade_farm:241（扣费/发奖后推进状态 → 重复扣费/重复收获）、spirit_eye collect_spirit_eye:124（发修为后推进时间 → 重复领取）、blessed_land purchase:72 / upgrade:127 / collect_income:174、gm cmd_clear_all_cooldowns:1207（幂等可重跑，cosmetic）。**另发现第 9 例不在 42 之内**：`dual_cultivation_manager.accept_request:237` 是**四叶提交**（4 个独立自动提交点：`update_player` :286/:287 ×2 + `_set_last_dual_time` :290/:291 ×2，每个自带 commit——实际是四次"先发放后记冷却"的两段式叠加）——函数体内无裸 `conn.commit()`，被"42 处子集"口径漏掉、靠人读才发现；形态与两段式相同（先发放后记冷却/删请求 → 重复双修刷修为），一并入 bd 清单。**这也说明 bd 清单的口径是"模式清单（先提交后写）"而非"42 处的子集"**——将来扫全库找同类须按模式扫，否则会漏掉 accept_request 这类。**处置**：本 change 不收敛它们（保持范围），已逐个分诊登记 **bd `astrbot_plugin_monixiuxian2_2-2w1`（`-2w1`；两段式提交清单）**——8+1 同形，是本 change 落地后用 CM 包裹 + 删体内裸 commit 即可单模式修复的首选批次；bounty complete_bounty:441 的物品掉落事务外 best-effort 属声明过的有意设计，随 bd 挂 low。**转换规则（防未来复刻 bug）**：任何一处未来被包进 `async with db.transaction()` 时，必须**同步删除其体内裸 `conn.commit()`**——裸 commit 在 CM 内就是提前提交 bug 本体；此规则随 AGENTS.md §3 的 CM 指针一并写入。

**D1.2 · 跨任务互斥：事务所有权绑定任务 + 连接级 Condition（2026-09-17 评审新增，采纳推荐方案 1；2026-09-18 二轮修正：认领协议改为「锁内认领 + 失败补偿」，闭合评审 F1 认领竞态 / F2 退出侧漏清 owner）。**
单连接 + 全库无锁 + 定时任务与指令并发（Context"并发现状"）；两个事务块交错时，今天 = 二重 BEGIN 抛 OperationalError + 后到者 `except Exception: rollback` 误回滚先到者事务（响亮但破坏性）；纯 depth 判据的 CM 则会把交错变成**静默共享事务**——后到者 join 先到者：先到者 commit 时后到者的写入被一起提交，先到者 abort/异常时后到者已"成功"的写入被静默回滚；且 `TxnState` 是连接级共享对象，后到者的 `txn.abort()` 会 abort 先到者的事务。不可接受，故增加任务归属：
- **连接新属性**：`conn._txn_owner_task: asyncio.Task | None`（谁发起了事务；`connect()` 初始化 None、重连重建）+ `DataBase._txn_free = asyncio.Condition()`（跨任务等待/唤醒用；同任务路径不进 Condition，零开销）。
- **`__aenter__` 认领协议（锁内认领 + 失败补偿）**：
  1. **同任务快速路径**：入口先同步判断 `_txn_owner_task is asyncio.current_task()` → 真则 `depth += 1`、共享既有 `state`，直接返回（no-op join），不进 Condition——「join 零开销」承诺在此保持。
  2. **认领路径**：否则 `async with self._txn_free:` → `while _txn_owner_task is not None: await self._txn_free.wait()`（wait 自动释放/重取锁）→ 循环退出后在**锁内**置 `_txn_owner_task = current_task()`、`depth = 1`、`_txn_state = TxnState()` → 出锁 → 再 `await conn.execute("BEGIN IMMEDIATE")`。任务身份用 `is` 比较，不用相等。
  3. **BEGIN 失败补偿**：BEGIN 抛错、或认领后本任务在 BEGIN await 点被取消（CancelledError 落在此 await 上）→ 重进 `async with self._txn_free:` → `_txn_owner_task = None`、`depth = 0`、`_txn_state = None` → `notify_all()` → best-effort rollback（BEGIN 未生效时 rollback 是安全 no-op，其报错吞掉）→ re-raise。
  4. **补偿子句解答 D1 原「先置位再 BEGIN」反对理由**：D1 曾以「先置位再 BEGIN 会在 BEGIN 失败时留下『有主无事务』（owner 占位而事务未开，所有 helper 永不提交）」反对先置位。锁内认领协议下认领与 BEGIN 分离，但失败路径必然清位（owner/depth/state 一并复位 + notify_all），『有主无事务』不可能持续；且锁内认领保证**同一时刻最多一个任务发出 BEGIN**——owner 只能在 Condition 锁内被置位，等待者在锁内循环、无法与其他任务并发认领，原「两任务先后通过 owner is None 同步检查、各自 await BEGIN、后者 OperationalError 后误回滚先到者事务」的竞态被结构性消除。
  5. **不变量**：`_txn_owner_task == current_task()` ⟺ `depth ≥ 1`（owner 有值必有正在建立或已建立的事务；该局面只有认领者自己可见，其他任务一律先等）。
  6. **等待者语义**：等待者**永不自行 BEGIN**——被唤醒后回锁内重查 owner，非 None 则继续 `wait()`；同一次 `notify_all()` 唤醒的多个等待者逐个取锁，第一个完成认领，其余看到 owner 非 None 重新等待，不会并发认领（3 任务探针见任务 0.5③）。
- **`__aexit__` 扩展（F2 复位顺序）**：owner 层 finally 按序 **depth 归零 → `_txn_owner_task = None` → `_txn_state` 置 None → `async with self._txn_free: notify_all()`**（notify 在锁内、全部字段清理之后，杜绝等待者唤醒后看到残留 owner 而反复 wait 的死锁）；join 层不通知。
- **残余窗口**：owner 在 COMMIT/ROLLBACK await 点被取消（finally 未执行 → 等待者永久阻塞，合作取消下仅「取消恰在 sqlite commit 下发瞬间」一个 await 点）；或补偿的 rollback 亦被取消 → 孤儿事务残留，下一认领者 BEGIN 与之冲突抛 OperationalError 后走补偿 re-raise——失败可见而非挂死。均写入 Risks，有意识接受。
- **叶子 helper 门控不变**（D2 的 `depth == 0`）：跨任务等待者在 CM 入口已被挡下，不会在他人事务内执行 helper；`_txn_depth` 因此始终是"当前任务自己的事务深度"，计数语义正确。
- **性能**：单任务路径零 Condition 开销（同任务判断先行）；仅真实跨任务竞争时一次事件粒度等待，等价今天"碰巧不撞车"的串行化，无放大。

**D2 · helper 先行切 `depth == 0` 门控，block 迁移随后。**
**25 个叶子 helper**（`data_manager.py` 2、`database_extended.py` 23）体内有 `if commit: await self.conn.commit()`，改为 `if commit and getattr(self.conn, "_txn_depth", 0) == 0: commit`——判的是**所有权**（我们是否发过 BEGIN）而非 autocommit 状态。已实测验证：§7.1 那 9 个测试不改也过（hand-BEGIN + `commit=False` 调用本就不该提交；默认 commit 的独立调用 depth==0 正常提交）。**7 个纯透传 wrapper**（`core/pill_manager.py:628`、`managers/bank_manager.py:458`、`handlers/shop_handler.py:345`、`managers/impart_manager.py` ×4）无本地提交门控，第一阶段零改动，随叶子行为自动继承。**例外**：`set_active_legacy_instance` / `learn_or_star_up` 的 commit 门控的是 BEGIN IMMEDIATE（:460-461、:830-831，检查点在 DML 之前所以碰巧正确），本阶段不动，随 4.2 收编时把 BEGIN 条件一并改为 `depth == 0` 判定。已核验：全部 26 个块内调用均为 `commit=False`/`external_transaction=True` 或裸 SQL，生产代码不存在"事务内 commit=True 调用"——D2 不破坏任何现有 §7.1/§7.3 测试。这一步行为保持，且使之后每个块的转换"进 CM 即安全"，调用点的 `commit=False` 可留待第二阶段一并清理。

**D3 · early-exit 收编策略（Q2 决策 = c 混合）。**
现状 8+ 处 sect 块与若干 bank 块是"BEGIN → 锁内复查 → 显式 rollback → return 失败文案"。能前置的复查挪到 CM 之前（多数 bank 块成立）；必须锁内复查的（sect `complete_construction_task` 的锁内 re-read 正是其 BEGIN 目的）用 `txn.abort()`。commit-on-clean-exit + abort 标记实现，不改 return 文案。

**D4 · 迁移顺序：bank 试点 → 其余模块逐块 → 第二阶段删 flag。**
bank_manager 6 块几乎同构（含 bd 9jt 刚修过的 claim_interest / 逾期追杀，回归价值最高）作试点；sect_manager 8 块（含锁内复查最复杂场景）随后；其余按模块清。每块转换 = "一个事务块 + 其调用点"，不是整个文件。第二阶段：50 处穿参清零后，从 34 个定义移除 flag（其中 2 个 BEGIN 门控 helper 随 4.2 收编），自事务 helper 收编为 CM，§7.1 kwarg 断言与 6 个 spy 测试改写为 CM 级测试。

**D5 · 测试策略：§7.2/7.4/7.5 全程不动；spy 断言断 ownership 信号（评审第 4 问决策）。**
这三组（中途注入失败全回滚、D5 stale-player 回归、bd 9jt 贷款原子性）与设计无关，是原子性契约的核心守护，迁移期原样运行。flag 退役时仅动 §7.1/§7.3——**6 个 spy 测试改写断 `conn._txn_depth` 信号**（CM 内 >0、CM 外 == 0、仅 owner 层提交），不只断 `in_transaction`：后者在裸 DML 后恒真，区分不了"在 CM 里"和"刚做过一条裸 DML"，会"因为错误的原因通过"。

## Risks / Trade-offs

- [生成器 handler `handle_buy` 在事务体内 yield，`except Exception`（:311）捕不到 GeneratorExit——**今天是预存的写锁泄漏**（生成器在任一 await/yield 点被关闭则 BEGIN 的写锁残留），CM 的 `__aexit__` 会**顺带修复**它（错误路径行为变化，属修复非漂移——已写入 Goals）] → 转换时**删除块内现已失效的手工 `except Exception: rollback`**（勿与 CM 嵌套造成双 rollback）；**✅ 已实测（spike 0.2）：基线上 CancelledError 注入真实 `handle_buy` 确证泄漏（in_transaction 残留 True）；CM 修复对 GeneratorExit/CancelledError 均生效（rollback + 清位 + 无告警）**。
- [`_check_loan_status` 外层 except 吞异常返回 None，与 CM 的 rollback 叠加] → 内层 re-raise → CM rollback → 外层吞异常，组合正确；**✅ 已实测（spike 0.2）：sqlite rollback 无活动事务时是安全 no-op 且无告警**。
- [abort 语义误用：调用方 abort 后继续写] → docstring 明示 abort 后块内写入仍会随事务回滚；CM 内不做运行时禁用（YAGNI）。
- [`_txn_depth` 随重连丢失/残留] → `connect()` 统一初始化为 0（含 `ensure_connection` 重建路径），属性只在连接对象上由本插件读写；连接关闭后 getattr 读到的是代理对象上的初始化值，不触及已关闭的底层连接。
- [CM 误入 raw BEGIN 块内部 → 重复 BEGIN 抛 OperationalError] → 过渡约束已文档化（D1）：AST 扫描证明 26 个生产块无此嵌套；转换期每个块的迁移本身就是消除 raw BEGIN 的过程。
- [协程在 `BEGIN` 的 await 点被取消 → BEGIN 可能已在后端生效] → D1.2 补偿子句已覆盖（清位 + notify_all + best-effort rollback + re-raise）；BEGIN 下发前的取消则无副作用；残余窗口（worker 线程已执行 BEGIN、补偿 rollback 亦被取消 → 孤儿事务残留，下一认领者 BEGIN 冲突抛 OperationalError 后走补偿 re-raise）**失败可见而非挂死**，**有意识接受**——插件场景（单连接、任务取消罕见）不做 shield 重试。
- [跨任务等待使协程在 CM 入口挂起（D1.2）] → 仅真实竞争时发生；读请求不受影响（读无需写锁）；等价今天手写语义的"没撞车"分支，无放大。
- [owner 任务在 COMMIT/ROLLBACK await 点被取消 → finally 未执行、等待者被永久阻塞（D1.2）] → 合作取消下 finally 总会执行，残余窗口仅"取消恰在 sqlite commit 下发瞬间"一个 await 点（微秒级）；**✅ 已实测（spike 0.5④）：owner 在 COMMIT await 被取消（SQL 层拦截挂起）→ finally 仍执行清位 + notify_all，等待者不被永久阻塞、后续认领成功——无需引入等待超时**；认领/补偿窗口已由 D1.2 补偿子句清位 + 失败可见兜底（⑤ 实测：认领者在 BEGIN await 被取消 → 补偿清位 + 后续认领成功，孤儿事务冲突未复现）。
- [CM 化后并发冲突从"报错"变为"等待"，掩盖调度层冲突痕迹] → 语义对齐 BEGIN IMMEDIATE 的串行化意图（写锁本就该串行）；冲突等待是正常态而非异常态，不为此加日志噪声。
- [CM 打开期间连接断开被 `ensure_connection` 重建 → owner 退出对新连接 commit（成功 no-op），旧事务数据静默丢失且调用方拿到成功] → 断连发生在块内任一写之前则会先抛错走 rollback，仅"最后一条写成功后再断连且块内无后续错误"才静默；单连接 + 本地 sqlite 下概率极低，接受并在 CM docstring 注明，不做 epoch 防护。
- [迁移中途信号模糊：新旧两套检查并存] → 接受；§7.3 spy 测试在迁移完成前持续给出"哪块还没转"的信号，这正是保留它们到第二阶段的理由。
- [某未转换块依赖 helper "在事务内也提交"的隐式行为] → 不存在：事务内 commit 即 bug 本体，D2 反而修复之；若注入测试暴露意外依赖，按 bug 处理并登记 bd。

## Migration Plan

无部署步骤，随插件重载生效；无 DB/配置变更。回滚 = revert 对应 commit（按块提交，块间可独立回滚）。

## Open Questions

- **全部回答（2026-09-19 spike 任务 0 完成；探针文件 `tests/test_transaction_cm_spike.py`，18 个探针全绿 + 既有 866 全量测试全绿，无颠覆性发现）**：
  1. **GeneratorExit/CancelledError 写锁泄漏**：基线证据成立——`test_02_baseline_cancel_leaks_write_lock` 对**未改的真实 `handle_buy`** 注入 CancelledError（落在大事务块内 await 点），`:311` 的 `except Exception` 捕不到，结束后 `conn.in_transaction` 仍 True（等待者若此刻 BEGIN 会 OperationalError）。CM 修复生效：`test_02_cm_generator_exit_aclose_rolls_back`（async generator 在块内 yield → `aclose()` 注 GeneratorExit → rollback、depth/owner 清位、无 "cannot rollback - no transaction" 告警、gold 回滚）+ `test_02_cm_cancel_during_block_rolls_back`（task.cancel() 注 CancelledError → 同样正确回滚清位）。注意基线用 CancelledError 而非 GeneratorExit，因为真实 handle_buy 的成功路径 yield 点在 commit 之后、事务块内无挂起点可控；两者同为 BaseException，泄漏机制相同，CM 对两者的修复分别有断言。
  2. **无活动事务 rollback 探针**：`test_01_rollback_without_active_transaction_is_safe_noop` 确认 sqlite3 无事务时 rollback 为安全 no-op、无告警（Risks 相关条目已标实测）。
  3. **`txn.abort()` 原型**：按 D1 契约以独立数据流探针验证（未在真实 deposit 生产代码上临时改装——spike 阶段避免污染，正式接入留 3.x）——`test_03_abort_prototype_on_bank_deposit`（abort 后 clean exit → owner rollback 不 re-raise、gold 扣减撤销）、`test_03_abort_with_exception_still_rolls_back_and_reraises`（abort + 异常 → rollback + 重抛）、`test_01_abort_is_idempotent_and_marker_does_not_leak`（幂等 + 标记不泄漏到下一笔事务）。手感成立，D3 的 recheck-then-abort 方案无需修改。
  4. **0.5 跨任务交错**（`asyncio.gather` 并发，全部通过）：① `test_05_owner_exit_before_joiner_begin`——joiner 的 BEGIN 严格在 owner 退出之后（事件序断言 `begin_idx > owner_left`）；② `test_05_joiner_abort_does_not_affect_owner`——等待者无 state 可 abort（D1.2 语义），认领后成为**自己的** owner、其 abort 只回滚自己的事务（最终 gold==300：owner 的 300 提交、joiner 的 900 被自己的 abort 回滚）——**后到者 abort 不影响先到者事务✓**；③ `test_05_three_way_claim_race_serializes`——3 任务严格串行（事件序无重叠），BEGIN×3 / COMMIT×3 / ROLLBACK×0，gold 10003（3 次写全提交；F1 闭合：同一次 notify_all 唤醒多个等待者 → 逐个取锁，第一个认领，其余重等）；④ `test_05_owner_cancel_at_commit_await_no_deadlock`——owner 在 COMMIT await 点被取消 → finally 清位（owner/depth/state 全 None/0）+ notify，等待者不永久阻塞，后续认领成功（不挂死 ✓，无需引入等待超时）；⑤ `test_05_claim_cancel_compensation_frees_ownership`——认领者在 BEGIN await 点被取消（探针在 SQL 层拦截 BEGIN 挂起 5s）→ 补偿清位 + notify_all → 后续任务正常认领成功。**静默共享事务、双 BEGIN、死锁均未复现**；共享 state 仅发生在同任务嵌套（`test_01_same_task_nesting_is_noop_join`：内层句柄 `state is outer._state`，内层 abort 经共享 state 由 owner 落地——`test_01_inner_abort_propagates_to_owner`）。
- 非目标备注：`data/migration.py:555,590,615` 迁移期 plain `BEGIN` 不在本 change 范围。

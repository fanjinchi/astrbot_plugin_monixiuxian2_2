## Context

动机与玩家向后果见 `proposal.md`。本设计只记录实施所需的当前状态与约束。

- **可用的收编原语**：`data/data_manager.py` 的 `DataBase.transaction()`（:268）→ `_TransactionCM`（:63）。同任务嵌套 = `conn._txn_owner_task is current_task` 走 **no-op join**（`_txn_depth += 1`，`self._joined = True`，不发 BEGIN、退出不 commit/rollback）；跨任务进入在 `db._txn_free` 条件锁内等待 owner 释放后**锁内认领、出锁再 BEGIN**（design D1.2）；`txn.abort()` 供锁内复查后放弃。
- **D2 所有权门控**：写叶子按 `getattr(self.conn, "_txn_depth", 0) == 0` 决定是否提交（fail-open：独立调用保持存量语义）。已门控且本 change 依赖的叶子（逐一核过）：`data/data_manager.py update_player`（:322-325）、`data/database_extended.py set_user_busy`（门控内联于 `:726-747`，`set_user_free`:747 委托它）、`delete_impart_pk_cooldowns`（:642-645）、`delete_impart_snatch_protection`（:658）、`core/storage_ring_manager.py store_item`（:122 判 `_txn_depth > 0`）。
- **尚未门控、但有裸 `commit()` 的叶子**（本 change 必须处理，否则包了 CM 也等于没包）：`managers/dual_cultivation_manager.py` 的 `_get_pending_request`（:143，commit :151）、`_delete_request`（:174，commit :179）、`_set_last_dual_time`（:330，commit :340）；`data/database_extended.py` 的 `cancel_bounty`（:1087，commit :1093）、`set_system_config`（:1105，commit :1116）。
- **转换规则（继承前置 change，写入 AGENTS.md §3）**：包进 CM 必须**同步删除体内裸 `conn.commit()`**；CM **不得嵌在裸 `BEGIN IMMEDIATE` 块内**（本 change 的 9 处体内均无手工 BEGIN，已逐个核过）。
- **bd 旧锚点已失效**：bd `-2w1` 记录于 2026-09-14，其函数名仍可用、部分函数起始行已漂移（如 `spirit_eye_manager.collect_spirit_eye` 定义现于 :120，bd 记 :124；`gm_manager.cmd_clear_all_cooldowns` 现于 :1204，bd 记 :1207），**裸 commit 行号整体需重新锚定**。下表为本设计核验后的当前锚点。
- **并发前提**：单连接 + 生产代码全库无锁；4 个后台定时任务与指令处理器共享事件循环。本 change 的 8 个玩家向 spot 全部由单条指令触发、调用链同步，无跨任务交错写同一行的路径；CM 的跨任务串行化是兜底。

## Goals / Non-Goals

**Goals:**

- 9 例同形收编：8 处两段式提交 + 1 处四叶提交，全部变为"全成或全不成"的单一事务边界。
- 正常路径**零可观察变化**（返回文案、数值、结算顺序逐字不变）。
- 生产代码里"写函数体内裸 `conn.commit()` 分段"这一模式清零（便于将来 grep 闸门与 review 判据，不再留下会误导人的示范）。
- 每个 spot 至少一条原子性回归测试（第 2 段前注入异常 → 第 1 段回滚）+ 一条正常路径测试 + 一条"CM 内无提前提交"的深度断言。

**Non-Goals:**

- 不改 CM 本身、不加 SAVEPOINT、不引入新并发原语（`asyncio.Lock` 等）。
- 不重新审计 42 处口径外的单阶段自包含提交点（无半提交窗口，逐一复核结论见 proposal 非目标）。
- 不改 `complete_bounty`（:437）事务内结算 + 事务外 best-effort 掉落的已声明设计。
- 不把 `managers/bounty_manager.py abandon_bounty`（:530）这类"两次自提交叶子"（非裸 commit 形态）纳入本 change——见 Open Questions。
- 不调整 GM 清除命令的语义与文案。

## Decisions

### D1 逐 spot 分诊表（当前锚点为核验结果）

| # | spot（当前 file:line） | 第 1 段（已提交） | 第 2 段（可失败） | 修复后形态 | join 场景 | 风险 |
|---|---|---|---|---|---|---|
| S1 | `managers/spirit_farm_manager.py` `create_farm`（def :79，裸 commit :99） | `update_player`（`gold -= 10000`） | `INSERT INTO spirit_farms` | 从 `player.gold -= cost` 起包 CM（`async with self.db.transaction():`），删 :99 | 无（仅 `handlers/spirit_farm_handlers.py:30` 调用，handler 不在 CM 内） | 低：`update_player` 已门控，包内自动转被动 |
| S2 | `managers/spirit_farm_manager.py` `harvest`（def :149，裸 commit :216） | `update_player`（经验/灵石）+ `storage_ring_manager.store_item` ×N | `UPDATE spirit_farms SET crops = ?` | 包住"发奖 + 入库 + 清 crops"，删 :216 | 无外部 join；**函数内** join 面 = `store_item`（已门控，CM 内不提交） | 中：包内有 N 次 `store_item`，锁窗口随收获株数增长（见 D3） |
| S3 | `managers/spirit_farm_manager.py` `upgrade_farm`（def :241，裸 commit :265） | `update_player`（`gold -= cost`） | `UPDATE spirit_farms SET level = ?` | 同 S1 形态，删 :265 | 无（仅 `spirit_farm_handlers.py:64`） | 低 |
| S4 | `managers/spirit_eye_manager.py` `collect_spirit_eye`（def :120，裸 commit :147） | `update_player`（`experience += exp_income`） | `UPDATE spirit_eyes SET last_collect_time = ?` | 包住"发修为 + 推进时间戳"，删 :147 | 无（仅 `spirit_eye_handlers.py:42`）；同文件 `claim_spirit_eye`:70 已是 CM，不受影响 | 低 |
| S5 | `managers/blessed_land_manager.py` `purchase_blessed_land`（def :72，裸 commit :116） | `update_player`（`gold -= price`） | `INSERT INTO blessed_lands` | 包住"扣费 + 建洞天"，删 :116 | 无（仅 `blessed_land_handlers.py:46`） | 低 |
| S6 | `managers/blessed_land_manager.py` `upgrade_blessed_land`（def :127，裸 commit :164） | `update_player`（`gold -= upgrade_cost`） | `UPDATE blessed_lands SET level, exp_bonus, gold_per_hour` | 同上，删 :164 | 无（仅 `blessed_land_handlers.py:52`） | 低 |
| S7 | `managers/blessed_land_manager.py` `collect_income`（def :174，裸 commit :208） | `update_player`（`gold += / experience +=`） | `UPDATE blessed_lands SET last_collect_time = ?` | 同上，删 :208 | 无（仅 `blessed_land_handlers.py:58`） | 低 |
| S8 | `managers/dual_cultivation_manager.py` `accept_request`（def :237，无裸 commit；4 个自动提交点） | `update_player(initiator)` :286、`update_player(acceptor)` :287 | `_set_last_dual_time` ×2（def :330/commit :340）、`_delete_request`（def :174/commit :179） | 把"发修为 ×2 + 记冷却 ×2 + 删请求"整段包一个 CM；**三个叶子补 D2 门控**（见 D2）。函数首步 `_get_pending_request`（:143/commit :151）也需门控，因为它会在 CM 内被调用 | 有：本 spot 是**叶子 join 密集点**——`update_player` 已门控，`_set_last_dual_time`/`_delete_request`/`_get_pending_request` 三个叶子补门控后，CM 外调用方（`send_request` :181、`reject_request` :311）仍走 fail-open 独立提交，逐字不变 | 中：CM 边界需与 4 处 `_delete_request` 早退分支（修为差距超限、双方冷却未结等）共存——早退分支的删请求发生在 CM 外，仍为独立提交（语义不变） |
| S9 | `core/gm_manager.py` `cmd_clear_all_cooldowns`（def :1204，裸 commit :1246、:1257） | 步骤 1 忙碌状态（`set_user_free` + `update_player`）、步骤 2 `UPDATE combat_cooldowns` | 步骤 3 `UPDATE dual_cultivation` 起至步骤 5 传承清除 | 把步骤 1-5 的 DB 写整段包 CM，删 :1246/:1257；**顺带给 `cancel_bounty`(:1087)、`set_system_config`(:1105) 补 D2 门控**；步骤 6 的**内存态**历练路线休整冷却弹出移到 CM 块退出之后 | 无（GM `dispatch` :350 分发，无外层 CM）；`set_user_free`/`update_player`/`delete_impart_*` 均已门控 | 中：涉及 2 个 ext helper 补门控（D4）；`git` 上与活跃 change `busy-state-owner` 同段（D6） |

**分诊口径**：本表的第 1/2 段边界以"最后一次裸 commit 之前的写" vs "之后到函数结束的写"划定；S8 因无裸 commit，以"第一个自动提交叶子"划为两段，列全部 4 个提交点。

### D2 叶子 helper 用 D2 门控，而不是删 `commit()`

- **决策**：`_get_pending_request`、`_delete_request`、`_set_last_dual_time`（S8）与 `cancel_bounty`、`set_system_config`（S9）**补 D2 门控**（`if getattr(self.conn, "_txn_depth", 0) == 0: await self.conn.commit()`），而不是直接删掉 `commit()`。
- **理由**：这 5 个叶子同时被 CM 外路径调用——`send_request`（:181）用 `_create_request`/`_get_pending_request`/`_delete_request`；`reject_request`（:311）用 `_delete_request`；`bounty_manager.abandon_bounty`（:530）与 GM 悬赏清除路径用 `cancel_bounty`/`set_system_config`。删 commit 会让这些路径丢失提交（写丢失但看起来成功），是比现状更坏的 bug。
- **备选与否决**：(a) 给叶子加 `commit: bool` 参数透传——被前置 change 明确标记为**过渡兼容、第二阶段移除**的旧模式，不新增；(b) CM 边界只包到"叶子之前的写"、把叶子挡在 CM 外——做不到，叶子的写是同一逻辑单元的一部分（删请求必须与发修为同生共死），挡在外面正是本 bug 的成因。
- **一致性收益**：门控后，叶子的提交决策依据"连接自身已知的所有权"，与 `update_player` / `store_item` / `set_user_busy` 同形，CM 内自动被动、CM 外自动提交。

### D3 CM 边界：只包写段，读与校验留在 CM 外

- **决策**：CM 从**第一个写之前**开始，到**最后一个写之后**结束。校验读（`get_user_farm` / `get_user_spirit_eye` / `get_user_blessed_land` / `_get_pending_request` 之外的条件分支）保持在 CM 外。
- **理由**：单连接插件下 `BEGIN IMMEDIATE` 持写锁，锁窗口越短越好；S2 的收获循环会在包内多次调用 `store_item`（每次一次 UPDATE + 可能的读），是唯一的长窗口 spot。备选"整个函数体包 CM"被否：把纯校验读也纳入写锁，收益为零、阻塞窗口更大。
- **`txn.abort()` 是否需要**：不需要。S8 的早退分支（无请求、发起者数据异常、修为差距超限、双方冷却未结）都在**第一个写之前**判定完成，天然落在 CM 外；S1-S7、S9 同理。本 change 不引入任何 CM 内早退，故不需要 abort 语义（与前置 change "能前置的复查前置"一致）。

### D4 S9（GM cosmetic）的两处额外门控与内存态顺序

- **决策**：纳入本 change 转换（保持"9 例同形"），代价是 `data/database_extended.py` 两个 helper 补门控。
- **理由**：若不门控 `cancel_bounty`/`set_system_config`，它们会在新 CM 内各自 `commit()`，等于提前终结事务（与现状同病），转换变成假动作。补门控是机械改动且 fail-open，其它调用方语义逐字不变。
- **内存态顺序（必须遵守）**：步骤 6 的 `self.adventure_manager._route_cooldowns.pop(target_id, None)` 是**内存**操作，回滚撤不回。若它在 CM 块内执行而事务最终回滚，玩家会丢掉历练路线休整冷却而 DB 侧状态未清——比现状更差。故实现时把该 pop 移到 CM 块**退出之后**（提交成功再弹）。
- **备选与否决**：把 S9 单独拆出去一个 change（它是 cosmetic、且与 `busy-state-owner` 同段）。否决理由：拆分会让"模式清零"目标拖延，且正文已给出"实现顺序上放最后"的折中（见 D6 与 tasks 阶段 4）。**此项仍列为 Open Question 1，供用户拍板。**

### D5 行为变化：只发生在错误路径，正常路径逐字不变

- **声明**：修复后，两段之间发生异常时不再"部分成功"，而是整段回滚（玩家看到失败、状态与操作前一致）。正常路径的返回值、文案、数值、结算顺序不变。
- **反向影响**：若某处异常今天被"部分成功"掩盖（例如收获时储物戒满→物品丢失文案路径），修复后该路径的**结果不变**（`store_item` 的失败分支只是文案提示，不抛异常，仍在同一事务内提交）。已核 `harvest` 的这一分支：`store_item` 返回 `False` 不抛异常 → 事务照常提交，文案逐字保留。
- **取舍**：全成或全不成是唯一正确语义；"部分成功"没有任何玩家向价值，且是重复刷取漏洞的成因。

### D6 与活跃 change 的冲突与落地顺序（逐条核过）

| 活跃 change | 是否碰本 change 文件 | 冲突判定 | 建议顺序 |
|---|---|---|---|
| `composition-root` | `managers/dual_cultivation_manager.py:35`（删自建 `CultivationManager`、改收注入）、`tests/test_dual_cultivation.py:47`、`tests/test_transaction_atomicity.py:117`（fake 构造点） | **同文件不同区（:35 构造 vs :237+ 写段）、同测试文件不同区（:117 附近 vs 追加的 §8）**；若它先落地，S8 及以下行号整体漂移约 1-2 行 | 建议**先落 `composition-root`**（不改本 change 的修复形态，仅需 apply 时重锚；且它已定案 `BusyState` 接线方式，是 `busy-state-owner` 的前置） |
| `busy-state-owner` | `core/gm_manager.py:908-910` / **`:1236-1239`**（`cmd_clear_all_cooldowns` 步骤 1 的手动双重置 → `clear(player)`）、`tests/test_gm_manager.py:377-389` | **S9 同一函数内直接重叠**：它的 2.4 步改的正是本 change 要包进 CM 的那一段；其 1.1b 明确依赖 `composition-root` 先合入 | 建议**它先落**（步骤 1 变成单次 `clear(player)`，其内部走已门控的 `set_user_free`/`update_player`，本 change 的 CM 包裹天然兼容）；本 change 把 S9 放在**阶段 4 最后**实现，届时按实际代码重锚——若它尚未落地，就包当前的手动双重置版本（两者都可，形态不变） |
| `gm-time-skip-registry` | `core/gm_manager.py:68`（`_TIME_SKIP_RULES`）、`:1187`（`cmd_time_skip` 的 CM 块，位于 S9 之前的函数）、`managers/dual_cultivation_manager.py`、`managers/bounty_manager.py`、`managers/boss_manager.py`、`managers/impart_pk_manager.py`（时间戳属主常量） | **相邻但不重叠**（:1187 在 `cmd_time_skip` def :1159 内，S9 def 在 :1204）；它的 1.2 步会把 `dual_cultivation` 的 UPDATE SQL 文本迁入属主模块并提供域 provider 常量 | 顺序无关；若它**先落**，S9 的步骤 3 可能需要改为调用属主模块提供的清除方法（而非内联 SQL），apply 时按实际代码重锚并在 tasks 阶段 4 记录 |
| `combat-result-winner-identity` | `managers/pve_combat_manager.py`、`managers/combat_manager.py`、`managers/impart_pk_manager.py`、`handlers/combat_handlers.py` | **无关**（不碰本 change 的 5 个文件） | 任意 |
| `decouple-handler-to-handler-calls` | `handlers/sect_handlers.py`、`handlers/bounty_handlers.py`、`handlers/ranking_handlers.py` | **无关**（层不同：本 change 不在 handlers 层写代码；它改的是 handler 间调用，不改 manager 写路径） | 任意 |
| `narrative-contract-module` | `managers/rift_manager.py`、`managers/combat_manager.py`、`managers/adventure_manager.py`、`core/breakthrough_fortune.py` | **无关** | 任意 |

**通用约束**：无论谁先落地，本 change 的 apply 首步永远是"按当前代码重跑锚点复核"（见 tasks 阶段 1），行号漂移不构成阻塞。

### D7 测试策略

- **落点**：`tests/test_transaction_atomicity.py` **追加 §8 章节（append-only）**，不新建文件。理由：该文件已是"中途失败必回滚 + helper 不提前提交"契约的唯一归属地（28 个测试函数），装置齐备（`db` fixture：`DataBase(tmp_path/'test.db')` + `MigrationManager(conn, MagicMock()).migrate_or_reset()`；`_make_player`；`_spy_in_transaction(db, monkeypatch, obj, name, states)` 记录 `(name, db.conn.in_transaction, db.conn._txn_depth)`）。追加在文件尾部可避开 `composition-root` 正在改的 `:117` 附近。
- **为什么不动 `tests/test_gm_manager.py` / `tests/test_dual_cultivation.py`**：前者 `:377-389` 正被 `busy-state-owner` 改写，后者 `:47` 正被 `composition-root` 改写——把 S8/S9 的回归放在同一份追加区块里可零冲突。
- **每 spot 三条断言**：
  1. **回滚**：包装 `db.conn.execute`，当 SQL 命中该 spot 的**第 2 段写**语句特征串时抛异常、其余透传；断言第 1 段痕迹不存在（S1：灵石仍为原值且 `spirit_farms` 无行；S2：经验/灵石未加、crops 未清、储物戒无货；S3/S6：灵石未扣、等级未升；S4/S7：经验未加、`last_collect_time` 未推进；S5：灵石未扣且无洞天行；S8：双方修为未加、冷却时间戳未写、请求仍在；S9：`combat_cooldowns`/`dual_cultivation` 的 `rowcount` 目标未被清）。
  2. **正常路径**：调用成功 → 两段写入都在、且退出后 `db.conn.in_transaction is False`（owner 已提交）。
  3. **无提前提交**：`_spy_in_transaction` 包裹该 spot 内所有已门控叶子，断言每次调用观察到 `_txn_depth > 0`（证明叶子没在 CM 内提交）。
- **S9 的额外断言**：CM 回滚时**内存态**历练路线休整冷却不得被弹掉（对应 D4 的顺序要求）。
- **质量门**：`uv run ruff format . && uv run ruff check .`；`uv run python -m pytest tests/ -v`（基线 `872 passed, 1 xfailed`）。

## Risks / Trade-offs

- **S8 事务边界与早退分支** → 早退分支全部前置在 CM 外（无写发生），实现时逐条检查 return 路径确认没有"CM 内 return"（tasks 3.2 的核验项）；若有，改用 `txn.abort()`。
- **S2 锁窗口随收获株数增长** → 可接受：单指令串行触发、单连接场景无并发读者需写锁；不为此引入批量写重构（Non-Goal：不改玩法/结算顺序）。
- **补门控的 5 个叶子被其它路径复用** → fail-open 语义保证 CM 外逐字不变；由 §8 的"CM 外独立调用仍提交"断言 + 既有 `tests/test_transaction_atomicity.py` §7.1 同族断言共同守护。
- **S9 与 `busy-state-owner` 同段** → 实现顺序放最后 + apply 首步重锚（D6）。
- **内存态不可回滚** → D4 规定 pop 移到 CM 之后；测试显式断言回滚时未弹。
- **误把"已经自包含"的 spot 也包进 CM** → 非目标已排除；各 spot 复核对齐 bd `-2w1` 的 9 例清单（不扩不缩）。
- **行为变化被误读为功能变更** → proposal 显式声明；本 change 不改数值/玩法，`design_docs/` 无需同步（不属 §14 的玩法变更）。

## Migration Plan

- **部署**：纯代码替换，随插件重载生效（AstrBot WebUI → 插件 → 重载）。无 DB 迁移、无配置项、无灰度。
- **回滚**：逐个文件 revert 即可——每处修复是独立函数级替换，互不依赖（无共享状态、无顺序要求）；无数据写入形态变化（表结构/字段不变），回滚不需要数据修复。
- **落地顺序建议**：阶段 1 锚点复核 → 阶段 2（S1-S7，farm/eye/blessed land）→ 阶段 3（S8，dual，含 3 个叶子门控）→ 阶段 4（S9 GM，含 2 个 ext 门控与内存态顺序）→ 阶段 5 测试与质量门 → 阶段 6 关闭 bd `-2w1` 与文档同步。
- **关闭条件**：质量门全绿（`872 passed + §8 新增, 1 xfailed`）、9 个 spot 的裸 commit 全部消失（grep 验证）、bd `-2w1` 关闭并注明落地 commit。

## Open Questions

1. **S9（GM cosmetic）是否纳入本 change？** 纳入需顺带为 `data/database_extended.py` 的 `cancel_bounty`（:1087）与 `set_system_config`（:1105）补 D2 门控（2 处机械、fail-open 改动）。若用户倾向"最小范围"，S9 可推迟为独立小 change（代价：生产代码仍留 2 处裸 commit 分段示范）。**需用户拍板**。
2. **未登记的同族 spot：`managers/bounty_manager.py abandon_bounty`（:530）** —— 两次自提交叶子（`cancel_bounty` → `set_system_config("bounty_abandon_cd_*")`）顺序执行，第二次失败 = 悬赏已放弃但无 30 分钟放弃冷却（可立即接新悬赏）。形态属"多段提交但体内无裸 commit"，与 S8 同族，**不在 bd `-2w1` 的 9 例清单内**。建议：本 change 收录为 Non-Goal，apply 阶段另立 bd 跟踪（含 `complete_bounty` 之外的悬赏路径盘点）。**需用户确认是否接受"另立 bd"。**
3. **行为变化确认**：错误路径从"部分成功"改为"全成或全不成"是本 change 的目的（D5）。若用户认为"部分成功"在个别 spot（如收获时储物戒满仍应发奖）需要保留，请指出——这会影响 S2 的 CM 边界。**需用户确认。**

> `design_docs/` 同步：本 change 不改数值/玩法/内容，无需更新 `design_docs/`（不触及 §14/§15 的触发条件）。

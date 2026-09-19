# Proposal: fix-two-stage-commit-atomicity

## Why

前置基建已就位：`add-transaction-unit-of-work`（2026-09-19 归档）落地了 `async with db.transaction() as txn:` 单元工作 CM（`data/data_manager.py` 的 `DataBase.transaction()` → `_TransactionCM`）与 25 个写叶子的 D2 所有权门控（`conn._txn_depth == 0` 才提交，fail-open 保持独立调用语义）。该 change 的 design D1.1 分诊把 **9 例 fake-atomicity 显式延后**，登记为 bd `astrbot_plugin_monixiuxian2_2-2w1`——本 change 就是那 9 例的收尾，外加 apply 前经用户拍板纳入的 1 例**同族未登记 spot**（`bounty_manager.abandon_bounty`，形态与 S8 同族、不在 bd 2w1 的 9 例清单内），合计 **10 例（S1-S10）**。

形态（按"先提交后写"模式扫，而非"42 处子集"口径）：**9 处两段式提交**（第 1 段提交后第 2 段失败 → 半提交状态；其中 8 例在函数体内裸 `conn.commit()` 分段，`abandon_bounty` 形态同族但两段均为自提交叶子、体内无裸 commit）**+ 1 处五叶提交**（`dual_cultivation_manager.accept_request` 体内无裸 commit，但 5 个叶子各自自动提交：`update_player` ×2 + `_set_last_dual_time` ×2 + `_delete_request`）。9 处是玩家向（可被正常指令触发并重试），1 处是 GM cosmetic（`cmd_clear_all_cooldowns`，各域清除幂等、可重跑）。

玩家向后果（异常落在两段之间 = 已提交的第 1 段留下真实收益/损失，玩家重试即重复生效）：

- `spirit_farm_manager.create_farm`：扣 10,000 灵石已提交 → 建田失败 = **重复扣费**
- `spirit_farm_manager.harvest`：发修为/灵石 + 入库储物戒已提交 → crops 未清 = **重复收获**（可反复刷）
- `spirit_farm_manager.upgrade_farm`：扣升级费已提交 → 等级未升 = **双重扣费**
- `spirit_eye_manager.collect_spirit_eye`：发修为已提交 → `last_collect_time` 未推进 = **重复领取**（可反复刷）
- `blessed_land_manager.purchase_blessed_land` / `upgrade_blessed_land`：扣费已提交 → 洞天写入失败 = **重复扣费**
- `blessed_land_manager.collect_income`：发灵石/修为已提交 → `last_collect_time` 未推进 = **重复领取**
- `dual_cultivation_manager.accept_request`：双方修为已发、冷却时间戳部分写入 → 请求未删 = **重复双修刷修为**
- `bounty_manager.abandon_bounty`：取消悬赏已提交 → 30 分钟放弃冷却写入失败 = **白白放弃悬赏**（无需冷却即可立即接新悬赏）

现在做的理由：CM 已落地，10 例同形，可**单模式**收编（包 CM + 删体内裸 `conn.commit()`），且这正是 AGENTS.md §3 关系数据库规范里"并发敏感操作必须使用事务保护"的最后一处系统缺口；越晚做，锚点越容易被其它活跃 change 漂移。

## What Changes

- **7 处玩家向两段式提交**包进 CM + 删体内裸 `conn.commit()`（写段入 CM，读/校验留在 CM 外以缩短锁窗口）：
  - `managers/spirit_farm_manager.py`：`create_farm`（:79，裸 commit :99）、`harvest`（:149，裸 commit :216）、`upgrade_farm`（:241，裸 commit :265）
  - `managers/spirit_eye_manager.py`：`collect_spirit_eye`（:120，裸 commit :147）
  - `managers/blessed_land_manager.py`：`purchase_blessed_land`（:72，裸 commit :116）、`upgrade_blessed_land`（:127，裸 commit :164）、`collect_income`（:174，裸 commit :208）
- **1 处五叶提交**：`managers/dual_cultivation_manager.py` `accept_request`（:237）把"发修为 ×2 + 记冷却 ×2 + 删请求"整个写段包进一个 CM（共 5 个自提交叶子：`update_player` ×2 + `_set_last_dual_time` ×2 + `_delete_request`）；其叶子里**尚无 D2 门控**的三个（`_get_pending_request` :143/裸 commit :151、`_delete_request` :174/裸 commit :179、`_set_last_dual_time` :330/裸 commit :340）**补 D2 门控**而不是删 commit——其中 4 个叶子有 CM 外调用方（`_get_pending_request`/`_delete_request` 由 `accept_request` 早退分支与 `reject_request` 调用；`send_request` 只走 `_create_request`，不碰这两个叶子），门控的 fail-open 语义保证那些路径逐字不变。
- **1 处 GM cosmetic（用户拍板纳入）**：`core/gm_manager.py` `cmd_clear_all_cooldowns`（:1204，裸 commit :1246 与 :1257）包进 CM + 删两处裸 commit；其"悬赏"步骤调用的 `data/database_extended.py` `cancel_bounty`（:1087/commit :1093）、`set_system_config`（:1105/commit :1116）需顺带补 D2 门控（否则会在 CM 内提前提交，等于没修）。步骤 6 的**内存态**历练路线休整冷却弹出移到 CM 块之后（内存不可回滚，回滚时不得已弹）。
- **1 处同族未登记 spot（用户拍板纳入）**：`managers/bounty_manager.py` `abandon_bounty`（:530）把"取消悬赏 `cancel_bounty` + 写 30 分钟放弃冷却 `set_system_config`"两段自提交叶子包进一个 CM（读与早退校验留在 CM 外）。它的两段叶子正是 S9 顺带补 D2 门控的那两个（`cancel_bounty` / `set_system_config`），**无额外门控工作**；`set_system_config` 被多个域复用，门控 fail-open 保证其 CM 外独立调用语义逐字不变。不涉及 `complete_bounty` 的 best-effort 掉落设计。
- **测试**：`tests/test_transaction_atomicity.py` 追加 §8 章节（append-only），逐 spot（S1-S10）覆盖"第 2 段写之前注入异常 → 第 1 段写入回滚"+"正常路径两段都落盘"+"CM 内每个叶子调用 `_txn_depth > 0`（无提前提交）"；复用既有 `db` fixture、`_make_player`、`_spy_in_transaction` 装置。
- **行为变化（显式声明，方向为修复）**：仅**错误路径**可观察——今天两段之间异常会留下"收益已发/费用已扣但状态未推进"的半提交状态，修复后变为**全成或全不成**。该语义**对全部 10 个 spot 一致适用（含 `harvest`，用户已拍板 all-or-nothing）**，不做 spot 级例外。正常路径逐字不变（返回值/文案/数值全不动）。这就是本 change 的目的，非 scope 漂移。

**非目标**：

- 不改任何数值、玩法、文案、掉落/概率、文案配置；不碰 `config/*.json` 与 `design_docs/content-design/`（本 change 为纯原子性修复，不属"内容设计先行"范围）。
- 不动 `managers/bounty_manager.py` `complete_bounty`（:437）"事务内结算 + 事务外 best-effort 物品掉落"的**已声明有意设计**（bd 2w1 记为 low）：本 change 不改变掉落与结算的顺序关系。
- 不重新审计 bd 2w1 的 42 处口径之外的单语句/自包含提交点（如 `spirit_farm_manager.plant_herb`:140、`spirit_eye_manager.spawn_spirit_eye`:66 / `release_spirit_eye`:170、`dual_cultivation_manager._create_request`:137、`bounty_manager.check_and_expire_bounties`:652）——经逐一复核为单阶段自包含写，无半提交窗口。不在该清单内的多段自提交 spot 是 `bounty_manager.abandon_bounty`，已纳入本 change 为 S10（不另立 bd）。change 级终审另发现 **3 处同族两段自提交残留（S9 同族未覆盖，均为 GM/自伤类、可重跑、用户不可见）**：`core/gm_manager.py:944`+`:949`（`cmd_clear_bounty`：`cancel_bounty` 与 `set_system_config` 各自提交、无 CM）、`core/gm_manager.py:553`+`:554`（`cmd_clear_legacy_state`）、`handlers/player_handler.py:652`+`:653`（弃道重修：`delete_player_cascade` 提交后写重修冷却键，第二步失败 → 角色已删但 7 天冷却键缺失 → 可绕过冷却），已登记 bd `astrbot_plugin_monixiuxian2_2-3ar`，不在本 change 处理。
- 不动已收编的 CM 块（`spirit_eye_manager.claim_spirit_eye`:70、`core/gm_manager.py cmd_time_skip`:1188、`bounty_manager.complete_bounty`:437 等）。
- 不引入 SAVEPOINT 嵌套语义、不改 CM 本身、不改 `isolation_level`、不做跨进程事务协调。
- 不调整 GM `cmd_clear_all_cooldowns` 的既有语义（清除范围、回复文案、幂等性逐字保持）；不新增/删除 GM 指令。

## Capabilities

### New Capabilities

（无——事务原子性是工程约束，由 `tests/test_transaction_atomicity.py` 钉住，没有需求级行为语义。）

### Modified Capabilities

（无——已核查 `openspec/specs/` 现有 13 篇 spec（attribute-numerics、battle-status-effects、combat-core、content-sync-pipeline、functional-test-suite、gm-commands、impart-system、level-progression、narrative-text-config、novel-reading-extraction、sect-commands、sect-system、skill-system），无一篇包含事务/原子性 requirement；本改动是恢复既有设计意图的错误路径修复，不改任何 spec 级行为。故 `.openspec.yaml` 设 `skip_specs: true`，不编造 requirement 满足校验。）

## Impact

- **代码（7 文件）**：`managers/spirit_farm_manager.py`、`managers/spirit_eye_manager.py`、`managers/blessed_land_manager.py`、`managers/dual_cultivation_manager.py`（3 个叶子补 D2 门控）、`core/gm_manager.py`、`managers/bounty_manager.py`（S10 包 CM）、`data/database_extended.py`（`cancel_bounty` / `set_system_config` 补 D2 门控，S9 与 S10 共用）。
- **测试**：`tests/test_transaction_atomicity.py` 追加 §8（不出现在其它文件的原子性契约集中在同一处）；不新增测试文件、不改既有断言。基线：`872 passed, 1 xfailed`。
- **数据库/配置**：无迁移、无配置项、无依赖变更。
- **文档**：AGENTS.md、design_docs 均无需改动（无玩法/数值/接口变化）；本 change 关闭 bd `astrbot_plugin_monixiuxian2_2-2w1`（10 例收编完成，不再另立同族 bd）。
- **与活跃 change 的顺序**（详见 design D6）：`busy-state-owner` 会改到 GM 清除函数的同一段（`:1236-1239`），`composition-root` 会改 `dual_cultivation_manager.py:35` 构造签名与 `tests/test_transaction_atomicity.py:117` 附近，`gm-time-skip-registry` 会改 `core/gm_manager.py:68`/`:1187`；其余三个（combat-result-winner-identity、decouple-handler-to-handler-calls、narrative-contract-module）核对后与本 change 无文件重叠。

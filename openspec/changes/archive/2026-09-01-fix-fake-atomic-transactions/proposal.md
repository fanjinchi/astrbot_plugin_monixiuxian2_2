# Proposal: fix-fake-atomic-transactions

## Why

复审确认（bd `astrbot_plugin_monixiuxian2_2-rc0`；`8nu` 为重复项已关闭）：存量 manager 的 `BEGIN IMMEDIATE` 事务块内调用的数据层 helper 若内部自带 `commit()`，第一个内层 commit 即终结事务、提前释放写锁，外层事务的读-校验-写原子性失效（"假原子事务"）。宗门路径已按"helper 加 `commit` 参数、外层统一提交"的模式修复（commit `c39c42a` 及后续），但同类模式仍存在于银行、储物戒、商店购买、逾期追杀等路径，并发或中途异常时可造成半提交状态（如存款扣了灵石但余额未落账）。

review 复查（第二名审查者带行号实证）在同一临界区内另发现**更严重的成功路径数据丢失 bug**：商店购买块中 `store_item(external_transaction=True)` 内部重取 fresh_player 并整行写回（`core/storage_ring_manager.py:121-126`/:139），随后 `handlers/shop_handler.py:300-301` 用事务开始时的陈旧 player 对象再次整行写回，把 `storage_ring_items` 覆盖回旧值——购买武器/防具/材料/功法类商品在**成功路径上丢货扣钱**（已在临时 sqlite 实证）。它就在本 change 触碰的临界区内，决策纳入本变更一并修复（方向见 design D5）。

## What Changes

- **数据层补 `commit` 参数**（沿用宗门修复模式，默认 `True` 保持全部存量调用方行为不变）：
  - `data/data_manager.py`：`delete_player_cascade`（:144，内部 commit 于 :193）
  - `data/database_extended.py`：`update_bank_account`（:992）、`create_loan`（:1253，`last_insert_rowid` 查询须随 commit=False 留在事务内）、`close_loan`（:1273）、`mark_loan_overdue`（:1280）、`add_bank_transaction`（:1311）
- **manager/handler 层透传 `commit`**：`managers/bank_manager.py` 的 `_add_transaction`（:400）、`core/pill_manager.py` 的 `add_pill_to_inventory`（:654，透传给 `update_player`）、`handlers/shop_handler.py` 的 `_apply_legacy_pill_effects`（:345，透传给其 :454 的 `update_player`）增加 `commit: bool = True` 参数。
- **逐块修复假原子事务**（块内 helper 一律改传 `commit=False`，由外层统一 commit/rollback）：
  - `managers/bank_manager.py`：`deposit`（:109）、`withdraw`（:152）、`borrow`（:252，方法定义 :236）、`repay`（:310）四块
  - `core/storage_ring_manager.py`：`store_item`（:119，含 `external_transaction=True` 分支）、`retrieve_item`（:164）、`discard_item`（:201）三块——块内 `update_player` 改 `commit=False`
  - `handlers/shop_handler.py` 购买事务（:208）：块内 `update_player`（:301）改 `commit=False`；`add_pill_to_inventory`（:254）与 `_apply_legacy_pill_effects`（:261，其内部 :454 自提交）透传 `commit=False`；`store_item(external_transaction=True)`（:234/:270/:283）随储物戒修复后不再内层 commit
  - `handlers/utils.py` `_check_loan_status`（:161）：`delete_player_cascade`/`mark_loan_overdue`/`add_bank_transaction` 改 `commit=False`
- **修复商店购买成功路径的陈旧 player 覆盖**（review 发现，见 Why 第二段）：`store_item` 在 `external_transaction=True` 时不再内部重取、直接作用于调用方传入的 player 对象（写锁内 `shop_handler.py:210` 已重取，二次重取冗余），使物品写入与 :300-301 最终扣款写回落在同一对象；方案对比与 pill 分支影响评估见 design D5。
- **并发回归测试**：`tests/` 新增用例，验证事务块中途注入失败时全部写入回滚（不留半提交）、`commit=False` helper 不自行提交，以及购买装备类商品成功路径"储物戒确有物品且灵石正确扣除"。

**明确不在本变更内**（顺带观察，另立 bd 跟进）：

- `bank_manager.claim_interest`（:182）与 `check_and_process_overdue_loans`（:364）的多步写**完全没有事务**（缺事务而非假原子），是否补事务另行评估
- `data/data_manager.py` 的 `increment_shop_item_stock`（:329，自包含事务，当前无调用方）与 `update_shop_data`（:232）等独立自提交 helper——无外层事务嵌套，行为正确，不动
- 任何数值/流程/玩法变更：本变更为纯 bug 修复，恢复既有设计意图

## Capabilities

### New Capabilities

（无。）

### Modified Capabilities

（无——已逐一核查 `openspec/specs/` 现有 13 篇 spec（attribute-numerics、battle-status-effects、combat-core、content-sync-pipeline、functional-test-suite、gm-commands、impart-system、level-progression、narrative-text-config、novel-reading-extraction、sect-commands、sect-system、skill-system），无一篇包含事务/原子性相关 requirement（全库检索 transaction/事务/原子 无命中）。本改动是恢复既有设计意图的纯 bug 修复（含 review 新发现的成功路径丢货 bug），不改变任何 spec 级行为语义，不为满足校验编造 requirement。本 change 已在 `.openspec.yaml` 声明 `skip_specs: true`。）

## Impact

- **代码侦察结论**（2026-08-30 初查 + review 复查补正，全库 `BEGIN IMMEDIATE` 27 处逐块核查）：
  - **确认假原子（本变更修复）**：`managers/bank_manager.py` 4 块、`core/storage_ring_manager.py` 3 块、`handlers/shop_handler.py` 1 块、`handlers/utils.py` 1 块，共 9 块；根因 helper 为 `update_player`（`data/data_manager.py:126`，commit 于 :137）、`update_bank_account`、`create_loan`、`close_loan`、`mark_loan_overdue`、`add_bank_transaction`、`delete_player_cascade`，及 handler 内私有方法 `_apply_legacy_pill_effects`（:454 调 `update_player`，review 复查补认的第二个块内自提交点）
  - **确认干净（无需动）**：`managers/bounty_manager.py`（:331/:445/:599 块内仅直接 SQL）、`managers/spirit_eye_manager.py`（:72 直接 SQL + `total_changes` 守卫）、`managers/impart_manager.py`（:225 已传 commit=False）、`handlers/player_handler.py`（:506 已传 commit=False）、`managers/sect_manager.py` 全部 8 块（c39c42a 起已修）、数据层自包含事务 `decrement_shop_item_stock`/`increment_shop_item_stock`/`set_active_legacy_instance`/`learn_or_star_up`（无外层嵌套调用）
  - **review 复查新增修复对象（非假原子，更严重）**：商店购买成功路径陈旧 player 覆盖致装备/材料/功法类商品丢货扣钱（`storage_ring_manager.py:121-126`/:139 × `shop_handler.py:300-301`，临时 sqlite 实证；pill/legacy_pill 分支操作同一对象不受影响）
- **改动文件**：`data/data_manager.py`、`data/database_extended.py`、`managers/bank_manager.py`、`core/storage_ring_manager.py`、`core/pill_manager.py`、`handlers/shop_handler.py`、`handlers/utils.py`、`tests/`（新增回归用例）
- **兼容性**：所有 `commit` 参数默认 `True`，存量调用方（含 `player_handler.py:629`、`breakthrough_manager.py:400`、`bank_manager.py:384` 的独立 `delete_player_cascade` 调用）行为不变；`external_transaction=True` 全库仅商店购买三个调用点（`shop_handler.py:235/:271/:284`），store_item 行为变化范围可控；无数据库 schema 变更、无 migration
- **测试**：`tests/test_shop_handler.py`、`test_pill_manager.py` 等既有用例保持绿；新增事务回滚/不提前提交/购买成功路径的回归用例
- **流程**：纯 bug 修复，不影响玩法数值——按 AGENTS.md §14 无需同步 design_docs 玩法资料；版本 checklist（metadata.yaml、README 更新日志）照常
- **bd**：落地后关闭 `astrbot_plugin_monixiuxian2_2-rc0`；顺带观察项（缺事务的两处银行路径）另立 bd

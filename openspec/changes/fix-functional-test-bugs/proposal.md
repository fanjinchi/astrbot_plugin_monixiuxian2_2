# Proposal: fix-functional-test-bugs

## Why

`add-functional-test-suite` 通过网页测试平台在真实 AstrBot 实例上跑功能测试（`2026-08-17_core-smoke` 7 例、`2026-08-17_pvp-effects` 63 例），发现 3 个当前项目 Bug，均已登记为 open 状态的 bd issue（`astrbot_plugin_monixiuxian2_2-tbp` / `-qv9` / `-7px`）且尚未修复。这 3 个 Bug 分别导致「切磋」命令直接抛异常、忙碌状态双层检查不一致、GM 无法发放心法，影响玩家正常游戏与测试/运营效率。

## What Changes

- **修复「切磋」UnboundLocalError（bd `tbp`）**：`handlers/combat_handlers.py` 的 `handle_spar` 在使用 `result` 前未调用战斗引擎赋值，补上 `result = await self.combat_mgr.player_vs_player(p1, p2, combat_type=1)`（与 `handle_duel` 的 `combat_type=2` 对应），使切磋正常结算并输出战斗日志。
- **修复 `set_user_busy` 只 UPDATE 不 INSERT（bd `qv9`）**：`data/database_extended.py` 的 `set_user_busy` 改为 upsert（`INSERT ... ON CONFLICT(user_id) DO UPDATE`），保证无 `user_cd` 行的玩家进入闭关/历练等忙碌状态时也会落库，使双层状态检查（`player.state` + `user_cd`）保持一致。
- **GM 发放支持心法等全部已配置物品类型（bd `7px`）**：`core/gm_manager.py` 的 `_item_exists` 扩展检查范围，除 `items_data`/`weapons_data` 外纳入 `heart_methods_data` 等其余配置表，使「修仙GM 给予装备/给予物品」可发放心法（如「长春功」）等已配置物品。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `gm-commands`: 「给予装备/给予物品」的物品存在性校验 SHALL 覆盖所有已配置的物品类型（含心法），而不仅是物品与武器配置表。

> Bug 1（切磋）与 Bug 2（忙碌状态落库）均为对既有已规定行为的实现修复：切磋正常结算已在 `combat-core` 规格中要求，忙碌状态双层一致是项目既定约定（AGENTS.md），二者不引入需求变更，故不产生对应 delta。

## Impact

- **代码**：`handlers/combat_handlers.py`（handle_spar）、`data/database_extended.py`（set_user_busy）、`core/gm_manager.py`（_item_exists）。
- **测试**：`tests/` 需新增/补充回归测试；修复后通过测试平台重跑 `pvp-basic-spar`（当前唯一失败用例，预期转为通过）与 `gm-basics` 相关用例。
- **bd**：修复验证后关闭 `tbp` / `qv9` / `7px` 三个 issue。
- **文档**：按项目版本更新 checklist 同步 `metadata.yaml` 版本、`README.md` 更新日志；本次为纯 Bug 修复（行为与设计意图一致），不需要改动 `design_docs/` 玩法资料。
- **兼容性**：`set_user_busy` 的 SQL 语义变化依赖 `user_cd.user_id` 的唯一约束（既有表结构），无迁移需求；无对外 API 变更。

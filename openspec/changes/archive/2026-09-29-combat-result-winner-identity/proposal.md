# combat-result-winner-identity

## Why

`CombatResult.winner: str  # user_id or "draw"`（`managers/combat_manager.py:183`）把敌人身份编码——`EnemyManager` 生成敌人的 `enemy_`/`guardian_` 前缀约定——泄漏给每个调用方：两处运行时读取点各自做 `isinstance(winner, str)` 防御 + `winner.startswith("enemy_")` 前缀解析（`managers/pve_combat_manager.py:236,274`，全仓仅此两处）。该编码已造成一次 shipped bug：定向组妖兽 `guardian_` 前缀被 `enemy_` 前缀判定误判为玩家胜利，修复靠 `challenge_rift_beast` 全量特殊化显式比较（`pve_combat_manager.py:409-418` 注释自证；`openspec/changes/archive/2026-09-05-add-rift-encounters/design.md:11,72` 记录了「新挑战方法不得沿用前缀判定」的补丁式约定）。引擎在 `combat_manager.py:352-374` 已持有 FighterState↔侧的完整映射，「谁赢」本应是查询而非解析。

## What Changes

- `CombatResult` 重构：删除 `winner: str`，新增 `winner_side: Literal["fighter1", "fighter2", "draw"]`（权威判定）与 `winner_id: str | None`（便捷字段，平局为 `None`；引擎持有 FighterState，成本为零）。纯重构，**战斗行为、战报文本、胜负口径逐位不变**。
- 运行时调用点全部改查询/显式比较，删除前缀解析与 isinstance 防御：`managers/pve_combat_manager.py`（`_calculate_rewards` :236、`_format_combat_result` :274、`trigger_pve_combat` legacy dict :357、`challenge_rift_beast` :412-413、`challenge_legacy_guardian` :467-468）、`managers/boss_manager.py:446,494,527`、`managers/impart_pk_manager.py:115,119`、`CombatManager.player_vs_player` legacy dict（`combat_manager.py:1529`）。
- `design_docs/attribute-growth/` 下 4 个直接加载引擎且读取 `result.winner` 的模拟脚本（`sim_route_matchup.py`、`sweep_route_growth.py`、`sim_balance_regression.py`、`sim_xiuxian_turns.py`；`rebalance_equipment.py` 调用引擎但不读 winner，不受影响）的 `result.winner` 读取同步改 `winner_side`（数值输出不变，保证校准留档可复现）。
- 构造 `CombatResult(...)` 或断言 `result.winner` 的测试（`test_combat_engine.py`、`test_combat_report_structure.py`、`test_trigger_effect_extensions.py`、`test_rift_encounters.py:486` 桩、`test_boss.py`、`test_pve_combat.py`）随字段改名更新。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 — 已核查 `openspec/specs/`：`combat-core` 的「胜负判定」需求（`spec.md:115-132`）定义战斗结束与免死语义，**未定义 winner 字段的类型或身份编码**；`rift-encounter`（:88,112）、`impart-system`（:55,84-88）只定义胜/平的玩法后果，同样不涉及结算接口编码。本 change 不修改任何需求级行为，为纯重构。故 `.openspec.yaml` 设 `skip_specs: true`。）

## Impact

- **代码**：`managers/combat_manager.py`（CombatResult 字段 + `resolve_combat` :352-388 赋值 + legacy dict :1529）；`managers/pve_combat_manager.py`（5 处）；`managers/boss_manager.py`（4 处：读 :446/:452/:494 + legacy dict :527）；`managers/impart_pk_manager.py`（2 处）。
- **design_docs 脚本**：`attribute-growth/` 4 个模拟脚本的胜者读取（`rebalance_equipment.py` 不读 winner，除外；输出数值不变，仅判定读取改写）。
- **测试**：6 个测试文件的 CombatResult 构造/断言；全量 pytest 须绿。
- **无**数据库迁移、无配置变更、无用户可见行为变化；前缀约定（`enemy_`/`guardian_`）保留在 `EnemyManager` 内部，只是不再跨 seam 泄漏。
- **并发变更提示**：`busy-state-owner` / `add-transaction-unit-of-work` 若先合入会移动 `pve_combat_manager.py` 以外文件行号；本 change 实施前按当时代码重新锚定。

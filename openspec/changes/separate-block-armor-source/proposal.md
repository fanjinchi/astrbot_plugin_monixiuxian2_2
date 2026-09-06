# Proposal: 格挡率来源分离（防具护甲退出格挡判定）

## Why

当前格挡率公式 `5% + 总护甲 × 0.001`（`managers/combat_manager.py` `_calc_block_rate`）把**防具护甲**也计入格挡率。随着防具内容设计（armor-content-design）引入随等级线性增长的防具供给曲线（40 级重甲护甲 ≈167），格挡率将蠕升至 ~22%，与护甲减伤（r≈25%）乘算后总减伤 ~33%，再叠任意 15% 减伤技能即突破 40% 总减伤上限至 ~43%——既顶穿天花板，又让体修的护体类减伤技能毕业即作废，build 多样性被装备杀死。格挡是独立结算层（减半在护甲减伤之前，不吃 40% 上限），两个系统不该耦合缩放。必须在防具供给曲线上线之前先把格挡来源解耦。

## What Changes

- **BREAKING（战斗行为）**：格挡率公式改为只统计「天生护甲（角色面板护甲）+ 武器护甲」，防具槽位提供的护甲不再提升格挡率。公式变为 `格挡率 = min(5% + (天生护甲 + 武器护甲) × 0.001, block_cap)`。
- 战斗引擎在构建 `FighterState` 时需分开携带武器护甲与防具护甲两个分量（当前 `core/equipment_manager.py` 合并为单一 armor_value），减伤结算仍用合并值，格挡判定用分量。
- 同步更新 `design_docs/attribute-growth/growth-balance-proposals.md` §3.3 的格挡描述（当前写"保留不变"，需修正为来源分离后的规则）。
- 主 spec `combat-core` 增加格挡率来源的正式规约（当前格挡公式只在 design_docs 与代码中存在，openspec 侧无规约）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `combat-core`: 在回合制判定链规约中新增/明确格挡率来源要求——格挡率只由天生护甲与武器护甲贡献，防具护甲不参与；格挡仍为独立结算层（伤害减半、不受 40% 总减伤上限约束、受 block_cap 触发率上限约束）。

## Impact

- **代码**：`managers/combat_manager.py`（`_calc_block_rate`、`FighterState` 构建/装备属性汇总处）；`core/equipment_manager.py`（armor_value 合并逻辑需保留分量信息）。
- **配置**：`config/game_config.json` 战斗参数无需变更（block_cap 不变）。
- **文档**：`design_docs/attribute-growth/growth-balance-proposals.md` §3.3、`design_docs/current-design-report.md` 防御公式节。
- **测试**：`tests/` 战斗引擎相关用例需补格挡来源断言（同护甲总量下，护甲来自武器 vs 防具时格挡率不同）。
- **玩家可感知影响**：极小——当前全游戏防具仅 3 件占位（armor_value 1/10/25），格挡率变化 ≤1pp。
- **后续依赖**：armor-content-design 变更依赖本变更先行落地（防具供给曲线以格挡解耦为前提）。

# Design: 格挡率来源分离

## Context

当前护甲数据流：`Player.armor_value`（天生）+ 各装备 `Item.armor_value` 在 `Player.get_total_attributes()`（`models.py:258`）合并为单一 `total["armor_value"]`，战斗引擎构建 `FighterState.armor_value`（`managers/combat_manager.py:337`）后同时喂给两处：减伤 `_apply_armor_and_reduction`（:1290）与格挡 `_calc_block_rate`（:1249）。减伤需要合并值，格挡需要分量——解耦点就在属性汇总层。

约束：`route-identity.md` 校准过的跨路线胜率（满级 50%）依赖当前格挡公式在**低护甲**下的行为；当前防具护甲全服仅 1/10/25 三档，本变更对现网行为影响 ≤1pp 格挡率，属于趁内容空白期做的低成本解耦。

## Goals / Non-Goals

**Goals:**

- 格挡率只统计天生护甲 + 武器护甲；防具护甲全额保留在减伤结算中。
- PvE 敌人（cfg 构建的 FighterState）语义不变：其护甲视为"天生"，仍参与格挡。
- 主 spec combat-core 获得格挡来源的正式规约。

**Non-Goals:**

- 不改格挡触发上限（block_cap 30%）、不改减伤公式与 40% 上限、不改战力公式（护甲//2 仍用合并值）。
- 不做防具内容设计（armor-content-design 变更的职责）。
- 不调整创角护甲区间与路线成长表。

## Decisions

**D1：在 `get_total_attributes` 返回中新增 `block_armor_value` 键，而不是在战斗引擎里反推装备来源。**
汇总层是唯一知道每件装备 `item_type` 的地方（`Item.item_type == "armor"` 即防具槽）；战斗引擎只拿到聚合数字，反推不可得。`block_armor_value = 天生 armor_value + 武器槽 item.armor_value`（功法/心法槽理论上无 armor_value，如有也不计入——风味定位：格挡来自肉身功夫与持械卸力）。
备选：在 FighterState 上挂"逐槽 armor 明细"。否决：引擎不需要逐槽信息，单标量足够，明细增加构建成本与测试面。

**D2：FighterState 新增 `block_armor_value: int = 0` 字段，cfg 构建路径默认回退 `armor_value`。**
PvE 敌人/测试 mock 走 cfg 构建（:397-418），其护甲语义等同天生护甲；默认 `block_armor_value = cfg.get("block_armor_value", armor_value)` 保持现网 PvE 行为逐点不变，只有玩家构建路径（:327-337）传入分离值。

**D3：`_calc_block_rate` 改用 `defender.block_armor_value`，系数 0.001 与 5% 基础不变。**
不改系数的原因：创角护甲 3-10 与武器护甲（现 weapons.csv 挂 armor_value 的件，如青铜剑 15）共同贡献的格挡率上限约 5%+2.5%=7.5%，天然远离 30% cap，无需重新校准；改动越小，对 route-matchup 校准结论的扰动越小。

## Risks / Trade-offs

- [漏改某个 FighterState 构建路径导致格挡率静默归零] → 字段带默认值 0 且 cfg 路径显式回退；补测试断言两条构建路径的格挡率。
- [未来给功法/心法挂 armor_value 时语义含糊] → 在设计文档与 spec 中固定语义：仅武器槽装备护甲计入格挡，其余槽位护甲只减伤。
- [与 armor-content-design 并行开发时接口漂移] → 本变更先行落地，armor-content-design 的预算校验（总减伤 ≤40%）以其为前提。

## Migration Plan

纯代码 + spec 变更，无数据库/配置迁移。步骤：models.py 汇总层加键 → FighterState 加字段与两条构建路径接线 → `_calc_block_rate` 换源 → 补测试 → 更新 design_docs 两处描述 → 复跑战斗测试与 `sim_route_matchup.py` 确认满级跨路线胜率仍在 50%±2。回滚 = revert 本变更（无持久化状态）。

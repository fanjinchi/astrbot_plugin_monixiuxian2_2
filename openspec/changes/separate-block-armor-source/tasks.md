# Tasks: 格挡率来源分离

## 1. 属性汇总层

- [x] 1.1 `models.py` `Player.get_total_attributes()` 返回值新增 `block_armor_value` 键：天生 `armor_value` + 武器槽装备（`item_type == "weapon"`）的 armor_value 之和（经路线乘区），防具/功法/心法槽不计入；更新 docstring

## 2. 战斗引擎

- [x] 2.1 `managers/combat_manager.py` `FighterState` 新增 `block_armor_value: int = 0` 字段
- [x] 2.2 玩家构建路径（`get_total_attributes` 调用处）接线 `block_armor_value=total_attrs["block_armor_value"]`
- [x] 2.3 cfg 构建路径回退 `block_armor_value = cfg.get("block_armor_value", armor_value)`，保持 PvE/测试行为不变
- [x] 2.4 `_calc_block_rate` 改用 `defender.block_armor_value`，系数与上限不变；同步 docstring

## 3. 测试

- [x] 3.1 补测试：同护甲总量下，护甲来自武器 vs 防具时格挡率不同（覆盖 specs/combat-core 三个 Scenario）
- [x] 3.2 回归：`uv run python -m pytest tests/ -v` 全绿

## 4. 文档与校准

- [x] 4.1 更新 `design_docs/attribute-growth/growth-balance-proposals.md` §3.3 格挡描述（"保留不变"改为来源分离规则）
- [x] 4.2 更新 `design_docs/current-design-report.md` 防御公式节并修正已漂移的行号引用
- [x] 4.3 复跑 `uv run python design_docs/attribute-growth/sim_route_matchup.py`，确认满级跨路线胜率 50%±2（预期无变化，留档）
- [x] 4.4 `uv run ruff format . && uv run ruff check .` 通过
- [x] 4.5 按 AGENTS.md §7 更新 `metadata.yaml` version 与 `README.md` 更新日志（战斗行为变更，/修仙帮助 无指令变化可不更新）

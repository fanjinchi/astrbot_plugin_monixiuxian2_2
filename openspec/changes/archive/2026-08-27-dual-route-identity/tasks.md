# Tasks: dual-route-identity

## 1. 成长表配置与代码

- [x] 1.1 `config/game_config.json` 增加 `growth_by_route` 结构（体修/灵修 × 4 境界段），数值以 design.md D1 锚点起步
- [x] 1.2 `core/breakthrough_manager.py` 成长发放改为按路线 + 大境界段读表，缺失时回退全局权重；同步更新 docstring 与注释
- [x] 1.3 补充/更新 `tests/test_breakthrough_manager.py`：覆盖两路线各段取表、回退路径
- [x] 1.4 **C1（校准后追加，用户已批准）**：灵修创角迅捷区间 5-15 → 10-18（`core/cultivation_manager.py`）；attribute-numerics delta spec 增加创角差异化场景

## 2. 数值校准（用户检查点）

- [x] 2.1 新增 `design_docs/attribute-growth/sim_route_matchup.py` 路线对抗模拟（原 `sim_xiuxian_turns.py` 场景 A/B 已随公式化配置过时，故新建脚本复用其引擎与装备解析，不修复旧场景）
- [x] 2.2 跑校准：8/8 格 PASS（含 L30 armed 占位武器伪影告警），报告归档 `route-matchup-report.md`；初版锚点数值因迅捷收益过强被推翻，定稿见 design.md D1
- [x] 2.3 **用户 review 校准报告**：批准 C1 方向与练气段上限放宽至 62%（2026-08-26），随后按 C1 定稿重校通过

## 3. 内容规范

- [x] 3.1 内容规范落盘 `design_docs/content-design/route-identity.md`（路线定位/成长定稿/三族系数/机制预算表/检查清单），并从 content-design README 与 design_docs 总清单建立入口
- [x] 3.2 `validate_budget.py` 增加机制预算检查 `check_weapon_mechanics_band`（武器挂载触发技：练气段仅直接增伤/减伤、筑基及以下禁状态效果）与三族系数检查 `check_route_multipliers`；skills.csv 段位纪律经心法等级门禁人工落实
- [x] 3.3 **用户 review 规范文档**：修订三族系数为奖小于罚（1.2~1.4 / 0.5~0.7），存量 21 条功法按新规范迁移（CSV + config 手工同步， reconcile 地雷登记 bd bx8）
- [x] 3.4 （迁移附带）skills.csv 21 行路线系数迁移至新三族规范，`config/skills.json` 手工同步同值

## 4. 收尾

- [x] 4.1 更新 `design_docs/current-design-report.md` 创角区间与成长规则章节
- [x] 4.2 `uv run ruff format . && uv run ruff check . && uv run python -m pytest tests/ -v` 全绿（521 passed；validate_budget 0 FAIL；openspec validate 通过）
- [x] 4.3 metadata v3.12.0 + README 更新日志（无新指令，帮助文本无需变更）

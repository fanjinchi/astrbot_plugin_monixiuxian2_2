# unify-combat-power-formula

## Why

「战力」公式当前以逐字重复的内联表达式存在于两处代码（`managers/ranking_manager.py`、`handlers/player_handler.py`），且 `AGENTS.md` §8 与 `README.md` 历史 changelog 记载的却是已被 `openspec/specs/attribute-numerics` 明令废弃的旧公式（含「精神力」）。行为契约（attribute-numerics 战力公式需求）没有单一实现点可指，每次平衡调整需多处狩猎，文档与代码持续漂移。

## What Changes

- 在 `models.py` 的 `Player` 上新增深方法 `combat_power(equipped_items, pill_multipliers=None) -> int`：唯一实现 `伤害 + 身法 + 迅捷 + 气血 + 护甲值//2`（含装备与心法，可选含临时丹药倍率；格挡护甲不计入）。纯重构，**行为不变**。
- 两处调用点（排行榜 / 玩家信息面板）收缩为单行调用。
- `AGENTS.md:127` 整行（含「已在 ranking_manager.py 和 combat_manager.py 中统一」的错误声称）改为指针式约定，指向 `design_docs/current-design-report.md` 与代码符号，不再内联公式文本；`README.md:799`/`:830` 历史 changelog BUG 修复表（v2.9.3 / v2.9.2，非"已知问题表"）中的过时旧公式行加历史注记而非改写历史（实际文本为 `物伤+法伤+物防+法防+精神力/10`，缺陷是"物防+法防"对重复出现两次）。
- `design_docs` 中带「权威实现在 ranking_manager」实现引用的位置改指 `models.py`：`current-design-report.md:214`、`api-overview.md:91`；`current-design-report.md:455`（附录公式汇总）与 `project-architecture.md:85` 仅含公式文本无实现引用，核对即可。
- `tests/test_models.py` 补战力公式单测：含/不含丹药倍率两分支、护甲//2 取整行为（复用该文件既有的 `load_package_module` 导入 shim）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 — 纯重构：战力公式行为契约已在 `attribute-numerics` 战力计算公式需求中定义，本变更不修改任何需求级行为。故 `.openspec.yaml` 设 `skip_specs: true`。）

## Impact

- **代码**：`models.py`（+方法）、`managers/ranking_manager.py`、`handlers/player_handler.py`（各 -5 行内联表达式）。
- **文档**：`AGENTS.md` §8、`README.md` :799/:830 历史 changelog 行（注记方式）、`design_docs/current-design-report.md`（:214 改引用，:455 核对）、`design_docs/api-overview.md`（:91）、`design_docs/project-architecture.md`（:85 核对）。
- **测试**：`tests/test_models.py` 新增战力断言（此前全仓无任何战力数值测试）。
- **无**数据库迁移、无配置变更、无对外行为变化。

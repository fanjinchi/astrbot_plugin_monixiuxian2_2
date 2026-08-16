## Why

bd `dhh`（功法修复后数值配平）在 `skill-engine-fit-and-content-sync` 修复触发键 bug 后一直 open：修复让原本静默的触发技/大招突然满效，旧配置里的部分功法超出 G2 预算。虽然内容重做已替换/降级了旧功法，但仍需一次正式审计来关闭该 issue 并固化预算规则。

bd `f4t`（心法 `route_mult` 机制）同样 open：功法/武器已有路线倍率，但心法被动加成尚未按修炼路线乘算，导致路线差异化不完整。需要把 `route_multiplier` 字段落地到心法配置和属性计算中。

两个 issue 都围绕「技能/心法内容设计与数值框架对齐」，合并处理可以减少反复重载配置和回归测试的成本。

## What Changes

- **审计并关闭 bd `dhh`**：
  - 对比现有 `config/skills.json` 与 `design_docs/content-design/skills.csv`，确认旧 6 功法（御剑术、万剑归宗 3.0 档、开天辟地等）已被替换或数值已降到 G2 预算内。
  - 运行 `validate_budget.py` 与 `sync_content_to_config.py --dry-run`，确保当前全部功法通过预算闸门。
  - 在 bd 中关闭 `dhh`，如仍有个别超标则本次调整。

- **实现 bd `f4t`（心法路线倍率）**：
  - 在 `config/heart_methods.json` 与 `design_docs/content-design/heart_methods.csv` 增加 `route_multiplier.灵修` / `route_multiplier.体修` 字段（v1 池全部 1.0，未来 v2 路线专属心法再差异化）。
  - 修改 `models.py` 的 `get_total_attributes`，在 `main_technique` 分支读取心法 `route_multiplier`，按 `player.cultivation_type` 对 `passive_bonus` 的百分比项与 `armor_value` 平加项同时乘算。
  - 同步更新 `sync_content_to_config.py` 的 CSV→JSON 契约，确保新字段正确入库。
  - 新增/更新测试覆盖：路线匹配、倍率计算、缺省值 1.0、armor_value 也乘 route_mult。

## Capabilities

### New Capabilities

- 无新增独立 capability；本次变化属于既有 skill-system 的能力扩展。

### Modified Capabilities

- `skill-system`：
  - 扩展「心法属性被动常驻生效」要求：心法被动加成（百分比项与 armor_value 平加项）须按修炼路线与心法的 `route_multiplier` 乘算。
  - 扩展「路线装备池」要求：心法作为装备池核心，其被动效果须体现灵修/体修路线差异。

## Impact

- `config/heart_methods.json`：新增 `route_multiplier` 字段。
- `design_docs/content-design/heart_methods.csv`：新增 `route_mult_ling`、`route_mult_ti` 列。
- `models.py`：`get_total_attributes` 主修心法分支逻辑变更。
- `scripts/sync_content_to_config.py`：入库契约扩展以携带 `route_multiplier`。
- `tests/`：新增/更新心法路线倍率测试。
- bd issue：`dhh` 关闭、`f4t` 关闭（`cti`/`ehd` 的重复问题不在本次范围）。

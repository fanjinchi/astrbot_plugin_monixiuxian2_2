## Context

功法与武器已经具备路线倍率（`route_multiplier`），并在战斗/属性计算中按 `player.cultivation_type` 生效。心法虽然也有 `route` 字段做装备校验，但被动加成（`passive_bonus`）尚未按路线乘算，导致同一路线专属心法的差异化只停留在「能不能装备」，没有数值差异。

`models.py` 的 `Player.get_total_attributes` 已按装备条目逐个应用 `Item.route_multiplier` 到四维属性与 `armor_value`；心法分支（`item_type == "main_technique"`）目前只读取 `passive_bonus` 的百分比/平加项，未再乘路线倍率。本变更把功法/武器的同构逻辑扩展到心法被动。

bd `dhh` 则是触发键 bug 修复后的遗留：旧配置里部分功法触发概率/大招数值超出 G2 预算。当前 `skills.csv`/`config/skills.json` 已经过一轮内容重做，需要一次正式审计来确认全部通过 `validate_budget.py` 并关闭 issue。

## Goals / Non-Goals

**Goals:**
- 关闭 bd `dhh`：确认当前功法池通过预算闸门，无超预算条目。
- 关闭 bd `f4t`：让心法被动加成按 `route_multiplier` × `cultivation_type` 生效。
- 同步更新配置、设计表、同步脚本、测试与 bd issue 状态。

**Non-Goals:**
- 不修改战斗触发技/大招的结算链本身（只动内容数值与心法被动）。
- 不新增心法内容（v1 池 18 个已足够，`route_multiplier` 全部填 1.0，未来 v2 再差异化）。
- 不做武器变体扩展或心法 `final` 状态批量切换（属于 `hz7` 后续工作）。
- 不处理 `cti`/`ehd`（「把平衡配置固化到 `default_configs.py`」）——该任务超出本次范围，不在本 change 中关闭或修改。

## Decisions

### 0. `route` 与 `route_multiplier` 语义必须区分

- `route`：装备校验字段，决定某条修炼路线的玩家**能不能**装备该心法（如 `route=体修` 的心法灵修玩家不可装备）。
- `route_multiplier`：数值倍率字段，决定该心法被装备后，其被动加成**按多少倍率生效**。
- 两者独立：一个心法可以 `route=通用` 但 `route_multiplier.体修=1.2`（未来 v2 路线专属心法）；也可以 `route=体修` 但 `route_multiplier` 全 1.0（当前 v1 池）。
- 本变更只新增 `route_multiplier` 字段及其在被动计算中的消费，不改动 `route` 的装备校验逻辑。

### 1. 心法路线倍率字段采用与功法/武器同构的 JSON 对象

- **方案**：`route_multiplier: {"灵修": 1.0, "体修": 1.0}`。
- **理由**：与现有 `Item.route_multiplier`、`config/skills.json` 的 `route_multiplier` 字段命名与结构一致，减少心智负担；`Item.get_route_multiplier(route)` 可直接复用。
- **替代方案**：在心法上加 `route_mult_ling` / `route_mult_ti` 两个独立字段。拒绝理由：破坏配置一致性，同步脚本需要额外分支。

### 2. 路线倍率在心法被动上的应用顺序

- **方案**：先计算基础装备四维加成，再对心法的百分比被动乘 `route_multiplier`；对 `armor_value` 平加项也乘 `route_multiplier` 后累加。
- **理由**：与武器/武器词条的结算方式一致（`int(item.damage * mult)`）；`armor_value` 平加项也乘符合用户 2026-08-06 m00197 拍板（bd `f4t` notes）。
- **示例**：
  - 灵修玩家装备 `damage_percent=0.12`、`route_multiplier.灵修=1.0` 的烈火功：`damage = int(damage * (1 + 0.12 * 1.0))`。
  - 体修玩家装备 `armor_value=20`、`route_multiplier.体修=1.0` 的战神诀：`armor_value += int(20 * 1.0)`。
  - 未来某体修专属心法 `route_multiplier.体修=1.2`、`hp_percent=0.1`：等效 +12% HP。

### 3. 缺省值 1.0，未声明时不报错

- **方案**：`Item.get_route_multiplier` 已在非法/缺省时返回 1.0；心法配置统一填 1.0，但代码不强制要求该字段存在。
- **理由**：向后兼容，避免历史/测试数据必须立刻补字段；同时让未来 v2 路线专属心法可以只改数值就生效。

### 4. dhh 关闭前先跑预算闸门，不手动逐个核算

- **方案**：以 `design_docs/content-design/validate_budget.py` 的 0 FAIL 为通过标准；同时 `sync_content_to_config.py --dry-run` 无删除异常。
- **理由**：设计文档已经把预算规则脚本化，审计应依赖机器闸门而非人工抽查。

## Risks / Trade-offs

- **[Risk] 路线倍率会放大百分比被动，可能导致某些组合超标**  
  → Mitigation：v1 池全部 1.0，等效无变化；测试覆盖未来 1.2 倍场景，确保计算正确。

- **[Risk] `armor_value` 平加项乘 route_mult 后，低等级玩家护甲收益变化**  
  → Mitigation：v1 倍率为 1.0，数值不变；后续设计 v2 时再用 `validate_budget.py` 校验 armor 贡献。

- **[Risk] 同步脚本漏带 `route_multiplier` 导致配置与代码不同步**  
  → Mitigation：扩展 `sync_content_to_config.py` 的 heart_methods 契约，加 assert/测试验证入库后字段存在。

- **[Risk] 旧 `default_configs.py` 没有心法 route_multiplier，新代码读取缺省 1.0 无影响，但设计一致性下降**  
  → Mitigation：本次不处理 `cti`/`ehd` 的固化工作（超出范围）；后续固化配置到 `default_configs.py` 时一并处理。

## Migration Plan

1. 修改 `config/heart_methods.json` 与 `design_docs/content-design/heart_methods.csv`，增加 `route_multiplier`（v1 全 1.0）。
2. 修改 `scripts/sync_content_to_config.py` 的 heart_methods 处理，写入 `route_multiplier`。
3. 修改 `models.py` `get_total_attributes` 主修心法分支。
4. 跑 `uv run python scripts/sync_content_to_config.py` 生成最终 JSON。
5. 跑 `uv run python design_docs/content-design/validate_budget.py` 确认 0 FAIL。
6. 跑 `uv run python -m pytest tests/ -v` 确认全绿。
7. 在 bd 中关闭 `dhh`、`f4t`。

## Open Questions

无。两个待决策点（armor_value 是否乘 route_mult、缺省值行为）已由 bd `f4t` notes 和用户历史拍板确定。

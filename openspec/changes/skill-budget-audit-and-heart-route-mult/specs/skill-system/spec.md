## MODIFIED Requirements

### Requirement: 心法属性被动常驻生效（按修炼路线乘算）

心法携带的属性被动 SHALL 在装备期间常驻生效（加成四主属性或其派生），无需战斗中触发判定。卸下心法 SHALL 立即移除其被动加成。

心法配置中的 `route_multiplier`（含 `灵修` / `体修` 两个值，缺省均为 1.0）SHALL 在心法被动生效时按玩家当前修炼路线（`cultivation_type`）选取对应倍率，对被动加成进行乘算：

- 百分比类被动（如 `hp_percent`、`damage_percent`）SHALL 先计算基础百分比，再乘以路线倍率作为最终生效百分比。
- 平加类被动（如 `armor_value`）SHALL 先取配置值，再乘以路线倍率作为最终生效值。

`exp_multiplier` 不属于 `passive_bonus` 的百分比/平加项，系统 MUST NOT 对其应用 `route_multiplier`，修炼速度倍率 SHALL 保持按配置原值生效。

未声明 `route_multiplier` 或声明不全时，系统 SHALL 按 1.0 处理（无加成）。该倍率机制 MUST 与功法/武器已有的路线倍率语义一致。

#### Scenario: 灵修玩家装备灵修向心法获得额外加成

- **WHEN** 灵修玩家装备心法【烈火功】，其 `route_multiplier.灵修 = 1.0`、`route_multiplier.体修 = 1.0`
- **THEN** 该心法被动 `damage_percent = 0.12` 按灵修倍率 1.0 结算，最终 +12% 伤害

#### Scenario: 体修玩家装备体修向心法获得额外加成

- **WHEN** 体修玩家装备心法【龟息功】，其 `route_multiplier.体修 = 1.0`
- **THEN** 该心法被动按体修倍率 1.0 结算；若未来某心法 `route_multiplier.体修 = 1.2`，则同被动最终 +20% 效果

#### Scenario: 心法缺省路线倍率无加成

- **WHEN** 某心法未声明 `route_multiplier`
- **THEN** 系统按 `灵修 = 1.0`、`体修 = 1.0` 处理，被动效果不因此变化

#### Scenario: 卸下心法立即移除路线倍率加成

- **WHEN** 玩家将当前装备的心法卸下
- **THEN** 该心法提供的全部被动加成（含路线倍率放大后的部分）立即从玩家属性中移除

#### Scenario: exp_multiplier 不受路线倍率影响

- **WHEN** 玩家装备声明了 `exp_multiplier = 0.08` 与 `route_multiplier.灵修 = 1.2` 的心法
- **THEN** 玩家修炼速度倍率仍为 +8%，不按路线倍率放大

## ADDED Requirements

### Requirement: 心法配置携带路线倍率字段

`config/heart_methods.json` 与 `design_docs/content-design/heart_methods.csv` SHALL 为每个心法定义 `route_multiplier` 对象，至少包含 `灵修` 与 `体修` 两个键，值为浮点数。v1 心法池可全部设为 1.0，保留字段为未来路线专属心法提供扩展点。

#### Scenario: 同步脚本正确入库路线倍率

- **WHEN** 运行 `uv run python scripts/sync_content_to_config.py`
- **THEN** `config/heart_methods.json` 中每个心法条目均包含 `route_multiplier.灵修` 与 `route_multiplier.体修`

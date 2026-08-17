# Design: fix-functional-test-bugs

## Context

三个互相独立的小修复，涉及 `handlers/`、`data/`、`core/` 三层（动机见 proposal.md）。修复点已在测试中定位到具体函数：

- `handlers/combat_handlers.py:211` — `handle_spar` 在使用 `result` 前未赋值（`handle_duel` 在同文件 103–152 行有正确范式，调用 `self.combat_mgr.player_vs_player(p1, p2, combat_type=2)`）。
- `data/database_extended.py:423` — `set_user_busy` 仅 `UPDATE user_cd ... WHERE user_id=?`；表 `user_cd.user_id` 为 PRIMARY KEY（`data/migration.py:562`），具备 upsert 条件。同文件已有 `create_user_cd` 做 INSERT。
- `core/gm_manager.py:218` — `_item_exists` 只查 `config_manager.items_data` / `weapons_data`；`config_manager` 还加载 `pills_data`、`exp_pills_data`、`utility_pills_data`、`storage_rings_data`、`heart_methods_data` 等表（`config_manager.py:381–423`）。

## Goals / Non-Goals

**Goals:**

- 三处修复均为最小改动，不改变任何已通过测试的行为（PvP 效果矩阵 62/63 通过的结算路径不受影响）。
- 修复后 `pvp-basic-spar` 用例由预期失败转为通过；GM 可直接发放心法，无需 fixture 绕行。

**Non-Goals:**

- 不重构 `handle_spar`/`handle_duel` 的公共校验逻辑（ cooldown、状态检查虽有重复，但不在本次范围）。
- 不处理测试平台侧问题（事件队列延迟、能力缺口），那属于测试平台仓库的后续增强。
- 不为忙碌状态系统新增独立 spec；双层状态一致性是项目既定约定。

## Decisions

### D1: handle_spar 直接对齐 handle_duel 的调用范式

在 `handle_spar` 中 `p1`/`p2` 校验通过后、写回气血之前，补一行：

```python
result = await self.combat_mgr.player_vs_player(p1, p2, combat_type=1)  # 1=切磋
```

`combat_type` 取值以 `handle_duel` 的注释（`2=决斗`）及 `combat_manager.player_vs_player` 的参数约定为准，实现时先核对 `combat_type=1` 是否确为切磋语义。

**备选**：先初始化 `result = None` 再赋值——掩盖问题而非修复，且空结果会导致后续 `result["combat_log"]` 再抛 TypeError，不采纳。

### D2: set_user_busy 改为 upsert

```sql
INSERT INTO user_cd (user_id, type, create_time, scheduled_time, extra_data)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(user_id) DO UPDATE SET
  type = excluded.type, create_time = excluded.create_time,
  scheduled_time = excluded.scheduled_time, extra_data = excluded.extra_data
```

**备选**：保留 UPDATE 并检查 `rowcount == 0` 时 fallback 到 INSERT——两条语句、存在并发窗口，不如单条 upsert 原子；不采纳。
注意 `extra_data` 列由后续迁移添加，需确认该列在所有迁移路径的 `user_cd` 表上都存在（upsert 语句引用它）。

### D3: _item_exists 遍历配置管理器的全部物品类配置表

显式列出物品类数据表做存在性检查：`items_data`、`weapons_data`、`pills_data`、`exp_pills_data`、`utility_pills_data`、`storage_rings_data`、`heart_methods_data`（如还有 `skills_data` 等可给予类型一并纳入，以 `config_manager.load_all` 实际加载清单为准）。

**备选**：用反射遍历 `config_manager` 所有 `*_data` 属性——会把非物品表（如 `enemies_data`、`heart_methods` 之外的效果表）也纳入，语义不清；显式清单更可控，新物品类型需要 GM 发放时再加一行。

## Risks / Trade-offs

- [D1 中 `combat_type` 取值若与切磋语义不符，会按错误规则结算（如切磋产生决斗惩罚）] → 实现时先读 `combat_manager.player_vs_player` 的 `combat_type` 分支确认取值，并用 `pvp-basic-spar` 用例回归。
- [upsert 覆盖整行，`extra_data` 缺省传 `{}` 时会清掉旧行的 extra_data] → 与现 UPDATE 行为一致（现逻辑同样整体覆盖），风险可接受。
- [_item_exists 放开后 GM 可发放更多类型物品，若某类型储物戒不支持会有下游报错] → `store_item` 本身有失败返回与错误提示，不会静默写脏数据。

## Migration Plan

无数据库结构变更，无需迁移。部署方式为修改代码后在 AstrBot WebUI 重载插件，并重跑对应功能测试用例验证。

## Open Questions

无。

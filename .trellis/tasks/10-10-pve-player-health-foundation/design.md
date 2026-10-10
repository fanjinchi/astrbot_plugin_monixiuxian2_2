# Technical Design: 玩家持续气血领域与数据库迁移

## 1. Domain model

```text
persisted: base_hp, current_hp, health_recovered_at (or equivalent anchor)
runtime:   max_hp = aggregate(base_hp, equipment, technique, other bonuses)
invariant: 0 <= current_hp <= max_hp
```

模型和属性聚合层删除含混 `hp`。推荐把气血操作集中到 Health Domain：

- `get_health_snapshot(player, now)`：先惰性结算恢复，再返回 base/current/max；
- `clamp_current_hp(player)`：属性变化后维护 invariant；
- `apply_current_hp_change(...)` / 战后写回：唯一改变当前资源的通用边界；
- 永久成长调用显式的 base HP 操作，不复用 current API。

最终函数签名由实现阶段依现有类型风格确定，但语义、所有权和测试契约不得弱化。

## 2. Migration

本轮数据库链从 `LATEST_DB_VERSION = 34` 连续追加：A 固定为 v35（players health 列）；Persistence child 独占 v36…vN、同步 `_create_all_tables(...)` fresh DDL，C/D 只消费共享 schema/repository。测试必须证明 v34→latest 只走已注册 migration tasks、不进入 reset，且 `db_info.version` 仅在对应事务和必要 backfill 全成功后推进。

v35 首选 SQLite 原地 DDL：`ALTER TABLE players RENAME COLUMN hp TO base_hp`，再 `ADD COLUMN current_hp`、`ADD COLUMN health_recovered_at`（以及实现采用的 health version）。原地 DDL 保留既有列、PK/索引；若运行时 SQLite 能力检测不支持安全 rename，才进入显式 players table rebuild，实施计划必须列出完整 DDL/索引复制，迁移前后核对 row count、`PRAGMA table_info/index_list` 与 `PRAGMA foreign_key_check`，任一失败回滚且不推进版本。

旧 `hp` 只负责无损得到 `base_hp`。现有玩家的 `current_hp` 必须由迁移命令中的一次性 backfill service 读取同一检查点的玩家、装备、功法和有效加成，复用新的属性聚合计算迁移瞬间 `max_hp` 后初始化/钳制；不得用普通首次领域读取偷偷改值。schema + backfill 作为 v35 启用门，任一步失败都保持旧版本/恢复备份；迁移 `health_recovered_at = migration_now`，不猜测历史 idle/busy。

## 3. Lazy recovery

恢复锚点持久化，但不尝试从 `user_cd` 单行重建历史区间。Health Domain 暴露可加入现有外层事务的 transition hook：

- idle→busy：在 `BusyState.set_busy(...)` 写入新状态前，按 `[anchor, now]` 结算空闲恢复并把 anchor 推进到 `now`；
- busy→idle：在 `BusyState.clear(...)` 清除旧状态前，只把 anchor 推进到 `now`，不恢复 busy 时段；
- busy→busy：先按旧 busy 状态推进 anchor，再覆盖新状态；
- 普通 health read/write：按当前权威 `user_cd` 状态恢复或仅推进 anchor。

所有权威 `user_cd` 写入口都必须收敛到该转换 seam；禁止绕过 hook。按设计的 1%/分钟折算，舍入规则必须集中并经边界测试固定；current 已满时仍推进锚点。迁移初始化 anchor=`migration_now`，不对无法证明的旧历史补发恢复。

`players.state` 只作展示镜像，不参与权威计算。恢复锚点是“上次结算时刻”，不是等待到期时间戳，不登记 `TIME_SKIP_ENTRIES`。当前 GM `/时间快进` 只前移 registry 字段，因此测试应证明命令不改 anchor、也不增加恢复；`now - anchor` 的经过时长行为由可注入业务时钟单独测试。只有新增真正的恢复到期/冷却字段时才登记 registry。

## 4. Dependency handoff

本 child 完成后向其他 child 提供：

- 新 Player/schema 和动态 `max_hp` 聚合结果；
- 可在已有外层 DB transaction 中使用的 current HP 操作；
- busy-aware 惰性恢复与 time-skip；
- 已完成迁移且无旧 `hp` 的消费者清单与静态检查证据。

普通 PVE 与 Boss child 不得重新实现 clamp 或恢复；Integration 只复核组合后的调用图，不负责让基础迁移从红变绿。

## 5. Tests

覆盖 v34 fixture/fresh/idempotent/rollback；基础值与装备加成；上限下降 clamp；满血/部分血/busy/idle/restart/time-skip；并用静态搜索测试或显式断言阻止 `Player.hp` / 含混结果键回归。

# 玩家持续气血领域与数据库迁移

## Goal

建立无歧义、可迁移、可被所有战斗系统复用的玩家持续气血基座：`base_hp` 表示永久基础气血，`current_hp` 表示当前持久资源，动态 `max_hp` 表示属性加成后的运行时上限。

## Requirements

### R1. 权威字段与属性聚合

- 将 `Player.hp` 重命名为 `base_hp`，新增持久字段 `current_hp`；不提供 `hp` alias。
- `max_hp` 只由 `base_hp` 加装备、功法和其他有效加成计算，不以冗余列持久化。
- 突破只增长 `base_hp`；战斗、药品和恢复只改变 `current_hp`；任何读取当前血条或永久属性的代码必须显式选择语义。
- 对外属性快照不得继续暴露含混的 `hp` 键；动态上限统一命名为 `max_hp`。

### R2. 数据库迁移

- 将本轮数据库结构冻结为连续增量链：A 独占 v35（players health 列）；Persistence child 独占连续 v36…vN 和 fresh schema parity，C/D 只消费其 schema/repository；禁止版本空洞导致 v34 库落入 reset 路径。
- v35 优先在一个迁移事务中执行 `ALTER TABLE players RENAME COLUMN hp TO base_hp`，随后新增 `current_hp`、`health_recovered_at`（及实现所需 health version）；若目标 SQLite 不支持安全 rename，才采用完整 players 表重建，并显式保全全部列/索引、校验 row count 与 `PRAGMA foreign_key_check`。
- 旧 `players.hp` 无损成为 `base_hp`；`current_hp` 不在普通首次读取时偷偷补齐，而由 v35 迁移后的**一次性 backfill 服务**使用装备、功法及有效加成聚合迁移瞬间的合法动态 `max_hp`，在同一受控迁移检查点初始化/钳制；backfill 未成功不得推进 v35 或启用新模型。
- 迁移须覆盖 fresh install、v34→v35 不进入 reset、版本仅在 schema+backfill 全成功后推进、重复启动幂等、异常回滚、row count/foreign key 校验与旧玩家读取。
- 项目尚未上线，不做长期双写、兼容列或版本开关。

### R3. Health Domain

- 提供单一领域入口处理动态上限计算、current clamp、当前气血读写、战斗快照和恢复结算。
- `current_hp` 在属性上限下降后钳制到 `[0, max_hp]`；所有更新使用整数且不得产生负值或超上限。
- 领域 API 不直接耦合 handler 文案或具体 PVE/Boss 奖励。

### R4. 空闲恢复与时间快进

- 仅玩家不处于 `user_cd` 权威活动状态时，按每分钟动态 `max_hp` 的 1% 惰性恢复；不创建 per-player 常驻定时器。
- 现有 `user_cd` 每人只有一行且转换会覆盖/清空，不能事后重建活动区间；因此 `BusyState.set_busy(...)` / `clear(...)` 及其他权威 `user_cd` 写入口必须在同一外层事务中先调用 Health Domain 结算旧状态并把持久恢复锚点推进到转换时刻，再写新状态。busy 期间只推进锚点、不恢复，idle 期间才恢复。
- 普通读取也按当前权威状态结算并推进锚点；重启和重复读取不得重复恢复。迁移时从迁移时刻建立锚点，不追溯猜测旧 busy/idle 历史。
- 恢复锚点属于经过时长基准而非等待到期字段，不登记 `TIME_SKIP_ENTRIES`。当前 GM `/时间快进` 只前移已注册 SQL 字段、不改变业务时钟，故必须验证该命令不修改锚点且不额外产生恢复；经过时长恢复另由可注入业务时钟测试。只有新增真正的恢复到期/冷却字段时才由字段属主登记 registry。

### R5. 子任务边界

- 本任务原子拥有模型、schema、属性聚合、Health Domain、所有现有 `Player.hp` / 含混属性键消费者的语义迁移，以及定向与全量回归；不能先删字段再把调用方修复推迟到集成 child。
- 创角、突破、装备、功法、丹药、商店、GM、PvP、现有 PVE/秘境/Boss 路径和展示代码都在本任务中显式改用 `base_hp`、`current_hp` 或 `max_hp`。普通 PVE/Boss 后续 child 可以替换流程，但不得接手修复一个不可运行的中间态。
- 集成 child 只做静态清零复核、领域组合、旧入口切流和父级验收，不再承担基础字段迁移。
- 普通 PVE 败场、疲劳、逃跑与世界 Boss 新事务分别由其领域 child 实施。

## Acceptance Criteria

- [ ] AC1：模型和 fresh schema 只有 `base_hp`、`current_hp` 两个持久语义，动态结果使用 `max_hp`；产品代码无 `Player.hp` 或兼容 alias。
- [ ] AC2：v34 fixtures 升级后旧永久气血值不丢失，`current_hp` 合法；fresh install、重复迁移和异常回滚测试通过。
- [ ] AC3：属性加成增减、突破、current clamp 以及创角/装备/功法/丹药/商店/GM/PvP/现有战斗/展示消费者测试证明三层所有权正确。
- [ ] AC4：空闲恢复按 1% maxHP/分钟工作；set_busy/clear 转换在同一事务结算旧状态并推进锚点，busy、idle、重启、重复读取、可注入时钟经过量、GM registry 不改锚点及上限变化边界测试通过。
- [ ] AC5：领域 API 可被普通 PVE 与世界 Boss 使用，不直接触发奖励或平台发送。
- [ ] AC6：定向测试及 `uv run ruff format .`、`uv run ruff check .`、`uv run python -m pytest tests/ -v` 通过。

## Out of Scope

- 普通 PVE pending/逃跑/疲劳结算。
- 世界 Boss 实例、次数和贡献台账。
- Step 7 奖励经济。

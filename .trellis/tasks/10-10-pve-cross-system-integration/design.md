# Technical Design: PVE 跨系统迁移与集成上线

## 1. Integration responsibility

本 child 不重建 Health、Catalog、Persistence、Adventure、Boss 五个前置模块，也不接手基础 HP 消费者迁移；它关闭旧入口、接线新流程并证明组合系统满足父 AC。**唯一新增的领域职责是 PVE 气血地板收口**（2026-10-12 甲案：秘境兽 `challenge_rift_beast` 与传承守护者 `challenge_legacy_guardian` 沿用历练已定的 `ceil(1% * 动态 max_hp)` 战败地板、胜场不保底；PvP 不加地板；旧 `trigger_pve_combat`/`challenge_boss` 走退役不补），其余一律不新建。采用静态清单 + 端到端测试双重核对：每个旧 `hp` 命中必须已由 Health 归类/移除，每个旧 enemy/Boss 调用点必须被替换或注明专项兼容。

## 2. Cutover sequence

```text
backup/fixtures
  -> health v35 + all consumers already green
  -> persistence v36…vN parity/repositories already green
  -> catalog adapters validated (preview only; no draft sync)
  -> ordinary PVE/Boss services wired but production entry remains disabled
  -> combat/narrative approvals + manifest/hash
  -> explicit sync + profile verification
  -> one activation checkpoint: disable old ordinary/Boss entry + old poller/key, enable fixed roster + new poller
  -> full regression/docs
```

代码批准不自动越过“用户内容确认”门。若确认尚未发生，集成 task 可以完成到 disabled/config-fixture 状态并报告明确剩余 gate。

## 3. Verification matrix

- Health: create/breakthrough/equipment/technique/pill/shop/GM/PvP/PVE/rift/Boss/display；
- Enemy: ordinary categories + rift beast + legacy guardian；**floor 收口**：秘境兽/守护者战败残血 ≥ `ceil(1% * 动态 max_hp)`、胜场按引擎终值，且与历练走同一 Health Domain 入口（不得在 handler 侧另写一遍公式）；
- Ordinary PVE: direct/choice/flee success/flee failure/win/loss/restart/fatigue；
- Boss: spawn/stage/cross-day/3-attempt/concurrent kill/dissipate/respawn/per-destination outbox failure；旧 `boss_next_spawn_time` 不再生效，旧/new poller 不可同时运行；
- Time skip: fatigue、Boss expiry/respawn 到期字段走 registry；recovery anchor、pending、北京日期键不登记。GM 字段快进不改变恢复量/当日次数；经过量与跨日分别用可注入业务时钟验证。另验证 pending 无自动过期且 busy 可跨重启恢复/终态清除；
- Governance: draft/缺 manifest/hash 漂移/列范围越权拒绝；`combat_status` 与 `narrative_status` 独立批准后 deterministic sync、运行时 profile hash/count。

## 4. Rollback

内容批准前只验证 disabled/fixture 接线，不改变生产入口。批准并完成 sync/profile 验证后，记录数据库备份、generated config hash 和旧/新入口开关位置；同一激活检查点同时停止旧普通/Boss 入口与旧 poller、删除/忽略旧 `system_config.boss_next_spawn_time` 真相源，并启用固定 roster/new lifecycle poller。任一动作失败则不启用新入口并恢复旧入口；失败时恢复代码+DB+生成配置为同一检查点，不做跨 schema 版本部分回滚或长期双运行。

## 5. Documentation

架构文档描述深模块边界、事务/outbox 和字段所有权；状态报告区分“代码已就绪”“内容已确认/同步”“玩法已启用”；README/API 说明 current/max HP、逃跑和 Boss 次数/阶段，明确奖励经济仍待 Step 7。

# Implementation Plan: 玩家持续气血领域与数据库迁移

## Dependencies

- 无代码 child 依赖；这是普通 PVE 与世界 Boss 的前置基座。
- 实施前复核父任务设计和研究证据。

## Steps

1. **建立迁移 fixtures 与失败用例**
   - 固化 v34 players fixture（含装备/功法气血加成）、fresh schema、重复启动和异常回滚测试。
   - 先写能暴露旧 `hp` 双义的属性/当前血条契约测试，并断言 v34→latest 不进入 reset、版本仅在全成功后推进。
2. **实施 v35 schema、backfill 与 Player 模型**
   - 注册连续 v35 migration 并同步 fresh DDL；优先 rename+add column，兼容回退重建时逐项验证完整列/索引、row count 和 `PRAGMA foreign_key_check`。
   - 在迁移检查点运行一次性 dynamic-max backfill，再推进版本；不得把补齐推迟到普通首次读取。
   - 改为 `base_hp` / `current_hp`，删除 alias；调整数据库动态 SQL 映射。
3. **重构属性聚合并迁移全部现有消费者**
   - 永久值从 `base_hp` 出发，结果显式产出 `max_hp`。
   - 迁移创角、突破、装备、功法、丹药、商店、GM、PvP、现有 PVE/秘境/Boss 与展示调用；不留临时 alias 或等待 Integration 修复的红态。
4. **实现 Health Domain 与恢复锚点**
   - 集中 current HP 读写、快照、clamp 和惰性恢复。
   - 为 `BusyState.set_busy(...)` / `clear(...)` 及其他权威 `user_cd` 写入接入同事务 transition hook：转换前结算旧状态并推进 anchor；禁止用当前单行倒推历史活动区间。
   - 使用可注入业务时钟验证经过量恢复；另验证 GM `/时间快进` 不修改未注册的恢复锚点、也不因字段快进额外产生恢复。
5. **提供事务友好的 API 与完成证据**
   - 从 Health/BusyState 事务入口沿调用图审计到 player、inventory/equipment 与 `user_cd` 叶子；清除 `create_player(...)`、`update_user_cd(...)` 等裸 `commit()` 提前提交风险，统一 `_txn_depth == 0` gate 或直接 connection DML。
   - 用故障注入证明 player/health anchor/busy 状态在任意叶子失败时整体回滚，并确保普通 PVE/Boss 可在外层 transaction 内复用。
   - 建立静态清单，证明产品代码无 `Player.hp`、含混 `hp` 属性结果、事务内裸 commit 或绕过 transition hook 的 `user_cd` 写入。
6. **验证**
   - 运行迁移/health/消费者定向测试，再运行完整 ruff/pytest 质量门；本 child 必须独立为绿。

## Rollback Point

迁移执行前备份开发数据库。若迁移或全消费者集成未通过，回退代码并恢复备份；不支持新 schema 写入后再由旧版本原地读取。

## Completion Evidence

- schema/version 与模型 diff；
- v34→新版/fresh/idempotent/rollback 测试；
- health invariant 与恢复/time-skip 测试；
- 完整质量门日志摘要。

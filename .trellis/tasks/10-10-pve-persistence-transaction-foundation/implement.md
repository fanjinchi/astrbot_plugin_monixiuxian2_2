# Implementation Plan: PVE 持久化与事务基座

## Dependencies and Gate

1. Health child 已冻结 v35 DDL/backfill、Player/BusyState 事务契约。
2. Catalog 无数据库依赖，可并行。
3. Adventure 与 Boss child 只有在本任务 schema/repository contract 通过 Gate 后才能实现其持久层。

## Steps

1. **冻结版本矩阵**：记录 v35/v36/v37/v38 ownership，建立 v34、fresh 和逐版失败 fixtures；同步 fresh DDL。
2. **建立共享 schema**：依次迁移 settlement/effect/fatigue、Boss instance/attempt/ledger/contribution、business event/delivery，加入唯一键、FK、version 与 claim 字段。
3. **实现事务友好 repositories**：提供 insert-or-read、CAS、幂等冲突读取和 delivery/effect claim；不包含领域计算。
4. **审计并修复事务叶子**：扫描 `data/` 全部 `commit()`，沿四条原子调用图确认 ownership；修复 `create_player(...)`、`update_user_cd(...)`、旧 Boss CRUD 和任何新叶子。
5. **登记 time-skip providers**：Adventure fatigue 与新 Boss lifecycle 字段声明 `TIME_SKIP_ENTRIES` 并加入 `_PROVIDER_MODULES`；更新 fail-closed label/field 测试。明确 health anchor、pending、Beijing date key 不注册，GM 字段快进不重置日次数。
6. **故障/并发验证**：在每个叶子边界注错，跑 CAS/幂等/claim lease/uncertain/schema parity/v34 no-reset 测试。
7. **质量门**：运行定向测试及完整 ruff/pytest。

## Rollback Point

任何新版本迁移前备份开发数据库。schema/repository 尚未接入 handler/poller，可在 Gate 前回退代码和数据库；禁止只回退代码而保留更高版本 schema。

## Completion Evidence

- 连续版本/fresh schema 对照表；
- v34→latest no-reset 与逐版 rollback 日志；
- commit 调用图和静态审计清单；
- 原子故障注入/CAS/幂等测试；
- time-skip provider/field matrix；
- 完整质量门摘要。

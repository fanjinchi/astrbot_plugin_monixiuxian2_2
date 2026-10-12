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

### 执行记录（2026-10-13，Steps 1–7 全部完成）

- **版本矩阵/共享 schema**：`LATEST_DB_VERSION=38`；v36 settlement/effect/fatigue、
  v37 instance/challenge/daily_attempts/ledger/contribution、v38 business_events/event_deliveries；
  DDL builder 由 `@migration(36/37/38)` 与 `_create_all_tables` 共用（fresh==upgrade 锁定决策）。
  测试：`test_pve_persistence_foundation.py` 版本 ownership、fresh 建表、
  逐版 rewound-snapshot parity（N∈{36,37,38}）、v34→latest 数据保全、
  逐版注错回滚+重跑幂等。
- **repositories**：`data/pve_repository.py`（AdventureRepository/WorldBossRepository/
  OutboxRepository + `shanghai_date_key`）；insert-or-read 幂等、CAS、effect/delivery
  claim、`uncertain` 不自动回收、日次数单语句封顶。测试覆盖契约与 FK 违例。
- **事务叶子审计**：`data/` 裸 `commit()` 清零（allowlist 仅 owner 层 2 点），
  20 处按 `_txn_depth` 门控；`test_leaf_commit_defers_to_outer_transaction`
  用旁观连接验证外事务内不提前落盘；四条 §3 原子图故障注入全回滚。
  静态审计测试 `test_no_ungated_commit_in_data_layer` 常驻把关。
- **time-skip 注册**：boss_manager 增世界Boss到期/再生 2 条、adventure_manager 新声明
  疲劳条并登记 `_PROVIDER_MODULES`；注册表 14 条目/13 域
  （`test_time_skip_registry.py` 锚点同步，9 passed）；health 锚点、结算/效果历史、
  daily attempts、date_key 负向不覆盖断言在案；三条新 SQL 已在 v38 实库实测前移语义
  （fatigue_until/expires_at(state='active')/next_spawn_at(>0)）。
- **质量门**：`ruff format`（129 files unchanged）+ `ruff check`（core/data/handlers/
  managers/tests/utils/main.py 等 All checks passed）；
  `pytest tests/ -q` → **1092 passed**（基线 1057 + 本任务新增 35）。
- **遗留（不属本 child）**：`data/` 之外 6 处裸 `conn.commit()`
  （combat_handlers.py:75、spirit_farm_manager.py:144、spirit_eye_manager.py:79/187、
  bounty_manager.py:671、dual_cultivation_manager.py:164），归 children C/D/E 接入时处理，
  已用 bd 登记。

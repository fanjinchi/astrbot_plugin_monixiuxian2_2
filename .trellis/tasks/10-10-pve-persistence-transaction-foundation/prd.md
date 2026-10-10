# PVE 持久化与事务基座

## Goal

在普通 PVE 与世界 Boss 领域并行实现前，冻结一条不会重置 v34 数据库的连续迁移链、fresh schema、事务叶子规则、幂等基础表和时间快进矩阵，使后续 child 只实现领域命令而不各自重复发明数据库基础设施。

## Dependencies

- 玩家气血 child 先固定 v35 players health schema、模型和一次性 dynamic-max backfill 契约。
- 固定目录 child 可与本任务并行；普通 PVE 与世界 Boss child 必须在本任务完成后才开始持久层实现。

## Requirements

### R1. 连续版本与 fresh schema

- 当前 `LATEST_DB_VERSION = 34`；A 固定 v35 后，本任务为普通 PVE、世界 Boss、outbox 等结构分配连续 v36…vN，禁止版本空洞。
- 每个增量版本同步修改 `_create_all_tables(...)`；v34→latest 必须命中已注册 tasks，不得落入 reset/rebuild 数据清空路径。
- `db_info.version` 仅在该版 schema、约束、必要 backfill/校验全部成功后推进；失败完整回滚。
- 为 v34→latest、fresh→latest、逐版失败、重复启动、row count、索引/唯一约束与 `PRAGMA foreign_key_check` 建立 fixtures。

### R2. 领域基础表与约束

- 冻结普通 PVE settlement/effect consumption、Boss instance/version/attempt/ledger/contribution、business event 和 per-destination delivery 的最小 schema/唯一约束。
- 表必须支持 `adventure_run_id`、challenge/idempotency id、CAS version、`UNIQUE(consumer_name, settlement_id/effect_type)`、`UNIQUE(event_id, platform, group_id)` 等后续领域契约。
- 本任务只提供 repository/schema contract 和 fixtures，不实现逃跑、战斗、Boss 阶段或广播文案。

### R3. 事务叶子纪律

- 对 Health/BusyState、Adventure settlement、Boss challenge、ledger/outbox 全调用图做 `commit()` 静态审计；外层 `DataBase.transaction()` 内任何叶子不得提前提交。
- `create_player(...)`、`update_user_cd(...)`、旧 Boss CRUD 及新 repository 要么统一使用 `_txn_depth == 0` ownership gate，要么直接由领域 repository 使用 connection DML。
- player、busy、settlement、attempt、ledger、contribution、event/delivery 每个原子边界都要有故障注入，证明任意叶子异常时全量回滚。

### R4. 幂等、CAS 与 dispatcher 基础

- repository 提供 version/CAS 条件写和唯一键冲突读取接口，不在长写事务中运行 CombatEngine 或网络请求。
- effect/outbox claim 必须有 owner、lease、attempt、错误与状态；请求结果不确定的 delivery 可进入 `uncertain`，不得被通用 stale reclaim 当成安全重试。
- 不承诺外部平台 exactly-once，只保证领域事实唯一、逐 destination 隔离和可审计处置。

### R5. Time-skip 与业务日语义

- Adventure 字段属主声明 fatigue end 的 `TIME_SKIP_ENTRIES`；Boss 字段属主声明新 instance `expires_at` / `next_spawn_at` 条目；两者都登记进 `core/time_skip_registry.py` 的 `_PROVIDER_MODULES`，并更新 label/field 映射测试。
- health recovery anchor、PVE pending（首版无 expiry）和 Beijing date key 不注册为可前移时间戳。
- 现有 GM 时间快进只修改注册字段，不改变业务时钟；因此不会人为跨越 `Asia/Shanghai` 自然日、不会重置当日 Boss 次数。跨日测试使用可注入业务时钟。

## Acceptance Criteria

- [ ] AC1：版本映射明确且连续，v34→latest 不 reset；fresh/incremental schema、索引和约束一致，版本只在成功后推进。
- [ ] AC2：PVE/Boss/effect/outbox 最小表与唯一约束可被 C/D fixtures 独立复用，无领域行为越界。
- [ ] AC3：事务入口→叶子静态审计无未门控 commit；故障注入证明 player/busy/settlement/attempt/ledger/outbox 原子回滚。
- [ ] AC4：CAS、幂等冲突读取、claim lease 和 uncertain 状态的 repository 契约/并发测试通过。
- [ ] AC5：fatigue 与新 Boss 生命周期字段声明并注册 time-skip；静态 fail-closed 测试通过，health anchor/pending/date key 未被误注册。
- [ ] AC6：完整 ruff/pytest 质量门通过。

## Out of Scope

- 逃跑参数、普通 PVE 战斗结算、Boss 阶段/末击、外部广播 renderer。
- 正式内容 sync 与 Step 7 奖励经济。

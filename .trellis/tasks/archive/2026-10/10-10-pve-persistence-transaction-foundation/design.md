# Technical Design: PVE 持久化与事务基座

## 1. Version ownership

```text
v34 existing
  -> v35 Health: players hp rename/add columns + one-shot backfill
  -> v36 Persistence: adventure settlement/effect/fatigue
  -> v37 Persistence: Boss instance/attempt/ledger/contribution
  -> v38 Persistence: business event/per-destination delivery
```

实现阶段只有在发现 SQLite 约束要求拆分时才可把某一步继续拆为连续 v39…vN；不得改成非连续版本或把已发布版本复用为另一结构。每一版的 migration task 与 fresh DDL 同步，测试比较 `sqlite_master`/`PRAGMA table_info,index_list,foreign_key_list` 的规范化结果。

v35 仍由 Health child 拥有模型语义与 dynamic-max backfill；本任务从 v36 起拥有共享表和迁移链总验证，避免 C/D 并行修改同一个 `LATEST_DB_VERSION`/fresh schema 造成冲突。

## 2. Repository boundary

共享 persistence 层只暴露：

- insert-or-read by idempotency key；
- version/CAS update；
- transaction-joining player/busy/settlement/Boss/ledger/event DML；
- effect/delivery conditional claim 与状态转换。

领域状态机仍由 C/D services 拥有。repository 不运行 CombatEngine、不计算逃跑/阶段、不渲染消息，也不 await 网络。

## 3. Transaction ownership audit

建立机器可检索的 `commit()` 清单，并从每个领域事务入口画到叶子 helper：

```text
Health transition -> player + user_cd
Adventure terminal -> player + user_cd + settlement + fatigue + effects
Boss challenge -> player + attempt + instance + ledger + contribution + events
Dispatcher claim -> event/delivery state only
```

外层事务内叶子只能执行 DML；需要保留独立调用兼容的 helper 按 `getattr(conn, "_txn_depth", 0) == 0` 门控 commit。对 `create_player(...)`、`update_user_cd(...)` 和旧 Boss CRUD 做显式修复，不接受“上层通常会包事务”的假设。每条路径在最后一个写入前后注入异常，断言全表状态与调用前一致。

## 4. Idempotency and CAS

- Adventure：`adventure_run_id` 唯一；effect consumption 使用稳定 consumer/effect 唯一键。
- Boss：challenge key 唯一；instance 和 player health 有版本/CAS；CAS 失败只返回冲突/既有结果，不部分写入。
- Events：business event key 唯一；delivery 对 `(event_id, platform, group_id)` 唯一。
- Claim：`queued -> dispatching -> sent | queued | uncertain`，记录 owner/lease/attempt/next retry/error；不能证明请求未发出的 stale claim 转 `uncertain`。

## 5. Time model

字段属主模块声明 registry 条目：Adventure fatigue end，Boss `expires_at` / `next_spawn_at`。本任务负责登记 `_PROVIDER_MODULES` 和更新 `tests/test_time_skip_registry.py` 的期望矩阵，保持 fail-closed。

GM `/时间快进` 当前只把 SQL 注册字段前移，不推进一个全局业务 clock。因此：

- expiry/cooldown 字段会更早到期；
- `health_recovered_at` 不前移，Health 的可注入时钟单测另行验证经过量；
- `Asia/Shanghai` date key 不变，Boss 当日次数不会仅因字段 time-skip 重置；
- 真正跨日用 injectable clock 测试，不复用字段快进命令。

## 6. Tests

覆盖 fresh/v34 chain、每版失败和重复运行、schema parity、row/index/FK 校验、全调用图 commit scan、每个原子边界故障注入、CAS 并发、idempotency collision、delivery partial state、provider 注册/label/SQL field 映射，以及 GM time-skip 不误改 health anchor/pending/date key。

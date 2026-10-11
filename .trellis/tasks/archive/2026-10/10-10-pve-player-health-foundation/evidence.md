# Completion Evidence — child A 玩家气血领域基座（2026-10-11）

## 1. schema / version 与模型 diff

- `data/migration.py`：`LATEST_DB_VERSION = 35`（v36+ 留给 child P，本 child 未创建）。
  - fresh DDL `_create_all_tables` players 表：原 `hp` 列替换为 `base_hp`/`current_hp`/`health_recovered_at`（NOT NULL DEFAULT 100/100/0，带中文注释）。
  - 新增 `@migration(35) _players_health_layers_v35`：PRAGMA 幂等守卫（已有 base_hp 直接返回）→ `ALTER TABLE players RENAME COLUMN hp TO base_hp` + ADD `current_hp` + ADD `health_recovered_at` → 一次性 backfill（逐行以迁移时点动态上限回填：`HealthService(db=None, config_manager, equipment_manager=EquipmentManager(db=None)).compute_max_hp`，含装备/功法/心法聚合；`health_recovered_at = 迁移时刻`）→ 终验 PRAGMA，缺列抛 RuntimeError 由框架整体回滚保持 v34。rename+add+backfill+校验在同一迁移事务内。
  - 框架链验证：v34 ≥ TASK_CHAIN_MIN_VERSION(32) 走 pending 增量路径，**不触发 reset**；版本仅在全任务成功后 UPDATE db_info。
- `models.py`：`Player` 字段 `hp` → `base_hp: int = 100` / `current_hp: int = 100` / `health_recovered_at: int = 0`（带三层语义注释）；`get_total_attributes` 输出键 `hp` → `max_hp`；combat_power 聚合改用 `max_hp`；`Item.describe()` 的展示 hp 词条保留（配置契约）。
- 无 `hp` alias：`data/data_manager.py` 动态列映射来自 Player dataclass；死代码 `ext.update_player_hp_mp`（写 players.hp）已删除（零产品引用）。
- `data/data_manager.py` create_player、`data/database_extended.py` update_user_cd 的裸 `conn.commit()` 已按 `getattr(conn, '_txn_depth', 0) == 0` gate（Health/BusyState 事务调用图审计）。

## 2. 迁移测试（v34→新版 / fresh / 幂等 / 回滚）

`tests/test_player_health_foundation.py`（新增，18 用例）：
- `test_fresh_schema_has_three_layer_health_columns` — 新装 schema 恰含三列且无 hp 列。
- `test_v34_upgrade_backfills_dynamic_max` — 固化 v34 players fixture（带装备/功法气血加成）升级后 current_hp == 迁移时点动态 max_hp（≠ 旧 hp 底数），anchor==迁移时刻。
- `test_v35_rerun_is_idempotent` — v35 重跑早退，数据不变。
- `test_v35_failure_rolls_back_and_stays_v34` — 注入 backfill 异常：版本停留 34、hp 列恢复、行数据无损。
- `test_player_model_has_no_hp_attribute` / `test_no_player_hp_usage_left_in_product_code` — 静态清单：Player 无 hp 属性；产品代码（core/managers/handlers/data/main）无 `player.hp` / `Player(hp=)` / `total_attrs["hp"]` 残留（FighterState/BossEnemy/Item 配置契约的 hp 按 PRD 保留）。
- `tests/test_migration.py` 既有 11 用例同步（new_fields 集合、版本断言改 LATEST_DB_VERSION）通过。

## 3. 三层所有权 + 消费者迁移（AC3）

- 域入口 `core/health.py`（新增）`HealthService`：`compute_max_hp`（槽位装配镜像战斗构建器）、`settle`（锚点惰性结算，幂等、重启安全）、`get_health_snapshot`、`clamp_current_hp`（上限下跌夹紧）、`apply_current_hp_change`/`set_current_hp`/`heal_to_full`（仅动 current）、`add_base_hp`（仅动 base，不涨 current）；无奖励/平台副作用。
- 不变量测试：`test_base_growth_never_heals_current`、`test_current_change_never_moves_base_and_clamps`、`test_clamp_when_ceiling_drops`。
- 消费者全量迁移（无红态遗留）：
  - 创角 `core/cultivation_manager.py` generate_new_player_stats：base_hp=roll、current_hp=同值初始化。
  - 突破 `core/breakthrough_manager.py:256`：`player.base_hp += hp_step`（永久层唯一）；:382 叙事 ctx 用 base_hp。
  - 战斗引擎 `managers/combat_manager.py` build_fighter_from_player：经 HealthService 结算后 FighterState hp=settled current / max_hp=compute；PvP `handlers/combat_handlers.py` 写回 `current_hp`（duel 败者 1、spar 终值）。
  - 现有 PVE `managers/pve_combat_manager.py:350/:419/:472`、Boss `managers/boss_manager.py:518`、历练 `managers/adventure_manager.py:292`（败北 hp=1）：写回 player.current_hp。
  - 丹药 `core/pill_manager.py`：hp_restore/回生丹经 health API 改 current；回生丹属性减半属 base 层（`player.base_hp = max(1, base_hp//2)` 后 clamp current）；永久丹药 attr_mapping 写入目标 base_hp（PERMANENT_PILL_GAINS JSON 键 `hp` 契约保留）；周期性气血回复/消耗改 current，async 调用方 clamp。
  - 商店 `handlers/shop_handler.py`：add_hp → `apply_current_hp_change`（≥1）；add_max_hp → `add_base_hp`（current 不动，AC3）。
  - GM `core/gm_manager.py`：`设置气血` field_name → `base_hp`；两处 force-settle（cmd_force_adventure/cmd_force_rift）改为外层 `db.transaction()` 内先 `await health.settle(target)` 再上移 scheduled_time（直写例外保留但结算同事务）。
  - 展示：`handlers/player_handler.py` 面板气血 当前/上限、`handlers/equipment_handler.py:81` 预览差值 `total_attrs["max_hp"] - player.base_hp`。
- 事务 hook：`core/busy_state.py` set_busy/set_cooldown/clear 均在**既有外层事务内**先 `await self._health.settle(user_id)` 再写新状态（settle 经 _txn_depth 加入同一事务）；`test_set_busy_settles_old_state_in_same_transaction` 验证。
- 接线：`main.py` equipment_mgr 之后构造 HealthService 并注入 BusyState/CombatManager/PillManager/GMManager/PlayerHandler/ShopHandler/EquipmentHandler（keyword-only，默认 None 供测试 fixture）。

## 4. 惰性恢复与时间快进边界（AC4）

- `RECOVERY_RATE_PER_MINUTE = 0.01`：空闲按锚点补算 `int(max*0.01)*完整分钟`，anchor 只前进消耗的整分钟（余秒留存、重复读取幂等）；busy（user_cd type≠0 且未过期，scheduled_time=0 视为长期忙）不恢复仅推进锚点；anchor=0 采用当前时刻不追溯。
- 测试：`test_recovery_one_percent_per_minute_injected_clock`（可注入 clock）、`test_anchor_zero_adopts_clock_without_retro_heal`、`test_busy_window_advances_anchor_without_healing`、`test_expired_scheduled_cd_counts_idle`、`test_settle_joins_outer_transaction_rollback`（故障注入整体回滚）。
- 时间快进边界：`test_health_anchor_not_registered_in_time_skip` 断言 `health_recovered_at` 不在任何 TIME_SKIP_ENTRIES；`test_time_skip_sql_leaves_health_state_untouched` 执行注册 SQL 后三列（含锚点与 current）零变化——GM /时间快进不产生气血恢复。

## 5. 域 API 无副作用（AC5）

- `test_snapshot_returns_three_layers_without_side_effects`：get_health_snapshot 仅返回 base/current/max 并持久化结算值，不发放奖励、不触碰 user_cd/储物戒/消息。普通 PVE/Boss 路径已直接复用该 API（见 §3）。

## 6. 质量门日志摘要（AC6）

环境说明：沙箱内 `uv run` 不可用（`Failed to initialize cache at /home/guigui/.cache/uv: Permission denied`，沙箱对 workspace 外只读，非属主问题），改用项目 venv 等价二进制执行同一组门：
- `.venv/bin/ruff format . --check` → **124 files already formatted**（首跑 format 曾规整 13 个文件，含 4 个历史未格式化测试，属团队门本身行为）。
- `.venv/bin/ruff check core managers handlers data models*.py main.py tests` → **All checks passed!**（全仓 `ruff check .` 另有 70 条 `.trellis/scripts/**` 既有基线错误，非本 child 范围，未触碰）。
- `.venv/bin/python -m pytest tests/ -q`（插件目录，tests/helpers.py load_module 机制）→ **968 passed, 0 failed, 7.01s**（其中新增 test_player_health_foundation.py 18 例；11 个旧测试文件按三层契约迁移）。

## 7. 变更文件清单

产品：models.py、main.py、core/{health.py(新),busy_state.py,gm_manager.py,pill_manager.py,breakthrough_manager.py,cultivation_manager.py}、data/{migration.py,data_manager.py,database_extended.py}、managers/{combat_manager.py,pve_combat_manager.py,boss_manager.py,adventure_manager.py}、handlers/{combat_handlers.py,shop_handler.py,player_handler.py,equipment_handler.py}。
文档/版本：metadata.yaml v3.17.9→v3.18.0、README 版本行+更新日志、design_docs/{api-overview.md,current-design-report.md}（HealthService 行、v35 迁移行、主属性/气血通道措辞）。
测试：tests/{test_player_health_foundation.py(新),test_models.py,test_gm_manager.py,test_breakthrough_manager.py,test_pill_manager.py,test_boss.py,test_rift_encounters.py,test_migration.py,test_combat_engine.py,test_trigger_effect_extensions.py,test_pve_combat.py,test_transaction_atomicity.py,test_block_armor_source.py}（另有 ruff format 规整的 4 个无关测试文件）。

## 8. 回滚点

迁移执行前备份开发数据库（`cp monixiuxian.db monixiuxian.db.pre-v35.bak` 或 AstrBot data 目录等价）；失败场景由迁移事务整体回滚保持 v34（§2 测试证明）；不支持新 schema 被旧版本代码原地读取（项目未上线，直接回退代码+恢复备份）。

## 范围外（本 child 有意不做）

- v36+ 持久化迁移（child P）、PVE 敌人目录/世界 Boss/败场 25% 地板与 600s 疲劳/逃跑结算（child B/C/D/E）、步骤 7 奖励（父任务 PRD 全局 out of scope）。

## 9. 评审后修复轮（三轴评审发现，2026-10-11 同日修复）

- **P0 锚点内存-DB 不同步**：settle/_write_anchor 只写 DB 不回写内存锚点，而 update_player 全字段落库会把陈旧锚点刷回 DB（恢复窗口复活、忙碌窗口被补血）。修复：`data/data_manager.py` 新增 `_DOMAIN_OWNED_FIELDS = {"health_recovered_at"}`，UPDATE 排除该列（INSERT 不变），锚点由 HealthService 独占写入；`core/busy_state.py` set_busy/clear 钩子把 settle 返回值同步到内存 `player.current_hp`，防陈旧内存回刷已结算回血。回归测试：`test_update_player_never_reverts_settled_anchor`、`test_set_busy_syncs_current_hp_and_busy_window_stays_unhealed`。
- **P1 低上限恢复死区**：`heal = int(max_hp*0.01)*minutes` 在 max_hp<100（灵修创角 roll 90–99 无装备）时每分钟取整为 0 永不回血。修复：每分钟保底 1 点（`max(1, int(...))`）。回归测试：`test_low_max_hp_still_recovers`。
- **P2 批量**：`add_base_hp` 下限 0→1（对齐商店兜底/回生丹）；周期丹药 regen 落库前经 `_clamp_periodic_current_hp` 钳制动态上限；EquipmentHandler/PlayerHandler 新增可选 `health_service` 接线（main.py），装备/卸下后 clamp、面板气血显示 当前/上限；修正 health.py 模块 docstring 过度声明；test_pve_combat.py mock 残留 `p.hp`→`p.current_hp`（连带暴露并修复 build_fighter mock lambda 的残留读取）；AC1 静态扫描排除 `.scratch/`。回归测试：`test_add_base_hp_floors_at_one`。
- 修复后质量门：ruff format/check 全绿；`pytest tests/ -q` → **972 passed**（+4 回归用例）。

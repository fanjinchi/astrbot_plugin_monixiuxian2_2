# PVE 内容激活与旧 Boss 整删切流

## Goal

内容批准后执行正式 sync（28 名册 + 4 世界 Boss），把普通 PVE 默认出怪切到固定名册并退役旧动态派生（含 Q6 移出 top 三兽组），整删旧 Boss 实现/表/键/测试（2026-10-28 用户拍板：数据与结构直接放弃、不迁移不归档），在同一激活检查点启用新世界 Boss 领域与 poller，并交付端到端验收与回滚材料。

## Dependencies

- D 归档：世界 Boss 服务、fixture 测试、poller 函数、确定性 instance id、AC9 HP 锚证据、`ensure_spawn(profile_id)` 三分支。
- E1 归档：地板单源、全消费者复核、暴击双侧接线、事务叶子、通用文档收尾。
- B 的内容管线 / catalog / approval manifest 闸门（已归档）。
- **用户对 combat / narrative 的独立批准**（外部门，不由 AI 推定）。

## Requirements

### R1. 内容批准与正式 sync（唯一定义处）

- 展示：28+4 CSV 的 `status`/`narrative_status`、approval manifest、CSV SHA-256、获批列范围、生成 diff。
- 批准分两步、**均不由 AI 代劳**：① 用户按数据集确认「战斗数值列」获批范围；② 在获批范围内把对应行 `status` 由 `draft` 改 `final`，**重算 SHA-256 并生成 manifest**（hash 漂移 fail closed），再展示 diff 与 sync 计划。
- adapter 冻结：只认逐行 `status=final` + 显式 `--approval-manifest`（无第二通道）；manifest 绑定 CSV hash、列范围与叙事决策。**`columns` 必须覆盖整行表头**（含叙事列），「获批范围」指列内容被批准、不是选列；只列数值列会被判「列越权」。manifest 形状：`{"datasets": {"enemies.csv": {"sha256", "columns": [...], "narrative_status": [...]}, "world_bosses.csv": {...}}}`，`datasets` 键必须恰为两个文件名。
- **叙事状态必须按实际填**：当前 28+4 全为 `占位`，因此「只批战斗数值」时 manifest 必须写 `["占位"]`（闸门默认 `["定稿","豁免"]` 会让 32 行全拒）；只有用户同时批准叙事、CSV 升 `定稿` 后才写 `["定稿"]`（`豁免` 是 gate 语义值、不进 CSV）。放行占位必须在 `pve-enemy-design.md` 记录。
- **叙事批准结论必须落进 profile**：D 的 `build_world_boss_profile` 缺省发 `narrative_approved: false`（preview / 无 manifest 也带该键，否则 validate 因缺必填键失败），sync 在 `render_enemy_document` 的 `if manifest is not None:` 之后、唯一 `validate_enemy_document` 之前，按 `spec.get("narrative_status") or ["定稿","豁免"]` 对 `world_bosses` 每条翻 `true`（`enemies` 段无该字段）。缺省 `false` 时 D 的广播门控全挡。
- sync 后校验 count（28+4）/ id 唯一 / schema / hash；先 preview 再写正式 `config/enemies.json`（v2，含 `world_bosses` 段）。

### R2. 普通 PVE 调用方切流与旧派生退役

- catalog 非 `None` 时：`prepare_encounter` 与 `challenge_rift_beast` 默认出怪走 `EnemyCatalog.spawn_enemy(player_level, category, difficulty_multiplier)`；**难度系数必须显式取自 `config_manager.game_config["pve"]["difficulty_multiplier"]`**（config_manager 为 None 时 1.0）——旧路径在读该系数，漏传会让全局旋钮对所有普通 PVE 静默失效。定向组 `spawn_enemy_from_group`（`legacy_guardian` 等）不变。
- catalog 为 `None`（未 sync / 回滚）时保持旧动态派生，不得半切。
- **装配**：catalog 装配归 D；E2 只在 D 归档时 `load_catalog` 仍位于 `PVECombatManager` 构造之后的情况下把该行上移，否则复用同一实例——**任何情况不得第二次 load**；构造参数注入、不用 setter；源路径 `Path(__file__).parent / "config" / "enemies.json"`（`_wire_core_services` 只收到 `plugin_data_dir`）。
- 旧动态派生退役：`enemy_manager.spawn_enemy` 的 exp 派生路径不再被普通 PVE 命中，但**静态保留为 v1 回落**（不删除）；`enemy_catalog.spawn_enemy` docstring 改为「同名但需显式传 `difficulty_multiplier`」；把 `enemy_manager` 里的局部变量 `boss_config` 改名 `boss_mult`（否则 audit 判据永远命中）。
- **Q6 清理**：删除 `config/enemies.json` 的 `enemy_groups` 中 `key=top` 的组；**`low/mid/high` 必须保留**为 `catalog=None` 的 v1 回落（消费者是旧派生 `_get_group_by_level`，删掉会落到无 `level_range` 的守护组，未同步态会刷出守护 NPC）；`legacy_guardian` 保留。顺序：**删 top → sync → 代码切流**（`enemy_groups` 是 sync 的手工透传段）。
- **承接 D/E1 的延迟项**：若 D 落地时地板写回仍引用 `DEFEAT_HP_FLOOR_RATIO`，本 child 在激活检查点改调 `HealthService.defeat_hp_floor`（定义见 `10-10-pve-cross-system-integration/design.md` §2）；若 D 落地时 `build_enemy_fighter` 仍无 `base_crit_rate` 形参（D 先于 E1），本 child 补传（默认值见 `10-10-pve-cross-system-integration/design.md` §3、行为不变）并核世界 Boss 暴击随键变化。

### R3. 旧 Boss 整删（数据与结构直接放弃）

- 不迁移、不归档旧 `boss` 表数据；代码删 `managers/boss_manager.py`、`handlers/boss_handlers.py`、`models_extended.Boss`、`data/database_extended.py` 的 boss CRUD、`main.py` 的 `_schedule_boss_spawn`/`_broadcast_boss_*`/`boss_next_spawn_time` 读写。
- 配置三元组：删 `config/boss_config.json`、`data/default_configs.py::BOSS_CONFIG`、`config_manager.boss_config` 装载与 import（`config_manager.py` 的 import 行与属性同批删，否则 ImportError；缺文件会按默认值重建，必须三处一起）。
- **叙事 lint 依赖**：`lint_narrative.py` 读 `config/boss_config.json` 的 `world_bosses` 映射（`_load_json` 无兜底）；删文件前改为读 `config/enemies.json` v2（**不要直接删映射**：该表在 `desc_tables` 中且 `name_maps[table]` 直接索引，删了会 KeyError）。
- 表与键：删旧 `boss` 建表 DDL；新增 v40 `DROP TABLE IF EXISTS boss`，登记 `VERSION_SCHEMA_TABLES[40] = ()`（空表集合；boss 不得记入 v40 表集）与 `tests/test_pve_persistence_foundation.py` 的 `NEW_TABLES[40] = ()`；`DELETE system_config.boss_next_spawn_time`；补 v40 专用 parity 用例（手动建表 + 1 行 + 旧 key，fresh 已无表不能回退取证）。
- time-skip：旧 `boss_manager.TIME_SKIP_ENTRIES` 首条随文件删除；世界 Boss 两条迁到新属主模块并登记 `_PROVIDER_MODULES`（**删除 `"managers.boss_manager"` 元组项**，漏删会让 `from_providers()` 抛 FileNotFoundError、插件装配失败）；`spirit_eye_manager` 共享标签改「灵眼下次刷新时间」，同步 README 与 registry/GM 帮助文案（删 1 条后总数为 **13 条**；`gm_manager` 里「10 行 vs 11 条」在拆条前就已失真，改为按注册表动态计数）。
- GM / 权限（**保留**，2026-11-05 修订）：顶层 `生成Boss [profile_id]`（受 `BOSS_ADMINS`）与 `GM 生成Boss [profile_id]` 都改接 `ensure_spawn(profile_id)`，三分支语义见 `10-10-pve-world-boss-domain/prd.md` R1；只有管理入口可传 `profile_id`，poller 一律 `None`；`CMD_*`、`boss_admins`、`_check_boss_admin`、`BOSS_ADMINS` 保留，`broadcast_callback` 停用改走 outbox。
- 玩家可见文案不得再承诺 Boss 掉落：`handlers/misc_handler.py`（挑战Boss 帮助行）、`handlers/shop_handler.py` 的 `ITEM_ACQUIRE_HINTS`、`handlers/storage_ring_handler.py` 的「Boss击杀掉落」。
- 机械清理判据：`python3 scripts/audit_pve_redesign.py --scope e2` 必须为 0（覆盖旧符号、旧配置属性/文件、旧 key、玩家文案、time-skip provider、v2 config 的 top 组与 `narrative_approved`）；脚本不覆盖的装配/import 点按 `implement.md` step 6 逐项改。

### R4. 新入口与 poller 接管

- 复用 D 的 catalog 装配与领域服务，不重复装配；`boss.enabled` 保留为新玩法总开关（更新 comment 与默认配置文案）。
- 注册 lifecycle poller（指数退避、`initialize()` 启动 / `terminate()` 取消）；新 handler 接管 `世界Boss`/`挑战Boss`/`生成Boss` 三个命令名；outbox dispatcher 运行，网络 await 在事务外。
- **零奖励过渡**：本轮只落台账事实，不发任何奖励；过渡态写入 `current-design-report §4.7` 与 `pve-enemy-design` Step 6 遗留①，广播文案不得承诺奖励。
- 旧/new 不得同时运行；删除与启用必须同一提交/检查点。

### R5. 端到端验收

- spawn→challenge→phase→defeated/dissipated→respawn；北京日 3 次与跨日；重启恢复；并发唯一末击；CAS 失败方次数/HP 不变。
- 普通 PVE 切流：28 名册在历练/秘境默认路径可达；旧派生运行态不再命中；`enemy_groups` 无 `key=top`；`legacy_guardian` 与秘境定向组回归；`catalog=None` 回落不刷守护 NPC。
- HP 锚：用正式 config 的 4 只 profile 复跑 D AC9 同一断言（阶段 40/40/20、±10%、3 次/日×2 日磨死）。
- GM `/时间快进` 矩阵：Boss `expires_at`/`next_spawn_at` 生效；health anchor/pending/`date_key` 不受影响。
- 广播 partial success/uncertain 证据；事务内无网络 await；`functional_tests/cases/pve/pve-smoke.json` 的「世界Boss」断言仍可命中新回复。

### R6. 回滚与文档

- 激活前备份 DB + generated config hash + 旧 CSV hash；失败按同一检查点恢复代码/DB/config（git revert + 备份），禁止双跑与部分回滚。
- 文档同步（逐项）：`pve-enemy-design.md`（头部状态、实施状态块补 A/P/C/F/D/E1/E2、Step 6 遗留①②③④、§Q4、Step 8 状态、北京时间、旧 Boss 移除）；`current-design-report.md`（敌人生成/世界 Boss 条目、零奖励过渡、§4.19 GM 生成Boss、§4.20 敌人域 sync、§2 配置表删 `boss_config.json`、§4.6 掉落来源、目录树、`db.ext` Boss CRUD、`models_extended.Boss`、定时任务、Boss 模型字段、§五 表清单 v40）；`project-architecture.md`（版本号、managers/models/mermaid、定时任务、PvE 与世界 Boss 行、GM/Boss 管理员）；`api-overview.md`（删 BossManager/`_schedule_boss_spawn`、`BossHandlers` 行替换为新 handler、`cmd_spawn_boss` 保留改描述、DatabaseExtended Boss CRUD、models、状态行）；`design_docs/README.md` 与 `content-design/README.md`、`sect-system-design.md` 的引用；插件 `README.md`、`metadata.yaml` version、`/修仙帮助`。

## Out of Scope

- 新领域实现（D）、地板与消费者收口（E1）、Step 7 经济与秘境生态、未经用户要求的 webtest、第二季 top 三兽重设计。

## Acceptance Criteria

- [ ] AC1：批准流程可执行——获批列范围 → 用户侧 `status→final` → 重算 hash/manifest → sync；draft/缺 manifest/hash 漂移/列越权 fail closed；占位放行须 manifest `["占位"]` 并回写设计；该正向组合有用例；**正式产物 `world_bosses[*].narrative_approved` 为 true**。
- [ ] AC2：普通 PVE 默认路径切到固定名册（28 可达、全局难度系数仍生效、v2 config 下 `catalog` 非 None）且 `key=top` 组删除；旧派生运行态不再命中（静态保留、仅回滚/未批准态可达）；`legacy_guardian` 与秘境组回归；`catalog=None` 回落用例通过。
- [ ] AC3：旧 Boss 代码/配置三元组/表/键/测试/文档清零，`audit_pve_redesign.py --scope e2` 为 0；`boss` 表不存在（v40 专用 parity）；`system_config.boss_next_spawn_time` 无生产读写；`lint_narrative` 不再依赖已删配置；玩家文案不再承诺 Boss 掉落。
- [ ] AC4：新入口与 poller 同一检查点启用，旧/new 不双跑；poller 指数退避与 terminate；`boss.enabled` 关闭仍生效；`生成Boss`/`GM 生成Boss` 按 D R1 三分支改接且 `BOSS_ADMINS` 沿用；catalog 装配复用 D 的注入。
- [ ] AC5：端到端链路、北京日 3 次、重启恢复、并发唯一末击、CAS 失败不扣次数、time-skip 矩阵、广播 partial success、D AC9 HP 锚复跑均有证据；零奖励过渡已记录且广播不承诺奖励。
- [ ] AC6：回滚材料齐备并演练；文档清单逐项完成；完整 pytest + 产品范围 ruff + `audit_pve_redesign.py --scope all` 为 0。

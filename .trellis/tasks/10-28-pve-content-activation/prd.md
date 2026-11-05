# PVE 内容激活与旧 Boss 整删切流

## Goal

内容批准后执行正式 sync（28 只名册 + 4 只世界 Boss 配置），把普通 PVE 默认出怪切换到固定名册（调用方切流）并退役旧动态派生（含 Q6 要求移出第一季的 top 三兽组），整删旧 Boss 实现/表/键/测试（2026-10-28 用户拍板：旧 Boss 数据与结构直接放弃，不迁移不归档），在同一个激活检查点启用新世界 Boss 领域与生命周期 poller，并交付端到端验收与回滚材料。

## Dependencies

- D（`10-10-pve-world-boss-domain`）归档：世界 Boss 服务、fixture 测试、生命周期 poller 函数、确定性 instance id、AC9 HP 锚证据。
- E1（`10-10-pve-cross-system-integration`）归档：地板单源、全消费者复核、事务叶子清零、通用文档收尾。
- B 的内容管线 / catalog / approval manifest 闸门（已归档；仍需用户内容批准）。
- **用户对 combat / narrative 的独立批准**（外部门，不由 AI 推定）。

## Requirements

### R1. 内容批准与正式 sync

- 向用户展示 28+4 CSV 的 `status`/`narrative_status`、approval manifest、CSV SHA-256、获批列范围与生成 diff。
- 批准动作分两步，**均不由 AI 代劳**：① 用户按数据集确认「战斗数值列」获批范围；② 仅在获批列范围内把对应 CSV 行 `status` 由 `draft` 改为 `final`，**重新计算 CSV SHA-256 并生成 manifest**（hash 漂移必须 fail closed），然后再展示 diff 与 sync 计划。
- adapter 现状冻结：只认逐行 `status=final` + 显式 `--approval-manifest`（**不存在第二批准通道**）；manifest 绑定 CSV hash、列范围与叙事决策。**列闸门按整行表头校验：manifest 的 `columns` 必须覆盖含叙事列的全部列**，「获批范围」指这些列的内容被批准、不是选列；只列数值列会被判「列越权」fail closed。仓库目前没有 manifest 生成工具，需在 `scripts/` 旁给出最小模板/生成命令（或文档化 python 片段），否则用户侧不可复现。manifest 形状：`{"datasets": {"enemies.csv": {"sha256", "columns": [...整行表头...], "narrative_status": [...]}, "world_bosses.csv": {...}}}`——`datasets` 键必须恰为两个 CSV 文件名，缺一/多一都会被 sync 闸门 fail closed。draft / 缺 manifest / hash 漂移 / 列范围越权一律 fail closed，禁止手改生成配置。
- 叙事准入：gate 默认只放行 `{定稿, 豁免}`（`core/enemy_schema.check_approval` 的字面默认集；canon 词表只含 占位/待写/定稿，`豁免` 是 gate 语义值，**不得直接写进 CSV**）；若要放行占位，必须用户明确同意、manifest 的 `narrative_status` 显式写「占位」、并在 `design_docs/content-design/pve-enemy-design.md` 记录该决定（否则不得上线占位文案）。**当前清单 28+4 全为 `narrative_status=占位`**：因此「只批战斗数值、叙事仍占位」时 manifest 必须写 `["占位"]`——闸门默认放行集是 `["定稿","豁免"]`，照默认写会让 32 行全部 fail closed；只有用户同时批准叙事、CSV 升 `定稿` 后才写 `["定稿"]`（`豁免` 是 gate 语义值、永不出现于 CSV）。并补一条正向用例：`status=final` + `narrative_status=占位` + manifest `["占位"]` 必须通过（现有 `tests/test_enemy_sync_gate.py:181` 只有负例）。
- sync 后校验 count（28+4）/ id 唯一 / schema / hash；先在 preview 产物上验证，再写正式 `config/enemies.json`（schema v2，含 `world_bosses` 段）。

### R2. 普通 PVE 调用方切流与旧派生退役（设计点名 Batch 5 主体）

- catalog 非 `None`（正式 v2 config）时：`PVECombatManager.prepare_encounter` 与 `challenge_rift_beast` 的默认出怪改走 `EnemyCatalog.spawn_enemy(player_level, category, difficulty_multiplier)`；**`difficulty_multiplier` 必须显式取自 `config_manager.game_config["pve"]["difficulty_multiplier"]`（`config_manager` 为 None 时 1.0，与旧 `EnemyManager._global_difficulty_multiplier` 同义）**——旧路径在 `EnemyManager` 内部读取该系数，切流只传两参会让全局难度旋钮对所有普通 PVE 静默失效；定向组 `spawn_enemy_from_group`（`legacy_guardian` 等）保持不变。
- catalog 为 `None`（v1 config / 未 sync）时保持现状回落旧动态派生，不得半切。
- **catalog 实例来源与注入**：复用 D 在 `_wire_core_services` 创建的同一 `EnemyCatalog` 实例（D 归档后提供），以可选依赖（默认 `None`）注入 `PVECombatManager`；**不得新增第二次 `load_catalog`**。**装配顺序钉死**：catalog 装配本身归 D；E2 只在「D 归档时 `load_catalog(...)` 仍位于 `PVECombatManager` 构造之后」的情况下把这一行上移，D 已上移则直接复用——**任何情况都不得第二次 `load_catalog`**。catalog 作为构造参数传入，**不采用 setter**。源路径用 `Path(__file__).parent / "config" / "enemies.json"`（与 `managers/enemy_manager.py:85` 的 `CONFIG_FILE` 同源；`_wire_core_services` 只收到 `plugin_data_path`，`ConfigManager._base_dir` 是私有属性）。`PVECombatManager.__init__` 增 `catalog=None` 可选参数；补 wiring 断言「v2 config 下 `pve_combat_mgr.catalog is not None`」。
- 旧动态派生退役：`enemy_manager.spawn_enemy` 的 exp 派生路径不再被普通 PVE 命中，但**静态保留为 v1 回落**（不删除——删了 `catalog=None` 的回落就不成立）；`enemy_manager.py` 过渡注释与 `current-design-report` 措辞同步。`managers/enemy_catalog.py` 的 `spawn_enemy` docstring（现写「Same name/signature … mechanical」）同步为「同名但需显式传 `difficulty_multiplier`」，避免两参调用静默降级。
- 名册可达性证据：历练 / 秘境默认路径命中 28 只名册（segment × category），元婴段不再刷出 top 三兽组。
- **Q6 清理**：删除 `config/enemies.json` 中 `enemy_groups` 里 `key=top` 的组（苍龙/墨玉麒麟/火凤整组移出第一季）；**`low/mid/high` 必须保留**作为 catalog `None` 时的 v1 回落数据——它们的消费者是旧派生 `enemy_manager._get_group_by_level`（不是 `spawn_enemy_from_group`；全仓配置引用只有 `legacy_guardian`），删掉会让回落落到无 `level_range` 的守护组，未同步/回滚态下普通 PVE 会刷出守护 NPC；`legacy_guardian` 保留。**删除时机钉死**：在 R1 正式 sync **之前**从现有 `config/enemies.json` 删除（`enemy_groups` 是 sync 的手工透传段，透传源就是现有 config）；实现步骤顺序为「删 top → sync → 代码切流」；若改到 sync 之后才删，必须同时手工删生成配置里的同组（sync 不会从 CSV 重建 groups），否则残留。

### R3. 旧 Boss 整删（数据与结构直接放弃）

- 不迁移、不归档旧 `boss` 表数据（开发库现存 1 行随表删除）。
- 代码：删 `managers/boss_manager.py`、`handlers/boss_handlers.py`、`models_extended.Boss`、`data/database_extended.py` 的 boss CRUD、`main.py` 的 `_schedule_boss_spawn` / `_broadcast_boss_spawn` / `_broadcast_boss_defeat` / `boss_next_spawn_time` 读写。
- 配置三元组：删 `config/boss_config.json`、`data/default_configs.py` 的 `BOSS_CONFIG`、`config_manager.boss_config` 装载（`config_manager.py:418-419` 缺文件会按默认值重建，必须三处一起去）；另 `config_manager.py:9` 的 `from .data.default_configs import BOSS_CONFIG` 与 `:60` 的 `boss_config` 属性同批删除，否则 ImportError。
- **叙事 lint 依赖**：`design_docs/content-design/lint_narrative.py` 直接读 `config/boss_config.json` 的 `world_bosses` 名册映射（读取点在 `:318`，`:316` 只是注释）；删文件前必须改为读 `config/enemies.json`（v2 `world_bosses` 段），否则 sync 第二道闸门 FileNotFoundError。**不要选「直接删掉该映射」**：`world_bosses.csv` 在 `lint_narrative.py:693` 的 `desc_tables` 中，`:707` 直接 `name_maps[table]`，删映射会 KeyError；若确实要放弃该表的名字一致性检查，必须同批把它从 `desc_tables` 移除并记录。
- 表与键：`data/migration.py` 删除旧 `boss` 建表 DDL、新增 v40 `DROP TABLE IF EXISTS boss` 并登记 `VERSION_SCHEMA_TABLES[40] = ()`（**空表集合**：DROP 不是「拥有新表」；`tests/test_pve_persistence_foundation.py:70` 的 `NEW_TABLES` 同步 `40: ()`（注意它定义在测试里，不在 `data/migration.py`），避免回退用例对 fresh 库 DROP 不存在表报错）、`DELETE system_config.boss_next_spawn_time`；`tests/test_migration.py` 表清单同步；**补 v40 专用 parity 用例**（手动建 boss 表 + 1 行 + 旧 key、version=39 → 跑迁移断言表与键消失；fresh 已无 boss 表，DROP 是 no-op，不能靠 fresh 回退取证）。
- time-skip：旧 `boss_manager.TIME_SKIP_ENTRIES` 首条随文件删除；世界 Boss 两条迁到新领域属主模块并登记 `_PROVIDER_MODULES`；`spirit_eye_manager` 的共享标签「Boss/灵眼下次刷新时间」改名「灵眼下次刷新时间」，同步 README 与 `test_time_skip_registry` 期望（删 1 条后总数为 **13 条**，不是 14 条）与 `tests/test_gm_manager.py`（:1232/:1266/:1344 的 `boss_next_spawn_time` 种子/断言、:1366/:1369 的条数与域数断言），以及 `core/gm_manager.py` 的「时间快进」docstring 与回复文案（`core/gm_manager.py:1326` 现写「10 行（label 聚合）vs 共前移 11 条」，**在拆条前就已失真**——当前注册表 14 条目/13 标签；改成按注册表动态计数或写正确数字，并去掉「Boss/灵眼」表述）。新属主模块登记 `_PROVIDER_MODULES` 时**追加表尾**（决定 registry 测试期望顺序），并同批改 `core/time_skip_registry.py` 与 `data/migration.py` 注释里对 `boss_manager` 的引用。
- GM / 权限（**2026-11-05 修订，取代 11-01 的删除方案**）：**保留「生成Boss」子命令与 `BOSS_ADMINS` 权限闸门，改接新世界 Boss 领域**。命令语义改为「立即触发一次 ensure，可选指定 profile」：`GM 生成Boss [profile_id]` —— 不带参数时按 D 的确定性选段逻辑生成/复用 active 实例；带 `profile_id` 时强制该 Boss（仍按 `(profile_id, spawn_epoch)` 派生 instance_id、仍写不可变快照、仍受「单 active」与 12h/24h 到期规则约束）。理由：4 只 Boss 按境界段随机，取消手动生成会让功能用例无法「按指定 Boss」验证阶段/击杀/消散；`_check_boss_admin` 继续作为管理员闸门。依赖：D 提供 `ensure_spawn(profile_id: str | None = None)`（见 D R1）；E2 把 `main.py` 的 `handle_spawn_boss` 与 `core/gm_manager.py::cmd_spawn_boss` 改接该入口（`broadcast_callback` 停用，广播统一走新 outbox），`CMD_SPAWN_BOSS` 与 `_conf_schema.json:18` 的 `BOSS_ADMINS` 保留，`current-design-report:88`、`project-architecture:17` 只需把语义注释改为「世界 Boss 管理员」。
- 测试：`tests/test_boss.py` 删除/重写；`tests/test_feature_switches.py` 的 **6 条** boss 用例改指新命令；`tests/test_gm_manager.py` boss mock/断言改；`tests/test_time_skip_registry.py` 删旧键期望；`tests/test_skill_equip_and_tome.py:168` 的硬读文件清单删 `managers/boss_manager.py`；`tests/test_pve_persistence_foundation.py:254/266` 的 `LATEST_DB_VERSION == 39` / `VERSION_SCHEMA_TABLES == [36,37,38,39]` 更新到 v40；D 归档后新增的测试（TIME_SKIP provider、装配位置）同批核对。
- 机械面（import 会立刻炸）：`handlers/__init__.py`、`managers/__init__.py` 的导出；`main.py` 的 `CMD_BOSS_*`/**`boss_admins`/`_check_boss_admin` 保留**（「生成Boss」闸门沿用，仅改接新领域）；`core/gm_manager.py` 的 `boss_manager` 形参要换成新领域服务、`broadcast_callback` 停用、GM 帮助文本同步「生成Boss [profile_id]」。必须静态搜索兜底，不能只删主文件。另清不炸但会误导的残留：`data/default_configs.py:17` 的 `__all__` 中的 `"BOSS_CONFIG"`、`config_manager.py:265` 的 docstring 举例、`data/database_extended.py:3` 的 Boss 字样。
- **玩家可见文案**（零奖励 + 旧 Boss 删除后不得再承诺掉落）：`handlers/misc_handler.py:131`「挑战Boss → 挑战Boss获取奖励+物品掉落」、`handlers/shop_handler.py` 的 `ITEM_ACQUIRE_HINTS`（`:24/:26/:27/:28/:30`「秘境/Boss 掉落」「器阁、Boss 掉落」）、`handlers/storage_ring_handler.py:120/:528` 的「Boss击杀掉落」，全部改为与新玩法一致（世界 Boss 本轮无掉落／改指秘境·悬赏），并纳入 R6 文档同步。
- 旧 / new 不得同时运行；旧实现删除与新入口启用必须同一提交 / 检查点。

### R4. 新入口与 poller 接管

- **catalog 装配归 D**（D 的 Dependencies 已认领在 `_wire_core_services` 注入 `load_catalog`，`None` → disabled；D 归档后提供）；E2 复用**同一实例**注入 `PVECombatManager`（见 R2），不重复 `load_catalog`，并验证正式 v2 config 下自动启用。
- 保留 `boss.enabled` 作为新世界 Boss 总开关（不改 key，更新 comment 与 `data/default_configs.py` 文案）。
- 注册新 lifecycle poller：指数退避（复用 `_schedule_boss_spawn` 模板）、`initialize()` 启动 / `terminate()` 取消、不读旧 key。
- 新 handler / 指令接管 `世界Boss` / `挑战Boss` / `生成Boss` 语义；`生成Boss` 按 R3 改接新领域 `ensure_spawn(profile_id=None)`（三个命令名不变，`生成Boss` 支持可选 profile 参数）。
- outbox dispatcher 注册运行：提交后 per-destination claim 发送，网络 await 在数据库事务外；`uncertain` 仅人工处置。
- **零奖励过渡**：世界 Boss 本轮只落台账事实、不发任何奖励（Step 7 前无参与保底/分档/末击彩蛋数值）；该过渡态必须写入 `design_docs`（current-design-report §4.7 与 pve-enemy-design Step 6 遗留①），广播文案不得承诺奖励。

### R5. 端到端验收

- spawn → challenge → phase → defeated / dissipated → respawn；北京日 3 次与跨日；重启恢复；并发唯一末击；CAS 失败方次数 / HP 不变。
- **普通 PVE 切流验收**：28 名册在历练 / 秘境默认路径可达；旧动态派生不再命中；`enemy_groups` 中不存在 `key=top` 的组；`legacy_guardian` 定向组仍可用。
- **HP 锚复跑**：用正式 config 的 4 只 profile 跑 D AC9 同一断言（阶段 40/40/20 加权、偏差 ≤±10%、3 次/日 × 2 日磨死），确认运行时映射未漂移。
- GM `/时间快进` 矩阵：Boss `expires_at` / `next_spawn_at` 生效；health anchor / pending / `date_key` 不登记且不受影响；pending 无自动过期、busy 跨重启保持。
- **功能用例核对**：`functional_tests/cases/pve/pve-smoke.json` 的「世界Boss」步骤断言 `re:Boss|BOSS|boss|暂无|未生成`，新 handler 回复必须命中其一，否则冒烟误报；同批核对 GM 时间快进用例里的 Boss 相关步骤。
- 广播 partial success / uncertain 人工处置证据；事务内无网络 await。

### R6. 回滚与文档

- 激活前备份 DB + generated config hash + 旧 CSV hash；失败按同一检查点恢复代码 / DB / config（git revert + 备份），禁止双跑与部分回滚。
- 文档同步（逐项，设计文档必须与实现一致）：
  - `design_docs/content-design/pve-enemy-design.md`：头部状态、实施状态块（补 A/P/C/F/D/E1/E2 + 2026-10-28 旧 Boss 放弃决议）、Step 6 遗留①②③④、§Q4 与 Step 8 状态、每日 3 次 `Asia/Shanghai` 时区、旧 Boss 移除。
  - `design_docs/current-design-report.md`：在 E1 改写基础上**增量替换**敌人生成 / 世界 Boss 条目（零奖励过渡）、§4.19（GM 生成Boss）、§4.20（敌人域 sync）、§2 配置表 `:78`（删 `boss_config.json` 行）、`:88`（ACCESS_CONTROL 的 `BOSS_ADMINS`，语义改为世界 Boss 管理员）、§4.6 `:224`（掉落来源不再引用 `boss_manager`）、目录树 `:35`、`db.ext` Boss CRUD `:39`、`models_extended.Boss` `:43`、`_schedule_boss_spawn` `:63`、Boss 模型字段 `:127`、§五 表清单/迁移历史（v40）；`:208` base_crit_rate 归 E1，不在本 child。
  - `design_docs/project-architecture.md`：版本号（`:16`/`:132`）、`managers` / `models` / mermaid、定时任务（`:43`/`:51`）、PvE（`:69`）与世界 Boss（`:70`）行、`:17`（GM/Boss 管理员）、`:82`（GM 工具生成Boss）、bd 里程碑。
  - `design_docs/api-overview.md`：删 `BossHandlers` / `BossManager` / `_schedule_boss_spawn`、`GMManager` 行的 `cmd_spawn_boss`（`:111`）、`DatabaseExtended` 的 Boss `*_boss`（`:121`）、`models_extended.Boss`（`:130-131`），补新服务与 poller，改「Batch 5 切流前」状态（`:93-95`）。
  - `design_docs/README.md`：资料清单状态行（`pve-enemy-design` 讨论稿 → Step 0-6 封板 / Step 8 已激活；`world_bosses.csv` 已在 `content-design/README:34` 登记，核对即可）；`design_docs/content-design/README.md:29`（仍写「Step 8 管实施/内容批准」）与 `design_docs/sect-system-design.md:252`（引用已删 `boss_manager.py`）同步。
  - 插件 `README.md`：功能表 / 指令表 / 掉落来源 / `boss_config.json` 行 / 目录树 / 迁移链 / 更新日志；`metadata.yaml` version 与 `/修仙帮助`。

## Out of Scope

- 新领域实现（D）、地板与消费者收口（E1）、Step 7 奖励经济与秘境生态、未经用户要求的真实 webtest、第二季 top 三兽重新设计。

## Acceptance Criteria

- [ ] AC1：内容批准流程可执行——获批列范围 → 用户侧 `status` 升 `final` → 重算 hash / manifest → sync；draft / 缺 manifest / hash 漂移 / 列范围越权 fail closed；叙事占位放行须 manifest 的 `narrative_status` 显式写 `["占位"]` 并回写设计，且该正向组合有用例（`status=final` + `占位` + manifest `["占位"]` → 0 错）。
- [ ] AC2：普通 PVE 默认路径切到固定名册（28 只可达、全局难度系数仍生效、v2 config 下 `PVECombatManager.catalog` 非 None）且 `key=top` 的组删除；旧动态派生不再被普通 PVE 命中（判定基准：以交付的 v2 正式 config 为运行态；旧派生静态保留、仅回滚/未批准态可达）；`legacy_guardian` 与秘境定向组回归通过；`catalog=None` 回落用例通过。
- [ ] AC3：旧 Boss 代码 / 配置三元组 / 表 / 键 / 测试 / 文档清零，**判据必须可机械执行**：`grep -rn "boss_manager\|BossManager\|BOSS_CONFIG\|boss_config\|boss_handlers" main.py handlers managers core config` → 0（`data/migration.py` 的建表/迁移历史注释例外）；`boss_next_spawn_time` 在产品代码 0 读 0 写、只允许出现在 v40 `DELETE` 与测试；`stone_reward` 以 `grep -rn "boss.*stone_reward\|stone_reward.*boss"` → 0 为准（`managers/bounty_manager.py:493/502` 的局部变量与本域无关）；`boss` 表不存在（v40 专用 parity 用例 + fresh 一致）；`lint_narrative.py` 不再依赖已删配置；玩家可见文案不再承诺 Boss 掉落。
- [ ] AC4：新入口与 poller 在同一检查点启用，旧 / new 不双跑；poller 指数退避与 terminate；`boss.enabled` 整体关闭仍生效；`生成Boss` 已改接新领域（支持可选 `profile_id`，`BOSS_ADMINS` 闸门沿用且静态搜索无旧 `BossManager` 引用）；catalog 装配复用 D 的注入、不重复实现。
- [ ] AC5：端到端链路、北京日 3 次、重启恢复、并发唯一末击、CAS 失败不扣次数、time-skip 矩阵、广播 partial success、D AC9 HP 锚复跑均有证据；零奖励过渡态已在 design_docs 记录且广播不承诺奖励。
- [ ] AC6：回滚材料齐备并演练；文档同步清单逐项完成；完整 pytest + 产品范围 ruff 通过；真实 webtest 仅用户要求时运行。

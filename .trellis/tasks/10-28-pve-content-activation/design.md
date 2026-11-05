# Technical Design: PVE 内容激活与旧 Boss 整删切流

## 1. Cutover 形态（单开关 + 代码删除）

- 保留 `game_config.boss.enabled` 作为**新**世界 Boss 总开关（语义从「旧随机 Boss」改为「世界 Boss 生命周期玩法」），`pve.enabled` 继续作为 PvE 总闸。
- 不新增第二开关：旧实现整删后不存在「旧开关」，避免旧 / new 双跑；回滚 = git revert + 同检查点 DB / config 备份，不做 config 级并存。

激活顺序（同一检查点）：

```text
内容批准（combat / narrative 独立；用户侧把 status 升 final 并重算 hash/manifest）
  -> sync preview 校验 count/hash/schema
  -> sync 前：从现有 config 删除 enemy_groups 中 key=top 的组
  -> 正式写 config/enemies.json（schema v2，含 world_bosses 段）
  -> 普通 PVE 切流：默认出怪改走 EnemyCatalog.spawn_enemy；旧派生退役
  -> 停旧：删除旧 Boss 实现/配置三元组/表（v40 DROP）/键/测试（含 lint_narrative 依赖修正）
  -> 启新：复用 D 的 catalog 装配、注册 lifecycle poller、新 handler、outbox dispatcher
  -> HP 锚复跑 + smoke + 完整回归 + 文档同步
```

## 2. 普通 PVE 切流（设计点名 Batch 5 主体）

- `PVECombatManager.prepare_encounter` / `challenge_rift_beast` 的默认出怪：`catalog is not None` → `catalog.spawn_enemy(player_level, category, difficulty_multiplier)`；`difficulty_multiplier` 取自 `config_manager.game_config["pve"]["difficulty_multiplier"]`（None→1.0），**旧路径在 `EnemyManager` 内部读该系数，切流漏传第三参会让全局难度旋钮静默失效**；否则（v1 config / catalog disabled）保持旧动态派生，不半切。
- catalog 实例：复用 D 在 `_wire_core_services` 创建的同一实例（D 归档后提供），以可选依赖注入 `PVECombatManager`，不得第二次 `load_catalog`；**装配顺序钉死**：装配归 D；E2 只在 D 仍把 `load_catalog` 放在 `PVECombatManager` 构造之后时把该行上移，否则直接复用同一实例——任何情况不得第二次 `load_catalog`；源路径 `Path(__file__).parent / "config" / "enemies.json"`，构造参数传入，不用 setter；补 wiring 断言。
- 定向组（`spawn_enemy_from_group`）继续走 `enemy_groups`：`legacy_guardian` 必留；**`low/mid/high` 必须保留为 v1 回落数据**（消费者是旧派生 `_get_group_by_level`，不是 `spawn_enemy_from_group`；删掉会让回落落到守护组）。
- 删除 `enemy_groups` 中 `key=top` 的组（Q6：苍龙/墨玉麒麟/火凤整组移出第一季）——`enemy_groups` 是 sync 的手工透传段，**在 sync 前对现有 config 执行**（顺序：删 top → sync → 代码切流；若改到 sync 后删，必须同时手工删生成配置里的同组）；补「元婴段只出该段 7 只（4 normal/2 elite/1 boss）、不含 top 三兽」与「catalog=None 回落不刷守护」断言。
- 旧派生退役口径：`enemy_manager.spawn_enemy` 静态保留仅供 v1 回落（不删除）；`enemy_manager.py` 过渡注释与 `current-design-report` 同步。

## 3. 旧 Boss 整删矩阵

| 类型 | 对象 | 处理 |
|---|---|---|
| 代码 | `managers/boss_manager.py`、`handlers/boss_handlers.py`、`models_extended.Boss`、`data/database_extended.py` boss CRUD | 整文件/整段删除 |
| 代码 | `main.py` 的 `_schedule_boss_spawn` / `_broadcast_boss_spawn` / `_broadcast_boss_defeat` / `boss_next_spawn_time` 读写 | 删除，新 poller 接管 |
| 配置 | `config/boss_config.json` + `data/default_configs.py::BOSS_CONFIG` + `config_manager.boss_config` 装载 | 三处同批删除（缺一会被默认值重建） |
| 工具 | `design_docs/content-design/lint_narrative.py`（读 `boss_config.json` 的 `world_bosses` 映射） | 改为读 `config/enemies.json` v2 `world_bosses` 段（**不要直接删映射**：该表在 `desc_tables` 里且 `:707` 直接 `name_maps[table]`，删了会 KeyError；若放弃名字一致性检查须同批移出 `desc_tables`） |
| 表 | `boss`（fresh DDL） | 删除建表；新增 v40 `DROP TABLE IF EXISTS boss`，登记 `VERSION_SCHEMA_TABLES`；补 v40 专用 parity 用例 |
| 键 | `system_config.boss_next_spawn_time` | v40 顺带 DELETE，代码不再读取 |
| time-skip | `boss_manager.TIME_SKIP_ENTRIES` 首条 + 「Boss/灵眼」共享标签 | 首条随文件删除；标签改「灵眼下次刷新时间」，同步 README / registry 测试 |
| GM | `core/gm_manager.py::生成Boss`、`BOSS_ADMINS` | **2026-11-05 修订：保留并改接新领域**——顶层 `生成Boss [profile_id]`（`BOSS_ADMINS`）与 `GM 生成Boss [profile_id]` 都调 `ensure_spawn`，三分支：无 active 生成 / 未知 id 明确失败 / 有 active 复用并回报实际 Boss；只有管理入口可传 `profile_id`，poller 一律 `None`；`broadcast_callback` 改走 outbox |
| 测试 | `tests/test_boss.py`（18 用例）、`test_feature_switches.py`（6 条）、`test_gm_manager.py`、`test_time_skip_registry.py`、`test_migration.py`、`test_skill_equip_and_tome.py:168`、`test_pve_persistence_foundation.py:254/266` | 删除/改写/更新期望，全部列入执行清单 |
| 配置 | `config/game_config.json`、`data/default_configs.py` 的 `boss` 段 | 保留 key，更新 comment 为新玩法 |

## 4. 新入口装配

- catalog 装配复用 D 的 `_wire_core_services` 注入（D 归档后提供；E2 不重复 `load`，以同一实例注入 `PVECombatManager`）；v2 config 下自动启用，v1 → disabled + 维护文案。
- lifecycle poller：指数退避循环（`min(60 * 2**n, 3600)`），`initialize()` 启动、`terminate()` cancel；每轮 `ensure_spawn / expire_active / dispatch_events`。
- outbox dispatcher：读取已提交事件 → 展开 per-destination delivery → 逐条 claim 发送；网络 await 在事务外；`uncertain` 仅人工处置。
- 零奖励过渡：本轮只落台账事实；不新增参与保底/分档/末击彩蛋数值；广播文案不承诺奖励。

## 5. 验证矩阵

- 内容：draft / 缺 manifest / hash 漂移 / 列范围越权 → 正式 config 零修改；批准后 count 28+4、id 唯一、运行时 profile hash 一致；占位叙事未显式批准则 fail closed；**正式产物含 `world_bosses[*].narrative_approved=true`**（sync 由 manifest 派生，D 门控据此放行广播，缺省 false）。
- 切流：28 名册在历练 / 秘境默认路径可达；改 `pve.difficulty_multiplier` 伤害随之变化；旧派生不再命中；`top` 组不存在；`low/mid/high` 在 `catalog=None` 回落时仍可用；`legacy_guardian` 仍可用。
- 旧删（判据必须可机械执行且交付后真能为 0）：① `grep -rnw --include='*.py' "BossManager\|boss_handlers\|BOSS_CONFIG\|boss_manager" main.py handlers managers core config config_manager.py data scripts` → 0（**必须 `-w`**，否则新建的 `world_boss_handlers`/`WorldBossManager` 会被误伤）；② `grep -rn --include='*.py' "boss_config" config_manager.py data/default_configs.py main.py handlers managers` → 0（前提：`managers/enemy_manager.py:364-368` 局部变量改名 `boss_mult`）；③ `test ! -e config/boss_config.json`；④ `boss_next_spawn_time` 产品代码 0 读 0 写、只允许出现在 v40 `DELETE` 与测试；⑤ `stone_reward` 以 `grep -rn "boss.*stone_reward\|stone_reward.*boss"` → 0 为准（`bounty_manager.py:493/502` 局部变量与本域无关）；⑥ `boss` 表不存在（v40 专用用例）；⑦ `lint_narrative.py` 不再读已删文件；⑧ 玩家可见文案不再承诺 Boss 掉落。**统一加 `--include='*.py'`**：`__pycache__` 的旧 .pyc 会输出 binary matches，否则「→0」永不成立。
- 新启：poller 起停、指令可达、Boss 生命周期、北京日 3 次、并发唯一末击、CAS 失败不扣次数、outbox partial success、重启恢复。
- HP 锚：正式 config 的 4 只 profile 复跑 D AC9（阶段 40/40/20 加权、±10%、3 次/日 × 2 日磨死）。
- time-skip：Boss 到期/再生生效；anchor / pending / date_key 不受影响。
- 文案与用例：`handlers/misc_handler.py:131`、`handlers/shop_handler.py` 的 `ITEM_ACQUIRE_HINTS`、`handlers/storage_ring_handler.py:120/:528` 不再承诺 Boss 掉落；`functional_tests/cases/pve/pve-smoke.json` 的「世界Boss」断言（`re:Boss|BOSS|boss|暂无|未生成`）仍可命中新回复。
- 回滚演练：备份恢复后旧版本可读（不允许混合 schema）。

## 6. 风险

| 风险 | 对策 |
|---|---|
| 只 sync 不切流 → 28 名册成为死配置、父 AC3b 无法关闭 | 切流作为独立 R2 + AC2 可观察证据（名册可达 / 旧派生不命中） |
| 切流漏传 `difficulty_multiplier` / 二次 `load_catalog` / 误删 `low/mid/high` | R2 写死系数来源、同一实例与装配顺序、低中高保留为 v1 回落，并补改写旋钮、wiring 与回落用例 |
| CSV 全 draft 直接 sync 必 fail closed | R1 明确两步批准：用户侧 `status→final` + 重算 hash/manifest，AI 不得代改 |
| 删旧与启新不同步导致无 Boss 玩法或双跑 | 同一提交/检查点；smoke 失败整批回滚 |
| 删 `boss_config.json` 打断 lint 闸门 / 被默认值重建 | 配置三元组 + lint 依赖同批处理 |
| v40 DROP 无回退 | 备份 + 只允许整组合回滚（代码/DB/config） |
| 占位叙事被当作已批准上线 / 照默认集写 manifest 导致全量 fail closed | manifest 的 `narrative_status` 必须按 CSV 实际填：全占位时写 `["占位"]`（默认集 `{定稿, 豁免}` 会 32 行全拒）；放行占位须用户明确同意并回写设计 |
| 测试硬编码旧文件/旧版本号 | 删除矩阵显式列 `test_skill_equip_and_tome` 与 `test_pve_persistence_foundation` 的更新 |

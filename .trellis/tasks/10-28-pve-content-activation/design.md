# Technical Design: PVE 内容激活与旧 Boss 整删切流

## 1. Cutover 形态

- 保留 `game_config.boss.enabled` 作为**新**世界 Boss 总开关（语义从「旧随机 Boss」改为「生命周期玩法」），`pve.enabled` 继续作 PvE 总闸；不新增第二开关，避免旧/new 双跑。
- 回滚 = git revert + 同检查点 DB/config 备份，不做 config 级并存。

激活顺序（同一检查点）：

```text
内容批准（combat / narrative 独立；用户侧升 status 并重算 hash/manifest）
  -> sync preview（count/hash/schema；写 narrative_approved 后过 validate）
  -> 删 enemy_groups 中 key=top 的组
  -> 正式写 config/enemies.json（v2，含 world_bosses 段）
  -> 普通 PVE 切流（catalog.spawn_enemy + 显式 difficulty_multiplier）；旧派生退役
  -> 停旧：删旧 Boss 实现/配置三元组/表（v40 DROP）/键/测试 + lint_narrative 改读 + GM 改接
  -> 启新：复用 D 的 catalog 装配、注册 poller、切 handler、outbox dispatcher
  -> 承接延迟项（地板 API 改调 / 暴击形参补传）+ HP 锚复跑 + smoke + 完整回归 + 文档同步
```

## 2. 普通 PVE 切流

- `catalog is not None` → `spawn_enemy(player_level, category, difficulty_multiplier)`，系数显式取自 `game_config["pve"]["difficulty_multiplier"]`（None→1.0）；旧路径在 `EnemyManager` 内读该系数，漏传会让全局旋钮静默失效。
- `catalog is None` → 保持旧动态派生，不半切。
- catalog 实例由 D 装配，E2 复用（必要时把 `load_catalog` 行上移），不得二次 load；构造参数注入、不用 setter。
- 定向组继续走 `enemy_groups`：`legacy_guardian` 必留；`low/mid/high` 保留为 v1 回落（消费者是旧派生 `_get_group_by_level`）；只删 `key=top`（sync 前对现有 config 执行；若改到 sync 后删，必须同时手工删生成配置里的同组）。
- 旧派生静态保留（不删），仅运行态不再命中。

## 3. 旧 Boss 整删矩阵

| 类型 | 对象 | 处理 |
|---|---|---|
| 代码 | `managers/boss_manager.py`、`handlers/boss_handlers.py`、`models_extended.Boss`、`data/database_extended.py` boss CRUD | 整文件/整段删除 |
| 代码 | `main.py` 的 `_schedule_boss_spawn`/`_broadcast_boss_*`/`boss_next_spawn_time` 读写 | 删除，新 poller 接管 |
| 配置 | `config/boss_config.json` + `default_configs.BOSS_CONFIG` + `config_manager` 的属性与 import | 三处同批删除（缺一重建或 ImportError） |
| 工具 | `lint_narrative.py` 的 `boss_config.json` 映射 | 改读 `enemies.json` v2；**不要删映射**（`desc_tables`+`name_maps[table]` 会 KeyError） |
| 表 | `boss` fresh DDL | 删建表；v40 `DROP TABLE IF EXISTS boss`，`VERSION_SCHEMA_TABLES[40]=()`；补 v40 parity 用例 |
| 键 | `system_config.boss_next_spawn_time` | v40 顺带 DELETE，产品代码 0 读写 |
| time-skip | `boss_manager.TIME_SKIP_ENTRIES` 首条 + 「Boss/灵眼」共享标签 | 首条随文件删；标签改「灵眼下次刷新时间」；**删 `_PROVIDER_MODULES` 里的 `managers.boss_manager` 元组项** |
| GM | 顶层 `生成Boss`、GM 子命令、`BOSS_ADMINS` | **保留并改接 `ensure_spawn(profile_id)`**（D R1 三分支）；`broadcast_callback` 停用改 outbox |
| 文案 | misc 帮助行、shop `ITEM_ACQUIRE_HINTS`、storage_ring「Boss击杀掉落」 | 改为不承诺 Boss 掉落 |
| 测试 | `test_boss.py`、`test_feature_switches` 6 条、`test_gm_manager`、`test_time_skip_registry`、`test_migration`、`test_skill_equip_and_tome`、`test_pve_persistence_foundation` | 删除/改写/更新期望 |

`config/game_config.json` 与 `default_configs.py` 的 `boss` 段保留 key，只更新 comment。

## 4. 新入口装配

- 复用 D 的 `_wire_core_services` 注入（E2 不重复 load）；v2 config 自动启用，v1 → disabled + 维护文案。
- lifecycle poller：指数退避（`min(60 * 2**n, 3600)`），`initialize()` 启动、`terminate()` cancel；每轮固定 `expire_active → ensure_spawn → dispatch_events`，先提交到期终态再做生成资格判断。D 的 ensure 仍须在自己的事务内幂等处理到期 active，防止 GM 等其他调用方绕过 poller 顺序。
- outbox dispatcher：读已提交事件 → 展开 per-destination delivery → 逐条 claim 发送；网络 await 在事务外；`uncertain` 人工处置。
- 零奖励过渡：只落台账事实，不新增保底/分档/彩蛋数值，广播不承诺奖励。

## 5. 验证矩阵

- 内容：draft/缺 manifest/hash 漂移/列越权 → 正式 config 零修改；批准后 count 28+4、id 唯一、profile hash 一致；combat-only 占位产物 `narrative_approved=false` 且不广播，只有独立叙事批准的 `定稿` 或显式 `豁免` 才为 true；共享 Schema、真实加载与叙事快照链路按 §7 验收。
- 切流：28 名册在历练/秘境可达；改 `pve.difficulty_multiplier` 伤害变化；旧派生不再命中；无 `key=top`；`low/mid/high` 在 `catalog=None` 回落可用；`legacy_guardian` 可用。
- 旧删：`audit_pve_redesign.py --scope e2` 为 0；`boss` 表不存在（v40 专用用例）；`lint_narrative` 不读已删文件；玩家文案无 Boss 掉落承诺。
- 新启：poller 起停与固定调用顺序、到期后换不同 profile 仍单 active、三个命令可达、生命周期、北京日 3 次、并发唯一末击、CAS 失败不扣次数、outbox partial success、重启恢复。
- HP 锚：正式 config 的 4 只 profile 复跑 D AC9。
- time-skip：Boss 到期/再生生效；anchor/pending/date_key 不受影响。
- 回滚演练：备份恢复后旧版本可读（不允许混合 schema）。

## 6. 风险

| 风险 | 对策 |
|---|---|
| 只 sync 不切流 → 名册成死配置、父 AC3b 无法关闭 | R2 独立 + AC2 可观察证据 |
| 切流漏传难度系数 / 二次 load / 误删 low-mid-high | R2 写死来源、同一实例、v1 回落保留 |
| CSV 全 draft 直接 sync | R1 两步批准，AI 不得代改 |
| 占位叙事被当已批准 / 照默认集写 manifest 全拒 | manifest 按实际填 `["占位"]` 只放行 sync；占位始终 `narrative_approved=false`，只有 `定稿`/显式 `豁免` 可 true |
| 叙事批准结论没正确落进 profile → 占位误广播或定稿广播全哑 | sync 按 R1 逐行写 `narrative_approved`，D builder 缺省 false；真实加载链见 §7 |
| 把文案误接入 `narrative_config.json` / 代码 fallback → 双来源或未批准文案被当正式内容 | 只走 CSV→enemies.json→profile→出生快照，见 §7 |
| 删旧与启新不同步 → 无 Boss 或双跑 | 同一提交/检查点，smoke 失败整组回滚 |
| 删 `boss_config.json` 打断 lint / 被默认值重建 | 三元组 + lint 同批；D 删除与 lint 改读同一提交 |
| v40 DROP 无回退 | 备份 + 只允许整组合回滚 |
| 清零判据与代码漂移 | 判据脚本化（audit），文档只写「跑脚本」 |

## 7. 配置 Schema、真实加载与叙事单链路

- **共享 Schema 属主**：沿用 `core/enemy_schema.py` 的 `build_world_boss_profile`、`_WB_PROFILE_REQUIRED_KEYS`、`validate_enemy_document` 和 `managers/enemy_catalog.py` 的 `WorldBossProfile.from_dict`，不另建配置校验层。新增字段、必填/默认值与类型契约由 D prd R7 唯一定义；E2 的责任是在正式 sync 前确认 D 已交付，并用正式产物复验整条链，而不是只检查 JSON 已生成。
- **叙事唯一来源**：`world_bosses.csv` 五叙事列 → `sync_content_to_config.py` → `config/enemies.json` 的 `world_bosses` → `EnemyCatalog`/profile → D 出生快照 → renderer。世界 Boss 不使用 `config/narrative_config.json` 或 `copy_variants.csv`，不新增对应场景键，也不设代码文案 fallback；正式内容仍须用户批准，生成配置禁止手改。
- **lint 门**：`design_docs/content-design/lint_narrative.py` 继续以 `world_bosses.csv` 为文案源，对五叙事列复用现有文本检查；旧 Boss 配置删除时按 §3 把名称映射改读 `enemies.json` v2。`narrative_approved=false` 的 preview/占位内容只允许验证「不广播」，不得作为正式文案验收证据。
- **真实加载契约测试**：正式 `render_enemy_document`（manifest）→ `validate_enemy_document` → 写入临时 `enemies.json` → 真实 `ConfigManager` 加载 `game_config` 的开关/难度配置，同时由 `EnemyCatalog.load` 加载该生成文件 → `world_boss_by_id` 构造 profile → D `ensure_spawn` 固化快照 → renderer 生成 spawn/phase/defeated/dissipated 四类事件。分别覆盖 combat-only 占位与独立叙事批准/豁免，断言前者快照 false 且不广播、后者按 R1 为 true。`ConfigManager` 不负责读取 `enemies.json`，不得为通过测试新增第二加载入口。
- **契约测试矩阵**：合法且叙事已批准的完整配置可加载、五文案与快照逐字一致且 `narrative_approved=true`；每个新增必填键缺失、类型错误或已批准空文案均在 Schema/加载边界 fail closed；未批准/preview 保持 false 且不广播；旧 v1 配置使 `load_catalog` 返回 `None`、新领域 disabled，不得与 v2 字段混读。

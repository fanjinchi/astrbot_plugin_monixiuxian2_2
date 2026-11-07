# Implementation Plan: PVE 内容激活与旧 Boss 整删切流

## 依赖与门

1. D 归档（领域 + fixture + poller 函数 + `ensure_spawn(profile_id)` 三分支 + AC9 证据）。
2. E1 归档（地板单源 + 消费者 + 暴击双侧接线 + 事务叶子 + 通用文档）。
3. 用户内容批准（combat / narrative 独立，外部门）。
4. 激活前备份：DB 文件、`config/enemies.json`、`system_config.boss_next_spawn_time` 现值、CSV 旧 SHA-256。

## Steps

1. 备份与基线：DB / 生成配置 / CSV hash 快照；跑完整 pytest 确认起点绿；跑 `audit_pve_redesign.py --scope all` 记录基线。
2. 内容门复核：draft CSV 跑 preview + 一次 formal（**带 draft manifest 或缺失 manifest 的敌人域调用**；CLI 不带 manifest 时会跳过敌人域照写其余配置）；确认 `test_enemy_sync_gate` 覆盖负例，并补正向用例：`status=final` + `占位` + manifest `["占位"]` → 0 错且 `narrative_approved=false`；另补 `定稿`/显式 `豁免` → true 的独立叙事批准用例。
3. 批准展示与 `status` 升级：展示 28+4 的 status/narrative_status/manifest/hash/列范围/diff；manifest 形状与 `narrative_status` 填法按 prd R1（本批全 `占位`）；给出可复制命令（插件根执行，`json.dumps` 直接产出 manifest）。**用户侧**改 status 后重算 hash 并再展示 diff；AI 不得代改 CSV 或批准。
4. sync 前删 `enemy_groups` 的 `key=top` 组；先按 `design.md` §7 核对 D 已交付共享 Schema/profile 五文案与 `narrative_approved` 契约（未交付则返回 D，不在 E2 另建 Schema），并让 `lint_narrative.py` 覆盖 `world_bosses.csv` 五叙事列。正式 sync：`sync_content_to_config.py --approval-manifest <path>`；校验 count 28+4 / id 唯一 / schema / hash；按 prd R1 逐行核对批准结论：**占位即使放行 sync 也必须 `narrative_approved=false`，只有独立批准的 `定稿` 或显式 `豁免` 才为 true**；不手改配置，不接 `narrative_config.json`。随后跑 §7 真实加载契约矩阵：正式产物经 Schema、`EnemyCatalog.load`、profile、出生快照到 renderer；真实 `ConfigManager` 只负责 `game_config` 开关/难度；覆盖合法完整、新增键缺失/类型错误、已批准空文案、combat-only 不广播与旧 v1 disabled。
5. 普通 PVE 切流：`prepare_encounter`/`challenge_rift_beast` 默认出怪走 `catalog.spawn_enemy(..., difficulty_multiplier)`（系数取 `game_config["pve"]["difficulty_multiplier"]`，None→1.0）；catalog 装配归 D，E2 仅在需要时把 `load_catalog` 行上移，不二次 load、不用 setter；catalog None 保持旧派生。补用例：28 可达 / 改旋钮生效 / 旧派生不命中 / 元婴段只出本段 / `catalog=None` 回落不刷守护 / v2 下 catalog 非 None；`enemy_manager` 局部变量 `boss_config`→`boss_mult`；同步 `spawn_enemy` docstring。wiring 断言用单元测试 + `main.py` 源码顺序静态断言（**不要依赖 XiuXianPlugin mock harness**：它 mock `.core` 后 `main.py` 相对导入报 ModuleNotFoundError，单跑会炸、整仓跑绿是导入顺序依赖）。
6. 旧 Boss 整删（与 step 7 同一 commit）：按 design §3 矩阵删代码/配置三元组/表/键/测试；改 `lint_narrative` 读 `enemies.json` v2（不删映射）；v40 登记 `VERSION_SCHEMA_TABLES[40]=()` 与 `NEW_TABLES[40]=()`；time-skip 标签改名、世界 Boss 两条迁属主模块并**删 `_PROVIDER_MODULES` 的 `managers.boss_manager` 元组项**；GM 三项保留并改接 `ensure_spawn`（三分支，仅管理入口可传 profile；`broadcast_callback` 停用）；玩家文案去掉 Boss 掉落。**装配点逐项改**：`main.py` 的 BossManager/BossHandlers 导入与构造、`BossManager` 构造、GM 位置参数与 `broadcast_callback`、`BossHandlers(...)`、services 字典键、`config_manager.boss_config` 读取、`_broadcast_boss_spawn` 两处、三个命令的 handler 落点**与三处 docstring 的 `routes to boss_handlers.*`**；`生成Boss` 的 profile 参数用 `GreedyStr` 形参（与 `handle_gm` 同构）或 `get_message_str()` 后剥指令名，不用 `event.message_str`。
7. 新入口启用（与 step 6 同一 commit）：复用 D 的 catalog 装配；`boss.enabled` comment 更新；注册 poller（指数退避，每轮 `expire_active → ensure_spawn → dispatch_events`）与 outbox dispatcher；切三个命令到新 handler。补开关/启动用例：`false` 时新 poller 不生成且旧生成器已不存在，`false→true` 后下轮按 D 资格恢复，启用态重启不双跑；补旧实例在两次 poll 间到期且新随机 profile 不同的回归，断言任意时点至多一个 active；含旧 `boss` 表/数据的旧库经 v40 后可启动且旧表/key 删除。
8. 承接延迟项与端到端验收：若 D 落地时地板仍引用旧常量 → 改调 `HealthService.defeat_hp_floor`；若 `build_enemy_fighter` 无 `base_crit_rate` → 补传；然后 spawn→challenge→phase→终态→respawn、北京日 3 次、并发末击、CAS 失败、重启、time-skip 矩阵、广播 partial success、正式 config 复跑 D AC9、`pve-smoke` 断言核对、零奖励过渡记录。逐类核对 spawn/phase/defeated/dissipated 事件取自已批准出生快照，未批准时不广播，任何路径均无 `narrative_config.json` 或代码文案 fallback。
9. 回滚演练与文档：按 R6 清单逐项同步（`pve-enemy-design`、`current-design-report`、`project-architecture`、`api-overview`、两个 README、`sect-system-design`、插件 README、metadata、修仙帮助）；记录批准/sync/切流/回滚证据；`audit_pve_redesign.py --scope all` 为 0。

## 回滚点

- RP1：sync 前（config/DB/CSV hash 备份）；
- RP2：旧删 + 切流 + 新启同一检查点前（代码/DB/config 三者同点备份）；
- 任一步失败：整组回滚（git revert + 备份恢复），禁止半回滚或旧/new 并存。

## 完成证据

- 内容批准记录（用户确认 + status 变更 + manifest/hash）+ sync 校验输出 + combat-only 占位为 false 且不广播、独立叙事批准/豁免才为 true 的证据 + `design.md` §7 共享 Schema/真实加载/叙事快照契约矩阵摘要；
- 切流证据（28 可达、改旋钮生效、旧派生不命中、top 组删除、legacy_guardian 回归、catalog=None 回落）；
- 旧 Boss 清零：`audit_pve_redesign.py --scope all` 为 0 + `boss` 表不存在（v40 parity）+ lint 不读已删文件 + 玩家文案无掉落承诺；
- 正向批准用例（占位经 manifest 放行）记录；
- 端到端/并发/time-skip/广播测试摘要 + HP 锚复跑数据 + 到期换 profile 单 active、开关切换、重启与旧库 v40 升级启动证据；
- 回滚演练记录；产品范围 ruff / 完整 pytest 摘要。

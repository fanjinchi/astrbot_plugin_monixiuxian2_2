## 1. 数据层：迁移 v32 + 模型 + DAO

- [x] 1.1 `data/migration.py` 新增 v32 迁移：创建 `legacy_instances`（id PK AUTOINCREMENT, owner_id TEXT, legacy_type TEXT, impart_value INTEGER DEFAULT 0, claimed_tiers TEXT DEFAULT '[]', sect_id INTEGER NULL, acquired_at INTEGER）与 `impart_pk_cooldown`（challenger_id, target_id, failed_at，联合 PK）；拷贝 `impart_info` 全部行 → `legacy_instances`（legacy_type='common'，保留 value/claimed）；同事务 DROP `impart_info`；LATEST_DB_VERSION 31 → 32
- [x] 1.2 `models_extended.py` 新增 `LegacyInstance` 数据类（含 from_row/claimed_tiers JSON 解析），替代 `ImpartInfo`
- [x] 1.3 `data/database_extended.py` 新增实例 DAO：create_legacy_instance / get_legacy_instance_by_id / list_legacy_instances_by_owner / update_legacy_instance / delete_legacy_instance / delete_legacy_instances_by_owner_sect；冷却 DAO：get_impart_pk_cooldown / upsert_impart_pk_cooldown；敏感更新走 BEGIN IMMEDIATE 事务
- [x] 1.4 `data/data_manager.py`（L176 删玩家处）连带删除该玩家的传承实例与冷却记录；并**移除**旧的 `DELETE FROM impart_info` 语句（DROP 表后执行会报错）

## 2. 配置：类型分表 + 守护 NPC + 奖励落地

- [x] 2.1 `config/impart_config.json` 重构为 `{ cultivation_points_every_minutes: 15, types: { common/sect/adventure/rift: { name, tiers: [{tier, impart_value_required, rewards}] } }, guardian: { enemy_group: "legacy_guardian" } }`，保留原 20/40/60/80/100 五阶为 common 默认
- [x] 2.2 `data/default_configs.py` 补齐 impart 完整默认配置（缺失时 `_load_config_with_default` 不空转）
- [x] 2.3 `config/enemies.json` 增加 `legacy_guardian` enemy_group：**不带 `level_range`**（避免被普通 PvE 的 `_get_group_by_level` 匹配劫持），templates 按境界段配置，仅经新增的 `spawn_enemy_from_group` API 触达
- [x] 2.4 在 `design_docs/content-design/heart_methods.csv`、`skills.csv` 补齐传承奖励条目（传承心法·吐纳/归元、传承功法×2），运行 `uv run python scripts/sync_content_to_config.py` 同步进 `config/heart_methods.json`/`config/skills.json`（修复奖励 id 空转）
- [x] 2.5 `config/adventure_config.json` 与 `config/rift_config.json` 增加 `legacy_chance`；`config/sect_factions.json` 各宗门配置新增 `legacies` 列表承载宗门传承条目（宝库条目字段实为 `type`，`kind` 是 `sect_manager._get_treasury_entries` 映射产物——宗门传承作为独立 `legacies` 列表配置，领取时映射为 kind=legacy）
- [x] 2.6 确认配置加载适配新结构（`config_manager.py` impart 读取路径不变，types 结构在 manager 层解析）

## 3. Manager 核心：impart_manager 重构

- [x] 3.1 新增 create_legacy(owner, legacy_type, sect_id=None) / list_owner_legacies(user_id) / get_ranking()（按玩家全部实例传承值总和降序）
- [x] 3.2 重写 add_impart_value(instance_id, delta)：按实例 legacy_type 读取对应 types.tiers，阈值达成自动发放该等阶奖励并标记 claimed_tiers（心法入储物戒 / 功法学入 player_skills(source='impart') / level_up 提境界），同实例不重复发放
- [x] 3.3 新增 transfer_legacy(instance_id, new_owner)：单事务 owner 改写 + impart_value=0 + claimed_tiers=[]（PK 夺取清零）
- [x] 3.4 新增冷却：can_challenge(challenger_id, target_id) / record_challenge_failure（5×86400 秒，含当日）；get_impart_ranking 文案对齐

## 4. 修炼累积传承值

- [x] 4.1 `handlers/player_handler.py` `handle_end_cultivation` 出关时对玩家全部实例 `add_impart_value(effective_minutes // 15)`，同事务提交
- [x] 4.2 出关消息追加传承值增长行（各实例类型 + 增长点数；无实例则不显示）

## 5. PK 夺取制

- [x] 5.1 重写 `managers/impart_pk_manager.py::challenge_impart`：目标实例选择（可选类型参数过滤，否则取被挑战者 acquired_at 最近一条**非 sect** 实例；无可夺目标提示）；战斗沿用 CombatEngine(combat_type='impart_pk')；胜 → transfer_legacy + 提示清零重练；平局 → 不转移不冷却；败 → **保留扣除 1% 当前修为的现状惩罚** + record_challenge_failure + 提示 5 天冷却
- [x] 5.2 `handlers/impart_pk_handlers.py` 支持「传承挑战 <@某人> [类型]」参数解析，胜负文案更新（夺取/冷却/宗门不可夺）；`main.py` CMD_IMPART_CHALLENGE 路由同步
- [x] 5.3 新增「激活传承」指令组：`CMD_IMPART_ACTIVATE` 常量 + `@filter.command` 路由（main.py）+ `handlers/impart_handlers.py::handle_impart_activate`（无参列出可激活实例，带编号调用 `impart_mgr.activate_legacy`），帮助文本说明仅激活实例累积

## 6. 获取途径：守护 NPC 挑战

- [x] 6.1 守护挑战独立函数（`managers/pve_combat_manager.py` 新增）：`EnemyManager.spawn_enemy_from_group("legacy_guardian", player_level)`（新 API，见 6.0）→ `build_fighter` → CombatEngine 结算 → 写回 player.hp（失败设下限不死 ≥1）→ 仅返回胜负与战报；**无概率 roll、无修为/金币/掉落结算**。另在 `managers/enemy_manager.py` 新增 `spawn_enemy_from_group(group_key, player_level)`：按组 key 取组、玩家境界在组内 templates 选取
- [x] 6.2 `managers/adventure_manager.py` 历练结算：按 `legacy_chance` 掷概率 → 命中触发守护挑战 → 胜利创建 type='adventure' 实例（失败消耗本次机会）
- [x] 6.3 `managers/rift_manager.py` `finish_exploration`：同上 → type='rift' 实例
- [x] 6.4 `managers/sect_manager.py` `claim_treasure` 扩展 kind=legacy 分支：先守护挑战 → 成功创建 type='sect' 实例（sect_id 绑定当前宗门）并占「每人限领一次」名额；失败不占名额可重试。**实现提示：`claim_treasure` 全程 `BEGIN IMMEDIATE` 事务，守护挑战为异步战斗，必须在事务外完成挑战，成功后再开事务创建实例与占名额**
- [x] 6.5 `reclaim_sect_treasures` 扩展删除该玩家持有的该宗门 sect 传承实例；调用点：`sect_manager.py:472`（主动退出）、`sect_manager.py:780`（踢出）；第三调用点 `handlers/player_handler.py:562`（弃道重修）由 1.4 的删玩家级联删除覆盖，无需单独处理
- [x] 6.6 `main.py` 装配注入：`sect_mgr.impart_mgr`、`sect_mgr.pve_combat_mgr`、`adventure_mgr.impart_mgr`、`rift_mgr.impart_mgr`、`player_handler.impart_mgr`（impart_mgr 在相关 manager 之后 init，setter 注入）；同时修复 `sect_manager.py` 缺失的 `from ..models import Player` import

## 7. 传承信息与排行

- [x] 7.1 `handlers/impart_handlers.py` 传承信息面板改版：列出全部实例（类型/传承值/等阶进度/已领取奖励）
- [x] 7.2 传承排行按实例总和排序（`get_impart_ranking` 口径更新）

## 8. 测试

- [x] 8.1 `tests/test_migration.py` 增补 v32：两新表结构、旧数据完整迁移（值/claimed 保全）、幂等（重复启动）、DROP 旧表
- [x] 8.2 `tests/test_impart_manager.py` 重写：实例创建/多条持有/修炼累积粒度（15 分钟、不足不累计）/tier 自动发放（含奖励 id 存在性校验）/transfer 清零/冷却边界（第 5 天拒绝、5×86400 后放行、不同对手不受限）/宗门传承不可夺/排行总和/**战力断言**（`build_fighter_from_player` 输出不含传承值项，同战力不同传承值无偏移）
- [x] 8.3 `tests/test_sect_manager.py`（若存在）扩展：宗门传承领取（守护挑战成功/失败不占名额）与离宗回收；补充 `legacy_chance=0` 时历练/秘境不触发的断言
- [x] 8.4 新增 `functional_tests/cases/pvp/legacy-basic.json`（传承展示/夺取/保护/冷却/GM 预置清除全路径），`test_suite_ctl.py sync-cases && run --case legacy-basic` 连续两次通过（可重入）
- [x] 8.6 `core/gm_manager.py` 新增「给予传承 [目标] [类型]」「清除传承 [目标] [编号]」「清除传承状态 [目标]」子命令（路由表注册 + handler + GMCommand 表 + 帮助文本），`main.py` 装配注入 `impart_manager`；legacy-basic 用例改为 GM 预置传承的完整夺取/冷却/保护路径（用例开头用「清除传承状态」保证可重入）并重跑通过
- [x] 8.5 回归：`uv run ruff format . && uv run ruff check . && uv run python -m pytest tests/ -v`（515 passed）

## 9. 版本与文档同步

- [x] 9.1 `metadata.yaml` v3.10.0 → v3.11.0；`README.md` 更新日志追加 v3.11.0、传承系统节与指令表重写、功能速览更新；`handlers/misc_handler.py` /修仙帮助文本更新（已验证私聊渲染）
- [x] 9.2 `design_docs/current-design-report.md`：4.17 节重写（PK 夺取制 + 修炼累积）、ImpartInfo → LegacyInstance、数据表清单、迁移里程碑 +v32、明确传承值不参与 PK 计算
- [x] 9.3 `design_docs/project-architecture.md`（传承行、迁移里程碑）、`design_docs/api-overview.md`（方法索引）、`design_docs/sect-system-design.md`（宗门传承/宝库 kind=legacy 确认与补充）
- [x] 9.4 手动冒烟（热重载插件后）：私聊传承信息空态/修仙帮助新文本 ✓（挑战胜/败/冷却/保护由 legacy-basic 功能测试端到端覆盖，宗门领取回收/闭关累积由 8.2/8.3 单测覆盖）

# PVE 跨系统收口：气血地板与消费者清零

## Goal

在 A/B/P/C/F 五个前置完成后，把 PVE 气血地板统一到 Health Domain（秘境兽、传承守护者及宗门领取入口），复核全部 HP 消费者并静态清零旧语义，门控 data/ 之外剩余事务叶子，完成文档与版本收尾。旧 Boss 整删、内容 sync 与原子激活切流由 E2（`10-28-pve-content-activation`）承接，不在本 child。

## Dependencies

- 玩家持续气血领域（A）、固定名册内容管线（B）、持久化/事务基座（P）、普通 PVE 结算（C）、逃跑契约重拍（F）——均已归档。
- **不依赖 D**：世界 Boss 领域行为、Boss time-skip/outbox 端到端验收归 E2（D 归档后）。

## Requirements

### R1. PVE 气血地板收口（2026-10-12 甲案）

- 事实基线（2026-10-28 核对，函数名定位、行号以当日审计为准）：`challenge_rift_beast` 战败/平局写死 `1`（`final_hp = ... if won else 1`）；`challenge_legacy_guardian` 为 `max(1, 引擎终值)`。两者都不带 1% 地板，且宗门领取入口战败不落库、胜利在事务内被旧快照覆盖。
- 目标口径：战败/平局 `current_hp = max(引擎终值, ceil(1% * 动态 max_hp))`，胜场按引擎终值不保底。
- 地板单源：`DEFEAT_HP_FLOOR_RATIO` 与 `defeat_hp_floor(player)` 迁入 `core/health.py::HealthService`，`AdventureManager` 改为委托，删除私有副本。**世界 Boss 挑战（D）同样消费该单源**（设计 :886「地板调整全局统一适用：历练 + 世界 Boss」）：D 落地前以同一常量 import，E1 上收后改调 `HealthService.defeat_hp_floor`，不新增第三份 0.01。
- 写回归一：秘境兽/传承守护者改由战斗层经 `HealthService.set_current_hp(...)` 直接落库（宗门领取两条路径都生效）；`PVECombatManager` 增加 `health_service` 注入（装配段 `main.py::_wire_core_services`）。
- PvP（切磋/决斗）写回不适用 PVE 地板，只复核 clamp。
- 静态判据：产品代码不得再有 `current_hp = 1` / `if won else 1` 的败场赋值。

### R2. 全消费者组合复核

- 复核 A 已交付的 base/current/max HP 消费者（创角/突破/装备/功法/丹药/商店/GM/PvP/历练/秘境/传承/显示/排行），补跨玩法 clamp 回归。
- 产品代码与测试不残留含混 `Player.hp`；旧 Boss 实现中的旧语义归 E2 整删，不在此列。
- 补完设计 Step 3 定案③「暴击物化」，**双侧接线**（`pve-enemy-design.md:44/:89/:472-482`）：`config/game_config.json` + `data/default_configs.py` 补 `combat.base_crit_rate=0.15`；玩家侧 `build_fighter_from_player` 传参（`FighterState` 默认值保持兼容）；**怪物侧 `build_enemy_fighter` 增可选 `base_crit_rate` 形参**：`enemy.crit_rate > 0` 时按 /100 覆盖，否则回退该键（默认 0.15）。依据封板 `:480-482`「两个构建点统一从该键取值、怪物有配时覆盖」。现状：第一季 28 只与 4 只世界 Boss 的 CSV **都没有 `crit_rate` 列**（`core/enemy_schema.py:394/:500` 的 builder 默认 0），因此全部走回退——默认 0.15 时行为逐点不变，第二季配 per-enemy 值即可覆盖。当前 `managers/combat_manager.py:234` 的 `_base_crit_rate` 是**读值零消费**的死读取，属设计警告的「半接线」状态。**范围边界**：玩家目前没有任何暴击率加成来源——`Player` / `get_total_attributes` 不聚合 crit，武器/护甲/心法/丹药表也没有暴击字段，内容侧只有「暴击时触发/暴击增伤」类技（如战意诀 `trigger_condition=crit`，`design_docs/content-design/skills-ultimates.md`、`weapon-skills.md:42-46`），它们消费暴击但不提供暴击率；本轮只做「物化 + 双侧接线」，不新增玩家暴击加成通道（词条专项另开）。

### R3. 事务叶子清零

- 门控 data/ 之外剩余 5 处裸 `conn.commit()`（按 `conn._txn_depth` 叶子门控，与 `data/` 同一 idiom）：`managers/spirit_farm_manager.py`（种植写点）、`managers/spirit_eye_manager.py`（生成/释放两处）、`managers/bounty_manager.py::check_and_expire_bounties`、`managers/dual_cultivation_manager.py`（发起请求插入）。
- 文档/评审以函数名定位，行号由审计脚本当日生成。bd `-dfb`（叶子门控跨任务竞态，P1 open）未修前不新增依赖叶子提交的并发路径；若 -dfb 收口为 `db.leaf_write`，这 5 处跟随迁移。

### R4. 文档与版本收尾

- 口径同步（逐项）：
  - `design_docs/content-design/pve-enemy-design.md`：§Q4 地板收口范围改写（四处已统一、删「过渡期并存」、把「仍裸写引擎终值」改为 `else 1` / `max(1, 终值)` 的真实事实、枚举「宗门宝库领取」入口）；`:755`「待选择 busy 唯一用途是挡住开始历练」改为「唯一职责是挡住开始新活动（实现为忙碌白名单拦截），不再承担挡回血」；`:472-476`（坑#3「`crit_rate` → 接线（默认回退语义）」）与 `:477-482`（玩家侧断链）两段在 E1 落地后都失真 → **两段同批改写**为「玩家侧从 `combat.base_crit_rate` 读取并传参；怪物侧 per-enemy `crit_rate` 优先、未配置时回退该键（默认 0.15 行为逐点不变，第一季 28 只不配）」——只改一边会留下自相矛盾；同段已漂移的行号一并更正（`:716-717` 的 `pve_combat_manager.py:416/:469` → 现 `:504`/`:568`；`:479` 与 pit#3 `:89` 的 `combat_manager.py:219` → 现 `:234`）；`:758-760`（「全段触发/收益侧另开任务、实施前仍首版契约」）已过期（F 已落地）→ 删除或改写为已完成；附录 B 决策记录④就地改为 1% + 全风险段 ×0.3。
  - `design_docs/current-design-report.md`：§4.7 奖励与秘境行、§4.12「失败/平局 HP→1」、§4.17「失败/平局…气血下限 1」、`:208` base_crit_rate、§五 数据库版本（v32→v39；v40 由 E2 升）与表清单/迁移历史；**同文档 `:11`「数据库结构以 `data/migration.py` 最新版本 v34 为准」与 `:40`「migration.py # 版本化迁移（当前 `LATEST_DB_VERSION = 30`）」两处硬编码版本号也要改到实际值**——否则改完 §五 后同一文档仍并存 39/34/30 三个版本号，AC7a「文档与实现一致」无法自证。
  - `design_docs/project-architecture.md`：只改 `:74` 历练行「高/极高风险挂 `pending_choice`」→ 全风险段，以及 `:16`/`:132` 数据库版本号 → v39（`managers`/`models`/定时任务/世界 Boss 两行归 E2；D 落地前改写这些行只能写出与代码不符的描述）。
  - `design_docs/api-overview.md:108`：`HealthService` 方法表补 `defeat_hp_floor`。
  - `managers/rift_manager.py` 与 `managers/pve_combat_manager.py` 的 **docstring 与行内注释**（「气血降为 1 / HP 下限 1」，含 rift_manager 两处行内注释）同步；`managers/rift_manager.py` 的 3 处 `await self.db.update_player(player)`（胜利/失败/传承分支）保留、写回值一致（`HealthService.set_current_hp` 已同步内存对象），注释改为「非气血权威写点」；**不要宣称「无竞态」**——这 3 处是整行回写，仍受 AGENTS §3 约束。
- AGENTS §7 清单：`metadata.yaml` version、`README.md` 更新日志与指令表、`/修仙帮助` 文本。

### R5. 质量门

- `uv run ruff format .` + **产品范围** ruff（`uv run ruff check core managers handlers data utils main.py models.py models_extended.py tests`）+ `uv run python -m pytest tests/ -v`；真实 webtest 仅用户明确要求时运行。

## Out of Scope

- 旧 Boss 实现/表/键/测试整删、内容 sync/批准与激活切流（E2）。
- 世界 Boss 领域行为与端到端验收（E2，D 归档后）。
- Step 7 奖励经济、正式秘境生态与叙事创作、战斗引擎通用公式再平衡。

## Acceptance Criteria

- [ ] AC1：秘境兽（秘境应邀）与传承守护者（秘境应邀 + 宗门宝库领取）战败/平局残血 = `max(引擎终值, ceil(1% 动态 max_hp))`（至少 1），胜场不保底；PvP 不受地板影响；产品代码无 `else 1`/`current_hp = 1` 败场赋值。
- [ ] AC2：地板单源——`HealthService` 提供地板 API，历练/秘境/守护者三类入口已消费、无第二份 0.01 公式；`PVECombatManager` 经装配段注入 `health_service`。（**世界 Boss 地板消费由 D AC4 验收；E2 只复跑正式 config 下 D AC9 的 HP 锚，不验地板**；E1 只保证 API 就绪与 D 可 import 的模块级 re-export。）
- [ ] AC3：全 HP 消费者组合复核通过；产品代码与测试无含混 `Player.hp`（旧 Boss 实现除外）；max_hp 下降/药品/跨玩法战斗后 current clamp 成立；`base_crit_rate` 已物化进 config 且 `build_fighter_from_player` 实际传参（静态搜索不再有死读取）；**怪物侧缺省时回退同一键**（改键后怪物 fighter 也变化）、per-enemy 有值时仍覆盖。
- [ ] AC4：data/ 之外 5 处裸 commit 全部按 `_txn_depth` 门控，静态审计为空；未新增叶子并发路径。
- [ ] AC5：以 R4 清单为准逐项完成（§Q4 / current-design-report §4.7、§4.12、§4.17、`:208`、`:11`、`:40`、§五 / project-architecture `:74`、`:16`、`:132` / api-overview `:108` / pve-enemy-design `:472-476`、`:477-482`、`:755`、`:758-760`、`:883-885` / rift 与 pve_combat_manager docstring+行内注释），并与版本清单（metadata / README / 修仙帮助）同步。
- [ ] AC6：定向 + 完整 pytest（含 `tests/test_rift_encounters.py` 旧 `== 1` 断言改写、`tests/test_adventure_settlement_state_machine.py` 的 `DEFEAT_HP_FLOOR_RATIO` 导入不因常量上收而断）与产品范围 ruff 通过。

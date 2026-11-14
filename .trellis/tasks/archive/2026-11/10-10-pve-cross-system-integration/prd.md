# PVE 跨系统收口：气血地板与消费者清零

## Goal

在 A/B/P/C/F 完成后，先修复 bd `-dfb` 的跨任务事务归属竞态并全局收口同类独立叶子写，再把 PVE 气血地板统一到 Health Domain（秘境兽、传承守护者及宗门领取入口），复核全部 HP 消费者并静态清零旧语义，完成暴击双侧接线、文档与版本收尾。旧 Boss 整删、内容 sync 与激活切流由 E2 承接。

## Dependencies

- A（气血）、B（目录）、P（基座）、C（普通 PVE 结算）、F（逃跑）均已归档。
- **不依赖 D**：世界 Boss 领域行为归 D；世界 Boss 的地板调用点切换与暴击形参补传由 E2 在激活检查点做。

## Requirements

### R1. PVE 气血地板收口（2026-10-12 甲案）

- 现状（2026-10-28 核对）：`challenge_rift_beast` 败场写死 `1`；`challenge_legacy_guardian` 为 `max(1, 引擎终值)`；两者都不带 1% 地板；宗门领取入口战败不落库、胜利在事务内被旧快照覆盖。
- 目标：败场/平局 `current_hp = max(引擎终值, ceil(1% × 动态 max_hp))`（至少 1），胜场按引擎终值不保底。
- **地板单源（唯一定义处）**：`DEFEAT_HP_FLOOR_RATIO` 与 `defeat_hp_floor(player)` 迁入 `core/health.py::HealthService`，`AdventureManager._compute_locked` 直接调用 HealthService 并保留模块级 re-export（既有测试从 `_adv_mod` 导入）；产品代码不得再有第二份 0.01 公式。D 的世界 Boss 写回引用本定义，不新增常量。
- 写回归一：秘境兽/传承守护者改由战斗层经 `HealthService.set_current_hp` 落库（宗门领取两条路径都生效）；`PVECombatManager` 增 `health_service` 注入（装配段）。
- PvP 不适用地板，只复核 clamp；静态判据：无 `else 1` / `current_hp = 1` 败场赋值（audit 脚本）。

### R2. 全消费者组合复核与暴击物化

- 复核 A 已交付的 base/current/max HP 消费者（创角/突破/装备/功法/丹药/商店/GM/PvP/历练/秘境/传承/显示/排行），补跨玩法 clamp 回归；产品代码与测试不残留含混 `Player.hp`（旧 Boss 实现归 E2 整删）。
- **暴击物化（唯一定义处）**，依据 `pve-enemy-design.md` Step 3 定案③「两个构建点统一从该键取值」：
  - `config/game_config.json` + `data/default_configs.py` 补 `combat.base_crit_rate = 0.15`（两边同补，保持默认表与 live config 深相等）。
  - 玩家侧：`build_fighter_from_player` 传 `crit_rate`（新增公开读取口，替掉 `_base_crit_rate` 死读取）。
  - 怪物侧：`build_enemy_fighter` 增可选 `base_crit_rate` 形参（默认 0.15，向后兼容）；`enemy.crit_rate > 0` 时按 /100 覆盖，否则回退该键。
  - **普通 PVE 的取值点**：`PVECombatManager._build_enemy_fighter` 读 `self.config_manager`（装配段已注入，无需新增注入），**不要用 `self.combat_engine`**（测试替身是 `ScriptedEngine`/`MagicMock`/`object.__new__` 空壳，直接取会打挂既有用例）；读不到（含替身）回 `0.15`；**值为 `None` 也回 `0.15`（不要用 `or`，否则配成 0 会失效）**。世界 Boss 不经过该类，由 D 自读同一键（见 D R4）。
  - 第一季 28 只名册与 4 只世界 Boss 的 CSV 均无 `crit_rate` 列（builder 默认 0）→ 全部走回退，默认 0.15 行为逐点不变；第二季要配 per-enemy 值：专项组模板立即可用，**固定名册需先扩 CSV 列 + builder（现硬编码 0）**。
  - **范围边界**：玩家目前没有任何暴击率加成来源（`Player`/`get_total_attributes` 不聚合 crit，武器/护甲/心法/丹药无该字段）；本轮只做物化与双侧接线，不新增加成通道。旧 Boss 即时路径（`boss_manager.py` 内直接构造 `FighterState`）不接，E2 整删。

### R3. 事务归属修复与叶子清零（2026-11-09 用户定案：dfb 并入 E1，全局同类收口）

- 先以真实 `DataBase` + SQLite 建立确定性 red：standalone 叶子首条 DML 后、提交前让另一任务进入 `db.transaction()`，修复前必须稳定出现隐式事务悬空 / `cannot start a transaction within a transaction`，修复后两边写入均完成且不报错。
- standalone 叶子与 CM 共用连接级事务所有权：**首条 DML 前**决定归属；同任务 join、跨任务等待，owner 退出时 commit/rollback 并释放。禁止仅靠事后 `_txn_depth == 0` 判断，也禁止在 `BEGIN` 前强制提交无 owner 的隐式事务。
- 覆盖 `data/data_manager.py`、`data/database_extended.py`、`data/pve_repository.py`、`core/health.py`、`handlers/combat_handlers.py` 及 managers 层现有同类 auto-commit / `own_txn + BEGIN IMMEDIATE` 写点；包括原定的 spirit_farm 种植、spirit_eye 生成/释放、bounty 过期扫描、dual_cultivation 发起请求。裸连接测试与 raw `BEGIN` 的既有兼容语义要有回归，不改公开返回结构。
- 静态审计从“5 处门控”升级为“生产叶子不存在写后才决定归属的门控 / 自有裸 BEGIN”，并保留 CM 内不提前提交、standalone 可持久化、异常/取消释放所有权证据。
- 文档/评审以函数名定位，不写死行号；完成后关闭 bd `-dfb` 与 `-qbo`。

### R4. 文档与版本收尾

- `pve-enemy-design.md`：§Q4 地板收口范围改写（四处已统一、删「过渡期并存」、改为 `else 1`/`max(1, 终值)` 的真实事实、枚举宗门宝库领取）；**坑#3 段落与玩家侧断链段落同批改写**为「玩家侧从 `combat.base_crit_rate` 读取并传参；怪物侧 per-enemy 优先、未配置回退该键」，并更正两段内已漂移的行号引用；`§Q4` busy 段落改为「挡开始新活动」；「全段触发另开任务」段落标已完成；附录 B 决策④改为 1% + 全风险段 ×0.3。
- `current-design-report.md`：§4.7 奖励与秘境、§4.12/§4.17 地板描述、`base_crit_rate` 行、§五 版本（v39）、**以及开头的「最新版本 v34」与目录树里的旧版本号**。
- `project-architecture.md`：`:74` 历练行「高/极高风险」改全风险段；数据库版本号改 v39（managers/models/定时任务/世界 Boss 行归 E2）。
- `api-overview.md`：`HealthService` 方法表补 `defeat_hp_floor`；`build_enemy_fighter` 行把「暴击」从纯透传改为「per-enemy 优先、缺省回退 `combat.base_crit_rate`」。
- `rift_manager.py` 与 `pve_combat_manager.py` 的 docstring/行内注释同步；`rift_manager` 的 3 处 `db.update_player` 保留（写回值一致，`set_current_hp` 已同步内存），注释改「非气血权威写点」，**不宣称「无竞态」**。
- AGENTS §7 清单：`metadata.yaml` version、`README.md` 更新日志与指令表、`/修仙帮助` 文本。

### R5. 质量门

- `uv run ruff format .` + **产品范围** ruff + `uv run python -m pytest tests/ -v`；机械判据跑 `python3 scripts/audit_pve_redesign.py --scope e1` 必须为 0；真实 webtest 仅用户要求时运行。

## Out of Scope

- 旧 Boss 整删/内容 sync/激活切流（E2）、世界 Boss 领域行为（D）、Step 7 经济、秘境生态与叙事创作、战斗引擎通用再平衡。

## Acceptance Criteria

- [x] AC1：秘境兽与传承守护者战败/平局残血 = `max(引擎终值, ceil(1% 动态 max_hp))`（至少 1），胜场不保底；PvP 不受影响；产品代码无 `else 1`/`current_hp = 1` 败场赋值。
- [x] AC2：地板单源——`HealthService` 提供地板 API，历练/秘境/守护者三类入口已消费、无第二份 0.01 公式；`PVECombatManager` 经装配段注入 `health_service`。世界 Boss 地板消费由 D AC4 验收；**若 D 落地时仍引用旧常量，E2 在激活检查点做调用切换与回归**，不重做地板验收标准。
- [x] AC3：全 HP 消费者复核通过；无含混 `Player.hp`；clamp 成立；`base_crit_rate` 已物化且玩家侧传参；**怪物侧缺省回退同一键**（改键后名册/专项组/秘境/守护者 fighter 同变）、per-enemy 有值仍覆盖；世界 Boss 侧由 D 经同一 mapper 接线。
- [x] AC4：dfb 确定性竞态回归由红转绿；standalone 叶子与 CM 在首条 DML 前完成归属协调，同任务 join、跨任务互斥，异常/取消不泄漏 owner；现有同类 auto-commit 与 `own_txn + BEGIN IMMEDIATE` 写点全部收口，audit 为空，bd `-dfb`/`-qbo` 可关闭。
- [x] AC5：以 R4 清单逐项完成并跑通版本清单（metadata / README / 修仙帮助）。
- [x] AC6：dfb 红绿证据 + 定向与完整 pytest（含 `test_rift_encounters` 旧 `== 1` 断言改写、`test_adventure_settlement_state_machine` 的 `DEFEAT_HP_FLOOR_RATIO` 导入不断、原并发双击回归）+ 产品范围 ruff + `audit_pve_redesign.py --scope e1` 为 0。

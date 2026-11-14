# Implementation Plan: PVE 跨系统收口（气血地板与消费者清零）

## Steps

1. 先跑 `tests/test_audit_pve_redesign.py`，确认审计器不会自命中、不会把无关 `else 1` 当气血；再按 design §4 写 dfb 确定性 red（真实 SQLite + 事件控制 interleaving），确认修复前失败原因是隐式事务/BEGIN 冲突，而不是测试夹具失败。
2. 实现连接级 `leaf_write` 所有权上下文并全局迁移同类叶子：先 `data/data_manager.py` / `data/database_extended.py` / `data/pve_repository.py` / `core/health.py`，再 handlers/managers；覆盖 auto-commit 与 `own_txn + BEGIN IMMEDIATE` 两种形态。每批跑事务定向测试，保留 standalone、same-task join、raw BEGIN、异常/取消证据；更新静态审计并确认 dfb red 转绿。
3. 生成静态清单与审计入口：HP 消费者、`Player.hp`/败场固定 1 残留、事务归属违规（以函数名锚定；机械判据统一跑 `python3 scripts/audit_pve_redesign.py --scope e1`）。
4. 地板 API 上收：`core/health.py` 增 `DEFEAT_HP_FLOOR_RATIO` + `HealthService.defeat_hp_floor`；`AdventureManager._compute_locked` 对败/平直接调用 HealthService，败场进 resolved_loss、平局保持 resolved_win/基础收益，胜场不保底；删除本地 helper/公式但**保留模块级 re-export**（`test_adventure_settlement_state_machine` 从 `_adv_mod` 导入）。审计以 AST 公式结构防止第二份实现，不只匹配常量名。
5. 战斗接线：`PVECombatManager` 增 `health_service` 注入（装配段）；`challenge_rift_beast`/`challenge_legacy_guardian` 按 `won ? 引擎终值 : max(引擎终值, 地板)` 经 `set_current_hp` 落库；补秘境/宗门两条入口用例与 PvP 不受地板用例；改写 `test_rift_encounters` 旧 `== 1` 断言；两函数 docstring 同步。
6. 暴击双侧接线：按 design §3 落地 `combat.base_crit_rate` 物化（live config + default_configs）、CombatEngine 构造边界 missing/None→0.15 且保留 0、`build_fighter_from_player` 传参、`build_enemy_fighter` 增 `base_crit_rate` 形参、`PVECombatManager._build_enemy_fighter` 经 `config_manager` 取值（禁用 `combat_engine`）。补断言：玩家 missing/None/0/自定义值均通过真实 resolve_combat，怪物 0/None/自定义值同口径，per-enemy 覆盖、第一季 28+4 默认值、全量 pytest 保持绿。
7. 消费者组合复核：跨玩法 clamp/restart 回归；静态证明无含混 `Player.hp`（旧 Boss 白名单，E2 删除）。
8. 文档与版本：按 PRD R4 清单同步（`pve-enemy-design` §Q4/坑#3/玩家侧断链/busy/全段触发/附录 B、`current-design-report` §4.7/§4.12/§4.17/base_crit_rate/§五/开头版本/目录树、`project-architecture` 历练行与版本、`api-overview` HealthService 与 `build_enemy_fighter` 行、rift/pve docstring 与行内注释），并更正经引用的漂移行号；数据库规范改为首写前归属契约；`metadata.yaml` version、`README.md` 日志、`/修仙帮助`。
9. 质量门与评审闭环：完整 pytest + 产品范围 ruff/format + `audit_pve_redesign.py --scope e1` 为 0；核对 bd `-dfb` / `-qbo` 关闭证据。DFB 与 E1 的 Standards/Spec 独立评审最终均 approve；验收不运行 webtest，真实平台回归保持用户手动发起边界。

## 回滚点

RP1：地板/暴击/消费者改动前备份 DB；任一步失败回到上一提交（无 schema 变更，git revert 即可）。dfb 以“确定性 red → 共享所有权 primitive → data 层迁移 → 外围叶子迁移”为独立回滚检查点；禁止用强制提交别人的隐式事务来消红。

## 完成证据（2026-11-14 最终实现）

### AC1–AC6

- AC1：秘境两引擎、守护者/宗门领取与历练均覆盖败/平/胜；真实 SQLite 历练平局断言 `player.current_hp == 10` 且 ledger `hp_after == 10`，保持 resolved_win/基础收益；胜场 7 点及 ledger 均不保底；PvP 0 值对照通过。
- AC2：地板唯一实现为 `core/health.py::HealthService.defeat_hp_floor`；AdventureManager 仅 re-export 常量并直接委托服务；`test_duplicate_defeat_floor_formula_is_detected` 以旧公式与改名等价公式验证 AST 防漏，HealthService 自命中对照通过。
- AC3：全 HP 消费者/clamp/restart 与静态 Player.hp 清零通过；玩家 missing/None/0/0.23 和怪物 0/None/0.27 配置回归通过，per-enemy 正数 /100 覆盖不变。
- AC4：dfb 真实 SQLite interleaving 从 `cannot start a transaction within a transaction` red 转 green；共享 leaf_write/CM 首写前归属、全局同类叶子、储物戒回滚与异常/取消证据通过；bd dfb/qbo 均 closed。
- AC5：R4 文档逐项同步，版本为 v3.21.6；backend spec 使用真实 `leaf_write_method`/`leaf_write` API；旧 Boss/E2 未触碰。
- AC6：最终 `uv run python -m pytest tests/ -v` = **1258 passed in 11.42s**；`uv run ruff check . --exclude .trellis` = All checks passed；`uv run ruff format --check . --exclude .trellis` = 172 files already formatted；`python3 scripts/audit_pve_redesign.py --scope e1` = clean (0 findings)；`git diff --check` 通过。

### 四轮独立评审结论

- DFB Standards：approve（0 findings）；DFB Spec：初审发现储物戒 foreign-owner 丢物品，修复后复审 approve。
- E1 Standards / Spec：初审均 request changes；平局持久化、玩家 None 暴击、第二份地板公式与文档漂移修正后，最终两轴均 approve，AC1–AC6 全部 pass。

### 验证边界

- 未运行 webtest 或真实 AstrBot 平台回归（项目约定由用户手动发起）；未执行多进程数据库锁压测。
- 以上最终测试与审计结果来自评审修正后的完整复验；Phase 3 只同步任务文档，不重复跑完整 pytest。

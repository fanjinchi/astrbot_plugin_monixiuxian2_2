# Implementation Plan: PVE 跨系统收口（气血地板与消费者清零）

## Steps

1. 生成静态清单与审计入口：HP 消费者、`Player.hp`/`else 1` 残留、`data/` 之外裸 `conn.commit()`（以函数名锚定；机械判据统一跑 `python3 scripts/audit_pve_redesign.py --scope e1`）。
2. 地板 API 上收：`core/health.py` 增 `DEFEAT_HP_FLOOR_RATIO` + `HealthService.defeat_hp_floor`；`AdventureManager._defeat_hp_floor` 改委托；删本地常量但**保留模块级 re-export**（`test_adventure_settlement_state_machine` 从 `_adv_mod` 导入）。
3. 战斗接线：`PVECombatManager` 增 `health_service` 注入（装配段）；`challenge_rift_beast`/`challenge_legacy_guardian` 按 `won ? 引擎终值 : max(引擎终值, 地板)` 经 `set_current_hp` 落库；补秘境/宗门两条入口用例与 PvP 不受地板用例；改写 `test_rift_encounters` 旧 `== 1` 断言；两函数 docstring 同步。
4. 暴击双侧接线：按 design §3 落地 `combat.base_crit_rate` 物化（live config + default_configs）、`build_fighter_from_player` 传参、`build_enemy_fighter` 增 `base_crit_rate` 形参、`PVECombatManager._build_enemy_fighter` 经 `config_manager` 取值（禁用 `combat_engine`）。补断言：改键后玩家与名册/专项组 fighter 同步变化、per-enemy 覆盖、第一季 28+4 默认值、全量 pytest 保持绿。
5. 事务叶子：门控 5 处裸 commit；补静态审计测试；注明 bd `-dfb` 依赖。
6. 消费者组合复核：跨玩法 clamp/restart 回归；静态证明无含混 `Player.hp`（旧 Boss 白名单，E2 删除）。
7. 文档与版本：按 PRD R4 清单同步（`pve-enemy-design` §Q4/坑#3/玩家侧断链/busy/全段触发/附录 B、`current-design-report` §4.7/§4.12/§4.17/base_crit_rate/§五/开头版本/目录树、`project-architecture` 历练行与版本、`api-overview` HealthService 与 `build_enemy_fighter` 行、rift/pve docstring 与行内注释），并更正经引用的漂移行号；`metadata.yaml` version、`README.md` 日志、`/修仙帮助`。
8. 质量门：完整 pytest + 产品范围 ruff + `audit_pve_redesign.py --scope e1` 为 0。

## 回滚点

RP1：地板/暴击/消费者改动前备份 DB；任一步失败回到上一提交（无 schema 变更，git revert 即可）。

## 完成证据

- 三入口地板数学与落库证据（秘境/宗门/PvP 对照）；
- 暴击双侧证据：config 双份写入、玩家传参、怪物回退与 per-enemy 覆盖、改键后双方 fighter 同变、`_base_crit_rate` 非死读取；
- 静态清零报告（`Player.hp` / `else 1` / 裸 commit）+ audit 脚本为 0；
- 文档 diff 与版本清单；ruff/pytest 摘要。

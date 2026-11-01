# Technical Design: PVE 跨系统收口（气血地板与消费者清零）

## 1. 边界与归属

- 本 child 不重建 Health/Catalog/Persistence/Adventure 模块；**不整删旧 Boss、不做内容 sync 与激活切流**（E2）。
- 两项收口职责：① PVE 气血地板统一到 Health Domain（秘境兽、传承守护者，含宗门领取入口）；② 玩家侧暴击物化（设计 Step 3 定案③：`base_crit_rate` 进 config + `build_fighter_from_player` 传参）。

## 2. 地板 API（单源）

```text
core/health.py
  DEFEAT_HP_FLOOR_RATIO = 0.01
  HealthService.defeat_hp_floor(player) -> int    # max(1, ceil(compute_max_hp(player) * ratio))
managers/adventure_manager.py
  _defeat_hp_floor -> 委托 health_service（standalone 无 Health Domain 时回退 base_hp）
managers/pve_combat_manager.py
  __init__(combat_mgr, enemy_mgr, config_manager=None, health_service=None)
  main.py::_wire_core_services 注入 health_service
  challenge_rift_beast / challenge_legacy_guardian:
      won  -> engine_final
      else -> max(engine_final, health_service.defeat_hp_floor(player))
      写回 -> await health_service.set_current_hp(player, value)
              （无 health_service 时回退旧内存赋值，standalone 测试夹具兼容）
```

- 战斗层直接落库：`rift_manager` 的 `update_player` 保留但不再是气血的权威写点（值一致、无竞态），其注释改口径；`sect_manager` 的失败分支（当前直接 return）与胜利分支（事务内重读旧快照）都不再吞掉战斗气血。
- PvP（`handlers/combat_handlers.py` 切磋/决斗）保持引擎终值 + clamp，不加地板。

暴击物化（Step 3 定案③）：`config/game_config.json` + `data/default_configs.py` 补 `combat.base_crit_rate=0.15`；`build_fighter_from_player` 传 `crit_rate=self._base_crit_rate`；怪物侧保持 `enemy_catalog.build_enemy_fighter` 的 per-enemy `crit_rate`（>0 覆盖、否则 0.15），**不读该 config 键**。

兼容：`AdventureManager` 删除本地 `DEFEAT_HP_FLOOR_RATIO` 后保留模块级 re-export（既有测试从 `_adv_mod` 导入）；`rift_manager` 的 `update_player` 保留但注释改为「非气血权威写点」。

## 3. 事务叶子

- 5 处按 `conn._txn_depth == 0` 才提交（与 `data/` 层 `_commit_if_standalone` 同一 idiom）：spirit_farm 种植、spirit_eye 生成/释放、bounty 过期扫描、dual_cultivation 发起请求。
- 行号不写进文档，由审计脚本生成；bd `-dfb` 未修前禁止新增并发叶子路径。

## 4. 验证矩阵

- 地板：历练（C 已交付）/ 秘境应邀 / 宗门领取 三入口；战败残血 ≥ `ceil(1% * 动态 max_hp)`、胜场不保底；max_hp 下降时 clamp。
- 消费者：创角/突破/装备/功法/丹药/商店/GM/PvP/历练/秘境/传承/显示；静态搜索 `Player.hp` 归零（旧 Boss 实现白名单，E2 删除）。
- 事务：5 处门控后静态审计为空；并发双击不提前提交。
- 暴击：改 config `base_crit_rate` → 玩家 fighter 生效；`_base_crit_rate` 不再死读取；怪物侧不受影响；`DEFEAT_HP_FLOOR_RATIO` 旧 import 不断。
- 质量门：完整 pytest + 产品范围 ruff。

## 5. 回滚

- 地板改动无 schema/config 变更，可单提交 revert；执行前备份 DB（RP1）。宗门/秘境写回变更用定向用例钉住，失败即回退该提交。

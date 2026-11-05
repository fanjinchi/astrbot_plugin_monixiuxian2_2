# Technical Design: PVE 跨系统收口（气血地板与消费者清零）

## 1. 边界与归属

- 本 child 不重建 Health/Catalog/Persistence/Adventure 模块；**不整删旧 Boss、不做内容 sync 与激活切流**（E2）。
- 范围边界：**旧 Boss 即时路径（`managers/boss_manager.py:440` 直接构造 `FighterState`）不接该键**（E2 整删），改键不影响它属预期；名册/专项组/秘境兽/守护者走 `build_enemy_fighter`，世界 Boss 由 D 接线。
- 两项收口职责：① PVE 气血地板统一到 Health Domain（秘境兽、传承守护者，含宗门领取入口）；② 暴击双侧接线（设计 Step 3 定案③：`base_crit_rate` 进 config；玩家侧 `build_fighter_from_player` 传参、怪物侧缺省回退同一键，per-enemy 有值仍覆盖）。

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

- 战斗层直接落库：`managers/rift_manager.py` 的 3 处 `await self.db.update_player(player)`（胜利/失败/传承分支）保留，但不再是气血的权威写点（写回值一致，`set_current_hp` 已同步内存对象；**不宣称无竞态**——整行回写仍受 AGENTS §3 约束），其注释改口径；`sect_manager` 的失败分支（当前直接 return）与胜利分支（事务内重读旧快照）都不再吞掉战斗气血。
- PvP（`handlers/combat_handlers.py` 切磋/决斗）保持引擎终值 + clamp，不加地板。

暴击物化（Step 3 定案③，**双侧接线**）：`config/game_config.json` + `data/default_configs.py` 补 `combat.base_crit_rate=0.15`；`build_fighter_from_player` 传 `crit_rate`（新增公开读取口，替掉 `_base_crit_rate` 死读取）；`build_enemy_fighter` 增可选 `base_crit_rate` 形参：`enemy.crit_rate > 0` 时按 /100 覆盖，否则取该键（默认 0.15）。**普通 PVE 的取值点**：`PVECombatManager._build_enemy_fighter` 里读 `self.config_manager`（世界 Boss 不经过该类，由 D 自读同一键，见 D R4）（`main.py:306-310` 已注入，无需新增注入），**不要用 `self.combat_engine`**——测试替身里它是 `ScriptedEngine`/`MagicMock`，甚至 `object.__new__(PVECombatManager)` 的空壳（`tests/test_block_armor_source.py:243-246`、`tests/test_pve_combat.py:137`、`tests/test_adventure_settlement_state_machine.py:372` 的 `ScriptedEngine`），按最自然的取法会打挂 31~37 个既有用例；写法：`rate = getattr(self, "config_manager", None)` → 有则 `cm.game_config.get("combat", {}).get("base_crit_rate", 0.15)`，无则 0.15，**值为 None 时也回落 0.15（不要用 `or`，否则把基础暴击配成 0 会失效）**；`base_crit_rate` 形参默认 0.15、签名向后兼容。
第一季 28 只与 4 只世界 Boss 的 CSV 均无 `crit_rate` 列 → 全部走回退，默认 0.15 时行为逐点不变；**世界 Boss 的 Fighter 由 D 用实例面板经 `build_enemy_fighter` 构建并带该参数（见 D R4/design/implement）；若 D 自建 `FighterState`，世界 Boss 侧不生效，必须同批接线**。第二季配 per-enemy 值：专项组模板立即可用；**固定名册需先扩 CSV 列 + `core/enemy_schema.py:393-394` 的 builder（现在硬编码 `"crit_rate": 0`）**，只加 CSV 列会被 builder 忽略。

兼容：`AdventureManager` 删除本地 `DEFEAT_HP_FLOOR_RATIO` 后保留模块级 re-export（既有测试从 `_adv_mod` 导入）；`managers/rift_manager.py` 的 3 处 `db.update_player(player)` 保留，注释改为「非气血权威写点」。

## 3. 事务叶子

- 5 处按 `conn._txn_depth == 0` 才提交（与 `data/` 层 `_commit_if_standalone` 同一 idiom）：spirit_farm 种植、spirit_eye 生成/释放、bounty 过期扫描、dual_cultivation 发起请求。
- 行号不写进文档，由审计脚本生成；bd `-dfb` 未修前禁止新增并发叶子路径。

## 4. 验证矩阵

- 地板：历练（C 已交付）/ 秘境应邀 / 宗门领取 三入口；战败残血 ≥ `ceil(1% * 动态 max_hp)`、胜场不保底；max_hp 下降时 clamp。
- 消费者：创角/突破/装备/功法/丹药/商店/GM/PvP/历练/秘境/传承/显示；静态搜索 `Player.hp` 归零（旧 Boss 实现白名单，E2 删除）。
- 事务：5 处门控后静态审计为空；并发双击不提前提交。
- 暴击：改 config `base_crit_rate` → 玩家 fighter **与怪物 fighter 同时生效**（名册/世界 Boss 无 per-enemy 值时走回退）；per-enemy 有值时仍覆盖；`_base_crit_rate` 不再死读取；第一季 28+4 默认仍为 0.15；`DEFEAT_HP_FLOOR_RATIO` 旧 import 不断。
- 质量门：完整 pytest + 产品范围 ruff。

## 5. 回滚

- 地板改动无 schema/config 变更，可单提交 revert；执行前备份 DB（RP1）。宗门/秘境写回变更用定向用例钉住，失败即回退该提交。

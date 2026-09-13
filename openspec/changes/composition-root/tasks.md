# Tasks — composition-root

## 0. 前置检查

- [ ] 0.1 重新锚定行号：`add-transaction-unit-of-work`（动 `core/breakthrough_manager.py`）、`busy-state-owner`（动 handler 守卫段）、`unify-combat-power-formula`（同改 `player_handler.py`）的在飞状态逐一核对；**与 `unify-combat-power-formula` 串行实施**（同文件，本 change 动构造器 + :179,:388 两处设备获取，彼动 :187-194 战力求和，区域不重叠但避免同 PR 互相 rebase）
- [ ] 0.2 全仓构造点基线 grep：`EquipmentManager(` / `PillManager(` / `CultivationManager(` / `StorageRingManager(` / `ShopManager(` 的每一处（运行时代码）与本 tasks 清单一致；测试目录的直构造点单独登记（跟随签名用，不删除）

## 1. 装配段（main.py）

- [ ] 1.1 main.py `__init__` 新增 `_wire_core_services()` 装配段（或内联等价的显式装配块，遵循 D1），两阶段装配：**阶段一 service 层**按依赖序建 `storage_ring_mgr` → `equipment_mgr(db, cfg, storage_ring_mgr)`（完整三参）→ `pill_mgr` → `cultivation_mgr(config, cfg_mgr, skill_manager)` → `shop_mgr(config, cfg_mgr)`；**阶段二**把 impart/pve/boss 等顺序靠后的 manager 建完后，统一建 handler 层；段内注释声明顺序约束
- [ ] 1.2 删除事后属性回填（构造期注入替代）：main.py:271（`player_handler.impart_mgr`——player_handler 构造挪到 impart_mgr 之后）、:278-279（`sect_mgr.impart_mgr/pve_combat_mgr`——`SectManager` 构造签名补两可选参数，构造点挪到二者之后）、:308（`rift_mgr.impart_mgr`）、:318（`adventure_mgr.impart_mgr`）、:350（`sect_handlers.ranking_handlers`——`SectHandlers` 签名补参数）；**核对 main.py:238 sect_mgr 提前构造的注释链**（player_handler 弃道重修依赖）被两阶段装配完整吸收，删除「init 顺序在其后，此处注入」类注释
- [ ] 1.3 main.py 现有 `self.equipment_mgr`（:235-237，已是完整三参）等单例保留，改由装配段统一返回/赋值，消除「main.py 单例 + handler 自建」双轨

## 2. 消费方改造（删 per-site 重建）

- [ ] 2.1 `handlers/player_handler.py`：构造器（:45-48）改收注入的 `cultivation_manager`/`pill_manager`/`equipment_manager`（签名补参数，main.py 传入）；删 :179-184 与 :388-393 的 per-request 局部导入 + 两参构造，改用 `self.equipment_manager`；**核对这两条路径因此获得储物戒回落能力**（验证任务 4.1 显式断言）
- [ ] 2.2 `handlers/equipment_handler.py:31-35`、`handlers/shop_handler.py:41-45`（含 `ShopManager`，:40）：改收注入的 `storage_ring_manager`/`equipment_manager`/`pill_manager`/`shop_manager`；构造内自建全删
- [ ] 2.3 `handlers/breakthrough_handler.py:32-35`、`handlers/pill_handler.py:24`、`handlers/storage_ring_handler.py:58`：改收注入；`BreakthroughHandler` 同步把 `storage_ring_manager`/`pill_manager` 传入 `BreakthroughManager` 新必填参数
- [ ] 2.4 `core/breakthrough_manager.py`：删 :39-42 的 `or StorageRingManager(...)`/`or PillManager(...)` 回退（D2，签名改必填）；:423-425 死亡分支的局部导入 + 临时构造改 `self.pill_manager.handle_resurrection(player)`（接线等价替换）
- [ ] 2.5 `managers/ranking_manager.py:53-63`：构造签名补 `equipment_manager` 注入参数；删 :60-63 懒导入（改模块顶 `from ..core import EquipmentManager` 或经 `__init__` 链导入）；调用点 main.py:309 传入 `self.equipment_mgr`
- [ ] 2.6 `managers/dual_cultivation_manager.py:35`：删自建 `CultivationManager(config, config_manager, None)`，改收注入（注意 `player_handler` 传的实例带 `skill_manager`，能力超集，行为不变）；main.py:370 传入装配段实例
- [ ] 2.7 收尾 grep：运行时代码中 `EquipmentManager(` / `PillManager(` / `CultivationManager(` / `StorageRingManager(` / `ShopManager(` 仅出现在装配段与测试；`.impart_mgr = ` / `.pve_combat_mgr = ` / `.ranking_handlers = ` 属性回填零命中

## 3. 测试与文档

- [ ] 3.1 测试跟随构造签名（机械性，fake 直填构造参数）：`tests/test_transaction_atomicity.py:123-124`、`tests/test_sect_manager.py:513,535` 等直接实例化 handler 的点全量过一遍（以 0.2 登记的清单为准）；**不强制回改** `handler.storage_ring_manager = ...` 事后塞桩风格（D6，收益顺带、非本 change 义务）
- [ ] 3.2 `AGENTS.md` §13 新增系统接入模板补一条：core 服务一律从 `_wire_core_services()` 装配段注入，禁止在 handler/manager 内自构造；§3 数据库段或架构速览处可加装配段一句话指针
- [ ] 3.3 `design_docs/api-overview.md` 的 main.py 初始化链路描述若枚举了「handler 自建 manager」先例，改指装配段；`design_docs/project-architecture.md` 分层图接线说明核对
- [ ] 3.4 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过

## 4. 验证与收尾

- [ ] 4.1 假 seam 修复显式验证：`player_handler` 换装路径（`handle_player_info` 之外的装备指令经 EquipmentHandler 已有回落；本 change 重点核对 `player_handler` 两条原两参路径的装备读取不回归）+ 全装备流程快照：穿戴替换旧装备时旧装备入戒并输出回落消息，无静默丢弃
- [ ] 4.2 初始化回归：插件重载（webtest `POST /api/ops/plugin-reload` 或 Dashboard 重载）无异常；定时任务（boss/loan/spirit_eye/bounty）照常注册
- [ ] 4.3 functional_tests 冒烟：装备/丹药/商店/排行域用例各至少一条通过（接线改动面所在域）
- [ ] 4.4 按 AGENTS.md §7 版本 checklist 评估（纯工程重构无玩法变化，通常无需升版本号）；`openspec validate --change composition-root` 通过；本地 conventional commit（不 push）

# composition-root

## Why

无状态 core manager（`EquipmentManager`/`PillManager`/`CultivationManager`/`StorageRingManager`/`ShopManager`，构造后仅持有 `db`/`config_manager`/可选协作者，无可变运行态）在 ~15 处被随手重建，且存在**两种互斥的接线风格**：main.py 建单例 + 事后属性回填（`main.py:271` `player_handler.impart_mgr = ...`、:278-279 `sect_mgr.impart_mgr/pve_combat_mgr = ...`、:308/:318/:350 同类），对照各 handler/manager 内部自建（`handlers/player_handler.py:45-48,179,388-390`、`equipment_handler.py:31-35`、`shop_handler.py:41-45`、`breakthrough_handler.py:35`、`pill_handler.py:24`、`storage_ring_handler.py:58`、`managers/ranking_manager.py:60-63` 懒导入 + 注释自认、`core/breakthrough_manager.py:39-42` 回退自建、:423-425 方法中途局部导入、`managers/dual_cultivation_manager.py:35`）。后果：`EquipmentManager(db, cfg)` 与 `(db, cfg, ring_mgr)` 的**假 seam**——第三参决定 `_store_old_equipment` 的储物戒回落（`core/equipment_manager.py:352-355`），而 `player_handler.py:179,390` 建的实例恰好缺它，行为差异无声；对象图知识散落各 `__init__`，唯一发现方式是通读每个构造点；`ranking_manager.py:60` 的懒导入 workaround 是图无序的直接症状。

## What Changes

- main.py `__init__` 建立**唯一装配段**（`_wire_core_services()`）：一次性构建 core 服务图——`storage_ring_mgr` → `equipment_mgr(db, cfg, storage_ring_mgr)`（完整三参，假 seam 消失）→ `pill_mgr` → `cultivation_mgr` → `shop_mgr`，并以构造参数注入全部 handler/manager。
- 删除事后属性回填：main.py:271、:278-279、:308、:318、:350（`impart_mgr`/`pve_combat_mgr`/`ranking_handlers` 改为构造期注入；`sect_mgr`/`rift_mgr`/`adventure_mgr` 构造签名补可选协作者参数）。
- 删除 per-site 重建（含 per-request 局部导入 `player_handler.py:179,388-390`、方法中途导入 `core/breakthrough_manager.py:423-425`）：`player_handler`(:45-48)、`equipment_handler`(:31-35)、`shop_handler`(:41-45)、`breakthrough_handler`(:35)、`pill_handler`(:24)、`storage_ring_handler`(:58)、`ranking_manager`(:60-63，懒导入一并删除，改模块顶导入)、`dual_cultivation_manager`(:35)。
- 构造器收紧：`BreakthroughManager` 的 `storage_ring_manager or StorageRingManager(...)` / `pill_manager or PillManager(...)` 自建回退（`core/breakthrough_manager.py:39-42`）删除，改必填注入——「缺协作者时悄悄降级」是假 seam 的根源。
- **协调（先合约束）**：本 change 先行落地，建立装配段与注入惯例；`busy-state-owner` 的 `BusyState(db)` 接线（其 tasks 1.1b）由本装配段承接——两个 change 的 Impact 已互相引用（已回写 busy-state-owner 的 proposal/tasks）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 — 纯工程重构：无行为契约需求条目定义「manager 如何被构造/接线」，specs/ 全目录无相关 Requirement。故 `.openspec.yaml` 设 `skip_specs: true`。）

## Impact

- **代码**：`main.py`（新增 `_wire_core_services()` 装配段、~5 处回填删除、构造调用更新）；`handlers/`（player/equipment/shop/breakthrough/pill/storage_ring handler 构造签名 + 内部引用改注入字段）；`managers/`（ranking、dual_cultivation 构造签名；sect/rift/adventure 增构造期协作者参数）；`core/breakthrough_manager.py`（回退删除 + :423-425 用 `self.pill_manager`）。
- **测试**：直接实例化 handler 并自塞 manager 的测试需跟随构造签名（`tests/test_transaction_atomicity.py:123-124`、`tests/test_sect_manager.py:513,535` 等）；注入式构造对测试更友好（fake 直接进构造参数），预期改动为机械性。
- **协调依赖**：**应先于 `busy-state-owner` 合入**——装配段是 BusyState 注入的落点（busy-state-owner tasks 1.1b 已回写引用本 change）；与 `unify-combat-power-formula`（同改 `player_handler.py`，区域不重叠：本 change 动构造器与 :179,:388 两处设备获取，彼动 :187-194 战力求和）建议串行实施；`add-transaction-unit-of-work` 合入会移动 `core/breakthrough_manager.py` 行号，实施前重新锚定。
- **无**数据库迁移、无配置变更、无用户可见行为变化；删除的唯一可观察差异是 `player_handler` 两条路径获得储物戒回落能力（`equipment_manager` 第三参生效），属修复假 seam 的既意外又正确的副作用，须在验证任务中显式确认。
- **并发变更重叠**：`decouple-handler-to-handler-calls` 同样删除 `main.py:349-350` 的 `sect_handlers.ranking_handlers` 回填（改为 `SectHandlers` 构造收 `rank_mgr`）——与本 change 目标态一致（构造期注入），两者须协调先后：后合入者按先合入者的 `SectHandlers` 签名落地，避免同一回填被两种方案各改一次。

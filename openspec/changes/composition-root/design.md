# Design — composition-root

## Context

插件的对象图今天由两种风格拼成：main.py `__init__`（`main.py:222-389`）对**有状态**组件已是单例装配（`SkillManager`、`EncounterStore`、`CombatManager`、`GMManager` 等，正确）；但**无状态 core 服务**（EquipmentManager/PillManager/CultivationManager/StorageRingManager/ShopManager——构造后只持 `db`/`config_manager`/协作者，grep `self\.\w* = ` 无可变运行态）被第二类风格覆盖：每个消费方在自己的 `__init__` 甚至方法体内 `new` 一份。两类风格的接缝处用第三种风格糊上：事后属性回填（`main.py:271,278-279,308,318,350`）。

具体病灶（已逐点核实）：
- `EquipmentManager` 第三参 `storage_ring_manager` 缺省时 `_store_old_equipment`（`core/equipment_manager.py:352-355`）静默跳过回落——但生产中的两参实例（`player_handler.py:181,383`、`ranking_manager.py:63`）只服务 `get_equipped_items` 只读路径，不触回落；全部换装路径本就走 `equipment_handler`/`gm_manager` 的三参实例。**故本 change 行为完全不变**，假 seam 的危害是结构性的：构造完整与否成为静默的能力开关，读代码无法从调用点得知实例缺了协作者。
- `core/breakthrough_manager.py:39-42` `storage_ring_manager or StorageRingManager(...)` / `pill_manager or PillManager(...)` 回退自建，使「注入完整与否」成为行为开关。
- `core/breakthrough_manager.py:423-425` 在死亡分支内 `from .pill_manager import PillManager; PillManager(...)`——方法中途构造 + 局部导入。
- `managers/ranking_manager.py:60-63` 构造内懒导入 `EquipmentManager` 并自认「延迟导入，避免循环依赖」——循环依赖是无序装配的症状，不是必须忍受的常态。
- `managers/dual_cultivation_manager.py:35` 自建 `CultivationManager(config, config_manager, None)`，与 `player_handler.py:45-47`（传 `skill_manager`）得到能力不同的实例。

## Goals / Non-Goals

**Goals:**
- 单一装配段（main.py `_wire_core_services()`）一次构建无状态 core 服务图，构造参数注入全部消费方；对象图在**一个函数**内可读完全。
- 三种接线风格归一为构造注入；事后属性回填与 per-site 重建（含局部导入构造）全数删除。
- 假 seam 关闭：`EquipmentManager` 只有完整三参构造一种形态；`BreakthroughManager` 协作者必填。
- 有状态组件（`EncounterStore`、`CombatManager`/`CombatEngine`、`GMManager`、`bounty`/`shop` 种子态）的构造方式与协作关系不变——无新增注入参数、无回填、业务面零改动；但构造语句统一收编进装配段（tasks 1.1 ⑦-⑳）并按依赖序排列，可移动位置（如 sect_mgr 从 :238 挪后至 :269 之后），段内排序对它们同样适用——它们没有病灶，病灶只在接线风格。

**Non-Goals:**
- 不引入 DI 框架/服务定位器/独立容器模块（见 D1）。
- 不改任何 handler/manager 的业务逻辑与方法级行为（除 `breakthrough_manager.py:423-425` 改道 `self.pill_manager` 这一接线等价替换）。
- 不动 `tests/helpers.py` 的 `load_module` 机制；测试继续直接构造 manager（注入式构造对此天然友好）。
- 不重构 `ConfigManager`（AGENTS.md 既有加载器，非本 change 范围）。

## Decisions

**D1 · 落点：main.py `__init__` 内的 `_wire_core_services()` 装配段，不引入容器。**
组件规模 ~20 个、依赖深度 ≤3，手工装配段即足够且最透明（AstrBot 插件无独立启动框架，装配必须在 `Star.__init__` 内完成）。独立容器模块会把 30 行装配藏到第二文件，收益为负。装配段按依赖序排列并段内注释声明顺序约束（如 sect_mgr 先于 player_handler），替代现有「init 顺序在其后，此处注入」类回填注释。

**D2 · 假 seam 关闭方式：构造器必填注入，删除 `or XxxManager(...)` 回退；新协作者默认必填。**
`BreakthroughManager.__init__`（`core/breakthrough_manager.py:26-42`）的两个 `or` 回退删除，签名改必填；调用方（`handlers/breakthrough_handler.py:32-34`）从装配段取实例传入。回退形态让「协作者缺失」成为静默降级而非构造错误，正是 `player_handler` 换装无回落的病根。
**注入边界总则（2026-09-21 评审补）**：本 change 新增/收紧的构造参数**一律必填**，例外白名单只有三个——`SectManager`/`RiftManager`/`AdventureManager` 的新协作者参数保持可选 + None 默认，判据有二且必须同时成立：① 存在大批量测试直构造（~50 处 `SectManager(db, FakeConfigManager())` 等，必填即批量编译错）；② 新协作者不服务既有测试路径（测试不触发 impart/pve 调用面）。7 个 handler/manager 消费方（`PlayerHandler`/`EquipmentHandler`/`ShopHandler`/`PillHandler`/`StorageRingHandler`/`RankingManager`/`DualCultivationManager`）**全部必填**——它们的测试直构造点已登记（tasks 3.1），且 `ShopHandler`/`PillHandler`/`StorageRingHandler`/`RankingManager` 测试零直构造，必填零成本。反向论证：若做可选+None，装配段漏传时静默 None、运行期才炸 `AttributeError`——比旧假 seam 更隐蔽（旧假 seam 至少只读路径能工作），是 D3 诊断的假 seam 在 handler 层复发。

**D3 · seam 留在构造签名，不用服务定位器。**
拒绝 `getattr(self, 'equipment_manager', ...)`/全局注册表等模式：seam 应是可以静态阅读的参数列表。测试以 fake 直填构造参数即完成替身，无需 mock.patch。

**D4 · 回填改构造注入，构造签名按「必需/可选」分级。**
`sect_mgr`/`rift_mgr`/`adventure_mgr` 的 `impart_mgr`/`pve_combat_mgr` 依赖是真实需求（main.py:278-279,308,318 回填自证），但 impart/pve 在依赖序上靠后——解法不是保留回填，而是把这几个 manager 的**构造挪到 impart/pve 之后**（装配段内重排，无循环：`SectManager` 构造本身不触 impart；`main.py:238` 提前构造 sect_mgr 只因 player_handler 构造参数需要它——装配段内先建 sect_mgr 再建 impart 再回填构造参数的次序问题，用「先全部建完 service 层、再统一建 handler 层」的两阶段装配消除）。`player_handler.impart_mgr`（main.py:271）同理：player_handler 挪到 impart_mgr 之后构造。

**D5 · BusyState 接线协调：本 change 先行，busy-state-owner 落点既定。**
`busy-state-owner` 的 `BusyState(db)` 由本装配段构造并注入 handler/manager（其 tasks 1.1b 已回写指向本 change）。本 change 不预建 BusyState（类尚不存在），只确立「core 服务一律经 `_wire_core_services()` 构造注入」的惯例与落点；busy-state-owner 实施时把 `BusyState(db)` 追加进装配段即可，无需再定接线方式。

**D6 · 装配段的测试可见性：不加，测试维持直接构造。**
装配段属 main.py（Star 类）。注意：**并非所有测试都不加载 main.py**——`tests/test_feature_switches.py:100,133` 与 `tests/test_rift_encounter_commands.py:231,258` 会加载 main.py 并实例化 `XiuXianPlugin`（handlers/managers/core 子包整体 MagicMock 化），它们是 `__init__` 装配的**唯一 pytest 冒烟覆盖**，装配段改动必须保持这两个文件绿（装配段内不得引入对真实子包模块的依赖）。其余测试走 `tests/helpers.py` 按路径加载，不受影响。构造器注入后测试的替身路径不变——这恰是本次重构的测试收益：不再有人需要 `handler.storage_ring_manager = ...` 事后塞桩（`tests/test_transaction_atomicity.py:124-131` 的 `__new__`+挂载模式）才能换实现，但也无需为此回改存量测试（该模式登记为 bd 跟进项，见 tasks 4.5）。

## Risks / Trade-offs

- [行号漂移] → `add-transaction-unit-of-work`（已归档）未触碰 `core/breakthrough_manager.py`（原预警不实，行号仍准）、`unify-combat-power-formula`（已归档）已把 `player_handler.py:187-194` 战力求和落为 :187 单行调用——两者均非在飞；`busy-state-owner` 仍会移动 handler 守卫段（在途）——tasks 0.1 要求实施前全量重新锚定行号。
- [构造签名收紧导致外部直构造点（tests/脚本）批量编译错] → fail fast 改名，无静默面；受影响点已在 proposal Impact 列明（`test_transaction_atomicity.py:130-131`、`test_sect_manager.py:513,535` 等），tasks 逐文件跟随。
- [纯接线重排引入行为回归] → 本 change 全部构造替换均为等价实例替换，唯一「行为」面是 `player_handler`/`ranking_manager` 的 `get_equipped_items` 只读路径（注入前后同类同参，回落语义不介入）；验证任务 4.1 为纯不回归断言。另两条实施纪律：`SectManager`/`rift_mgr`/`adventure_mgr` 的新协作者参数**必须保持可选 + None 默认**（~50 处测试直构造 `SectManager(db, FakeConfigManager())`，必填即批量编译错）——按 D2 总则，这三个是**唯一**的例外白名单（双判据见 D2），其余消费方一律必填；`tests/test_breakthrough_manager.py` 覆盖突破成功发药路径（`core/breakthrough_manager.py:591/:612`，依赖注入的 ring/pill manager），回退删除后该文件必须保持绿。
- [装配段两阶段重排引入初始化顺序回归] → 重排仅移动构造语句、不改变任何任务/定时任务的初始化点（`initialize()` 不动）；段内注释声明顺序约束，review 核对 `main.py:238`（sect_mgr 提前）与 :270-279 的回填链被两阶段装配完整吸收。
- [有人在新 handler 里恢复 `XxxManager(...)` 自建] → AGENTS.md §13 新增系统接入模板补一条「core 服务一律从 `_wire_core_services()` 注入，禁止自构造」；review checklist 含构造点 grep。

## Migration Plan

无部署/迁移步骤：纯接线重构，随插件重载生效；无数据库与配置变更。回滚 = revert 单个 commit。

## Open Questions

无（方向已定：装配段落点、假 seam 关闭、两阶段装配、BusyState 协调均已收敛；唯一时序约束是应先于 `busy-state-owner` 合入）。

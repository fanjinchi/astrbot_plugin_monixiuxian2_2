## Why

当前 `level_config.json` 对 99 个等级逐一手写 `exp_needed`、`success_rate` 与 `base_*` 基础属性：升级属性已改为突破随机成长后 `base_*` 失去存在意义；经验曲线在元婴后封顶 600 亿、成功率压至 0.01%，靠"数字墙"卡进度（模拟显示 36 级后每级需上万年），前期却又秒升，节奏整体崩塌。同时突破失败扣累计总修为 10% 的惩罚在高等级会吞掉任何曲线设计（L99 期望时间膨胀 10 倍），双修按对方总修为 10% 结算属于乘性刷级漏洞。需要把境界配置与经验曲线公式化，并同步修正配套数值机制。

## What Changes

- **简化 level_config**：只保留大境界名称列表与曲线参数；境界由 `level_index // 10`、层由 `level_index % 10` 直接计算，保留「每境界第 10 级命名为下一境界初期」的现有惯例；配置中声明最高大境界限制（满级 99 级/地仙九阶）。
- **经验曲线公式化**：`exp_needed` 改由分段幂律公式生成（L≤10: `1800·L^1.5`；L≤50: 线性衔接；L≤99: `×(L/50)^1.7`，参数 config 可调），不再逐級手写。节奏目标：早期半天/级、中期 1~2 天/级、后期 3~7 天/级、满级约 300 天。
- **移除每级 `base_*` 字段**：玩家属性来源保持「初始属性 + 突破随机成长」；统一用中央 `get_level_name(level_index)` 替换各处 `level_data[i]["level_name"]` 直读。
- **突破失败惩罚**：由「累计总修为的 10%」改为「本级需求经验的 25%」（比例 config 可调）。
- **成功率按大境界配置**：练气 100% → 筑基 80% → 金丹 65% → 元婴 55% → 化神 50% → 炼虚 45% → 合体及以后 40% 地板；连败保底机制保留。
- **突破死亡率配套下调**：`BREAKTHROUGH_DEATH_PROBABILITY` 由 `[0.01, 0.1]` 降至 `[0.005, 0.03]`（避免高成功率时代仍有强挫败）。
- **双修定额化**：收益改为「K=2 小时闭关等效 × 境界系数 f(t)」，不再按对方累计总修为比例结算。
- **Boss/PvE 功能开关**：新增 `boss.enabled` 与 `pve.enabled` 两个开关（`game_config.json`），关闭期间停用 Boss 生成定时任务、Boss 相关指令与秘境等 PvE 战斗玩法（历练保留，不依赖 `base_*`）；Boss/PvE 模块待后续重做后再开启。
- **平衡建议文档**：`design_docs/level-exp-curve/balance-recommendations.md` 给出道具类固定收益的后续平衡原则（境界等效时长法、单道具 ≤5~20% E(L) 上限），本次不改道具数值。

## Capabilities

### New Capabilities

- `level-progression`: 境界名称配置与等级→境界/层映射（含「下一境界初期」命名惯例与最高大境界限制）、公式化经验曲线（分段幂律参数）、按大境界的突破成功率表、本级需求比例的失败惩罚、双修的定额×境界缩放收益、Boss/PvE 功能开关行为。

### Modified Capabilities

- `attribute-numerics`: 「属性来源：境界基础 + 随机成长」改为「初始属性 + 随机成长」——level_config 不再提供每级 `base_damage/base_agility/base_speed/base_hp`；「PvE 数值生成基准」的境界锚定点随 Boss/PvE 开关关闭而暂缓实施，待模块重做时落地。
- `combat-core`: 共用战斗引擎的 PvE 接入方（世界 Boss、秘境）增加运行时功能开关，关闭期间不开放对应玩法入口，引擎本身不变。

## Impact

- **配置**：`config/level_config.json`（结构重构）、`config/game_config.json`（新增曲线参数、成功率表、惩罚比例、双修参数、boss/pve 开关、死亡率区间）。
- **代码**：`config_manager.py`（境界数据加载与 `get_level_name` 中央函数、exp 公式计算）、`core/breakthrough_manager.py`（失败惩罚、成功率查表）、`core/storage_ring_manager.py`、`core/equipment_manager.py`、`core/shop_manager.py`、`core/pill_manager.py`、`core/gm_manager.py`（level_name 直读点收敛）、`managers/dual_cultivation_manager.py`（定额化）、`managers/boss_manager.py` 与 Boss/秘境相关 handlers、`main.py`（开关接入：定时任务与指令路由）。
- **数据库**：无 schema 变更；`player.experience` 语义不变，存量玩家无需迁移。
- **文档**：`design_docs/level-exp-curve/`（模拟脚本、结果、平衡建议）。
- **暂不处理**：修为丹/商店物品等固定收益数值重平衡（后续策划）、Boss/PvE 模块重做、保命道具设计。

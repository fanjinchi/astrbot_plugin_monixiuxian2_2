# Proposal: skill-engine-fit-and-content-sync

## Why

战斗技能引擎存在两个 P1 级契约断裂，导致功法系统在线上完全失效：config 全部 6 个功法的触发技因键名不匹配（config 用 `effect`、引擎只读 `effect_type`）静默不触发；两个大招（万剑归宗/开天辟地）因 config 缺 `trigger_rate` 且引擎默认 0.0 从不触发。测试直接注入引擎格式 dict、绕过 config 路径，因此全绿漏网。

同时，内容设计侧三套表格（`weapons.csv` / `heart_methods.csv` / `skills.csv`）已定稿却**没有入库管道**；升星系统无星级上限且加法膨胀（10 星御剑术期望 +294%）；大招若简单改必放又会退化为"开局第一击固定放"。本次把引擎契约、大招时机机制、升星机制、内容同步管道一次性修复到位，让设计内容**可入库、可测试、可配平**。

对应 bd issue：lvb(P1)、iup(P1)、711(P2)、plt(P2)、riw(P2)、arx(P2)、dhh(P2)。

## What Changes

- **BREAKING（config 契约）** 触发技效果键名统一为 `effect_type`：config/skills.json、设计 CSV、测试数据全部从 `effect` 迁移；转换脚本强制校验引擎键，引擎不加兼容兜底（A3 方案，消灭双轨制）。〔lvb〕
- 大招必放制 + 战况解锁门槛：归一化层为大招注入默认 `trigger_rate = 1.0`（配置不再写概率字段）；新增统一解锁门槛 `min_action_index`（行动数门槛）与 `trigger_hp_below`（自身 HP% 阈值），参数化支持斩杀型/逆袭型等时机风格，大招不再开局固定放。〔iup，C 方案〕
- 效果注册表重构：`_process_trigger_skills` 扁平 if/elif 链改为 `EFFECT_HANDLERS` 注册表（功法与武器挂载共用派发）；`FighterState` 新增 `battle_flags` 通用状态容器（为 v2 状态类效果预留）；未知 `effect_type` 记 warning 而非静默 pass。〔711〕
- 升星机制重做：上限 3 星（现状无上限）；加成从加法 `(star-1)×0.2` 改为乘法 `(1+b)^(star-1)`；rate 与 value 合并为单一系数（实验值 0.10，3 星 = +21%）；满星后重复参悟按比例折算修为补偿。〔plt〕
- CSV→config 转换脚本（merge 模式）：按 name 键控合并、status 过滤（draft/final）、`bonus_damage→damage` 键名映射、引擎键校验、写盘前跑 `validate_budget.py` 闸门。〔riw〕
- config→引擎契约测试：覆盖「config → 归一化 → loadout」真实路径，断言引擎可读键存在、大招带门槛后可触发；模拟战斗回归一律走生产代码路径。〔arx〕

> **范围调整（2026-08-06 m00291 用户拍板）**：修复后配平（dhh）**移出本 change**——功法尚未丰富、届时要重做池子并重新设定数值，现在配平是白做。本 change 交付后游戏处于「引擎已活、功法数值超模」的中间态，因未上线可接受。

## Capabilities

### New Capabilities

- `content-sync-pipeline`: 设计 CSV → config JSON 的同步管道：merge 语义、状态过滤、键名映射、引擎键契约校验、预算验算闸门。

### Modified Capabilities

- `skill-system`: 触发技效果键名契约统一为 `effect_type`；大招从「概率限次」改为「必放 + 战况解锁门槛 + 限次」；升星增加 3 星上限、乘法系数与满星修为补偿。
- `combat-core`: 触发技效果分发改为注册表契约（含未知效果告警要求）；大招结算增加解锁门槛判定环节。

## Impact

- **代码**：`managers/combat_manager.py`（注册表、大招门槛、battle_flags）、`core/skill_manager.py`（归一化默认 rate、升星乘法与单一系数）、`data/database_extended.py`（3 星上限 + 满星补偿）、`scripts/sync_content_to_config.py`（新增）、`tests/`（契约测试）
- **配置**：`config/skills.json`（键名统一 + 大招门槛字段 + 配平数值）、`config/weapons.json`（挂载技引擎键校验）、设计 CSV 三表（`effect`→`effect_type`、删大招概率列）
- **玩家可见**：功法触发技与大招首次真正生效（**数值为既有超模值，配平随功法池重做另案处理**，见范围调整）；升星 3 星封顶；满星补偿新提示文案
- **不涉及**：数据库 schema 变更（升星上限为逻辑层）；v2 needs_code 效果（tt3，依赖本 change 的注册表）；功法池数值重做与武器变体扩展（设计侧后续）

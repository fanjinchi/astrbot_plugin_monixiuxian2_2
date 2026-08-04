# Proposal: cleanup-legacy-fields-and-docs

## Why

战斗系统迁移到 CombatEngine 四主属性框架后，代码与配置中仍残留旧五维体系的碎片：`weapons.json` 全部 120 个词条同时携带遗留字段（`physical_damage`/`magic_damage`/`physical_defense`/`mental_power`）与新字段，三处装备解析代码保留五维回退路径且**当前实际生效**（如青铜剑 `damage` 实为遗留字段求和 15 而非配置语义）；`pve_combat_manager.py` 的两个"兼容旧接口"函数仅被测试引用，是死代码。同时 `Player.level_up_rate` 是从不写入、不参与计算却在玩家信息中显示"突破成功率+X%"的死字段（bug），两份 design_docs 报告仍在描述已被替换的旧机制，误导后续设计与调研。

## What Changes

- **遗留五维字段清理**（bd-gxo）：
  - `config/weapons.json`：将遗留字段解析结果固化进显式 `damage`/`armor_value` 字段（保证数值零变化），随后删除 `physical_damage`/`magic_damage`/`physical_defense`/`magic_defense`/`mental_power` 键。
  - 删除 `core/equipment_manager.py`、`managers/combat_manager.py`、`core/shop_manager.py` 中的五维回退映射代码（保留 `equip_effects` 法器映射，其仍是 items.json 法器的生效路径）。
  - 删除 `managers/pve_combat_manager.py` 中死代码函数 `calculate_equipment_atk_bonus`/`calculate_equipment_defense` 及其测试（生产代码零引用）。
  - **明确不做**：丹药 buff 键（`physical_damage_multiplier`、`physical_damage_gain`、`add_mental_power` 等）是独立的生效中效果键系统，改名无行为收益、波及面大，不在本次范围。
- **level_up_rate 死字段修复**（bd-nec）：将 `Player.level_up_rate` 接入突破成功率计算，作为永久加法加成源（与丹药、连败保底并列，结果钳制到 0–100%）；玩家信息仅在 >0 时显示该项。数据库列已存在，无需迁移。
- **过时设计文档修正**（bd-iae）：重写 `design_docs/current-design-report.md`，使其与 CombatEngine 四属性框架（damage/agility/speed/hp、Muxxu 公式、减法护甲、99 级境界）及新 Player 模型一致。
- **sim 文档历史标注**（bd-rau）：`design_docs/level-exp-curve/exp-curve-report.md` 中旧失败惩罚（10% 总修为）与旧双修漏洞的问题分析段落标注为"历史背景（v3.7.0 已修复）"，避免误读。
- 按插件版本 checklist 更新 `metadata.yaml` 版本与 README 更新日志。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `level-progression`：突破成功率新增永久加成源 `level_up_rate`（加法、钳制），并修正其在玩家信息中的展示语义。

## Impact

- **代码**：`core/equipment_manager.py`、`core/shop_manager.py`、`managers/combat_manager.py`、`managers/pve_combat_manager.py`、`handlers/player_handler.py`、突破成功率计算处（`core/cultivation_manager.py` 或所在模块）。
- **配置**：`config/weapons.json`（120 词条字段固化与清理）。
- **文档**：`design_docs/current-design-report.md`（重写）、`design_docs/level-exp-curve/exp-curve-report.md`（标注）、`README.md`、`metadata.yaml`。
- **测试**：`tests/test_pve_combat.py`（删除死代码测试）、装备解析相关测试需覆盖"固化后数值不变"、突破成功率测试需覆盖新加成源。
- **行为兼容性**：装备数值严格要求零变化（固化迁移）；突破成功率在 `level_up_rate=0`（全量现状）时零变化。
- **无数据库迁移**：`level_up_rate` 列已存在于 players 表。
- **bd 联动**：关闭 gxo、nec、iae、rau 四个 issue。

# 提案：重设计数值、战斗与技能系统

## Why

当前战斗是"纯数值对撞"：伤害仅由 `atk` 派生（`exp // 10`）、减伤为 `def/(def+100)`、会心固定 ×1.5，玩家的五维属性（物伤/法伤/物防/法防/精神力）、MP、灵修/体修路线差异在实际战斗公式中完全不起作用；功法只是被动装备，没有主动技能，MP 海量却无处消耗。数值体系缺少策略深度与成长反馈，需要一次系统性的数值、战斗与技能重设计（本提案先确立设计草案，再落地实施）。

## What Changes

- 重构战斗核心公式：引入物理/法术双伤害类型、对应防御/抗性、命中与暴击体系，使五维属性与灵修/体修路线在战斗中真正生效（**BREAKING**：现有战斗结算逻辑与战力公式全部替换）。
- 新增被动/触发技能系统：技能来源于功法、心法与武器装备，以常驻被动或概率触发（如攻击时、受击时、暴击时）的形式在战斗中自动生效，玩家通过配装组合构建战斗风格，为配装玩法带来策略深度与趣味。
- 重做属性数值框架：主属性向参考游戏靠拢（伤害/闪避/出手速度/生存分工），来源改为「境界基础 + 随机成长」，统一 Buff 分层叠加规则、战力评估公式与 PvP/PvE 结算入口。
- 境界体系重规划为十进制：每个大境界 = 初期 + 一阶~九阶，等级数字的十位编码大境界、个位编码小阶段（**BREAKING**：现有 36 境界 `level_config.json` 与 `level_index` 语义全部替换）。
- 功法获取随机化与领悟机制：功法拥有与领悟分离——可购买/掉落获得但只有领悟后才能使用；心法定义配套功法列表（各带领悟概率系数），突破成功/失败概率领悟、闭关按时长概率领悟，可设修习目标定向修习，构成随机成长循环。
- 同步重平衡 PvE（历练/秘境敌人、世界 Boss）数值生成，使其与新战斗模型匹配。
- 为技能与新属性提供静态配置（`config/*.json`）与数据库迁移（玩家已习得技能等持久化字段）。

## Capabilities

### New Capabilities

- `combat-core`：统一回合制战斗引擎的行为规约——回合流程、双伤害类型与减伤公式、命中/暴击/状态效果结算、胜负判定，覆盖切磋/决斗、传承 PK 与 PvE 共用入口。
- `skill-system`：被动/触发技能系统规约——技能作为功法/心法/武器的附带效果（常驻被动 + 概率触发两类），触发时机、概率与效果类型的配置规范，多装备技能间的叠加/互斥规则，战斗内自动结算与消息呈现。
- `attribute-numerics`：属性数值框架规约——十进制境界体系、主属性的境界基础值 + 随机成长规则、Buff 分层叠加规则、战力计算公式、PvE 敌人/Boss 数值生成基准。

### Modified Capabilities

（无——`openspec/specs/` 当前无既有能力规约）

## Impact

- **代码**：`managers/combat_manager.py`、`managers/pve_combat_manager.py`、`managers/enemy_manager.py`、`managers/boss_manager.py`、`managers/ranking_manager.py`、`managers/impart_pk_manager.py`、`handlers/battle_handler.py`（及 PvE 相关 handler）、`models.py`（属性计算）、新增 `core/skill_manager.py` / `managers/skill_manager.py`。
- **配置**：新增 `config/skills.json`（被动/触发技能词条库），调整 `config/game_config.json`、`config/enemies.json`、`config/boss_config.json`、`config/weapons.json` / `items.json`（功法、心法、武器词条化——携带被动与触发技能）。
- **数据库**：`data/migration.py` 新增迁移版本（玩家已习得技能、技能冷却等持久化字段）。
- **测试**：`tests/` 新增战斗引擎与技能系统的单元测试。
- **资料基线**：现状数值报告见 `design_docs/current-design-report.md`（公式速查见附录），重设计以其为对照基线。

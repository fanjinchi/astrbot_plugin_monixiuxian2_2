# equip-from-learned-skills-and-transfer — 装备以已领悟表为准 + 已学功法道具化转交

## Why

当前代码实现中，装备/激活功法已只以 `player_skills`（已领悟技能表）为唯一依据，
但 spec 的「功法拥有与领悟分离」仅写了"维护是否已领悟字段"，未钉死装备来源，
且 `handle_activate_technique` 的提示语仍引导玩家"将功法物品设为修习目标"，
与 items.json 中 10 件旧功法物品（名称与 skills.json 技能名不对齐）叠加，
造成"功法物品在储物戒里却无法设修习目标/装备"的困惑。
同时，已领悟的功法记录绑定在玩家上，**无法作为道具转交他人**——玩家已确认期望：
已学功法可生成秘籍物品交给其他人使用，且转交不影响自己的已领悟状态与装备能力。

## What Changes

- **BREAKING（契约明确化）**：装备/激活功法 MUST 仅以已领悟技能表（`player_skills`）
  为唯一依据；储物戒中的功法物品不参与装备判定（代码已如此，spec 补明确 + 修正提示语）。
- 新增**已学功法成册**：已领悟功法可生成同名「秘籍」物品（放入储物戒，生成条件/消耗
  config 可调），作为可转交载体。
- **转交语义=复制**：秘籍赠予/接收复用现有物品赠予流程；转交后源玩家的已领悟状态
  MUST 不受影响（仍可装备）；接收方获得未领悟的拥有凭据，可设为修习目标并领悟。
- **打通旧功法物品**：items.json 中 type="功法" 的 10 件旧物品（长春功残篇等）与
  skills.json 技能名对齐映射，使其真正成为"未领悟拥有凭据"；无法对齐的标注 legacy 废弃。
- 修习目标"已拥有"判定统一为：储物戒秘籍物品（对齐后）或已装备功法。

## Capabilities

### New Capabilities

- 无新 spec：所有行为变更归属 skill-system。

### Modified Capabilities

- `skill-system`：装备来源钉死为已领悟表（修改「功法拥有与领悟分离」）；
  新增「已学功法成册与转交」需求（秘籍生成、转交复制语义、接收方领悟链条）；
  修习目标"已拥有"判定与旧物品打通。

## Impact

- `core/skill_manager.py`：新增成册逻辑（生成秘籍物品、校验已领悟、消耗/限制）
- `handlers/technique_handler.py`：激活/修习目标提示语修正（装备=已领悟，不再引导功法物品）
- `handlers/storage_ring_handler.py` / `main.py`：注册「功法成册」指令；赠予流程支持秘籍
- `core/storage_ring_manager.py`：秘籍物品的存入/取出校验（如有特殊限制）
- `config/items.json`：10 件功法物品名称/描述对齐 skills.json（或标 legacy）
- `config/game_config.json`：新增成册配置（消耗灵石/冷却/是否可生成同名副本）
- `_conf_schema.json`：如新增动态配置则同步
- 数据库：无迁移（秘籍为储物戒物品，领悟状态仍在 player_skills）

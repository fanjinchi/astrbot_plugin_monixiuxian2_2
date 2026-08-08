# equip-from-learned-skills — 装备以已领悟表为准，储物戒秘籍仅用于领悟

## Why

当前代码中装备/激活功法已只以 `player_skills`（已领悟技能表）为唯一依据，但 spec 的
「功法拥有与领悟分离」未钉死装备来源，且 `handle_activate_technique` 提示语仍引导
"将功法物品设为修习目标"，与 items.json 中 10 件旧功法物品（名称与 skills.json 技能名
不对齐）叠加，造成"储物戒里有功法道具却无法设修习目标/装备"的困惑。
玩家确认的机制是单向的：**储物戒中的功法秘籍物品只能用于领悟（拥有凭据），
战斗装备的功法一律从已领悟技能表装备**；已领悟功法不会、也无需再转回道具。

## What Changes

- **契约明确化**：装备/激活功法 MUST 仅以已领悟技能表（`player_skills`）为唯一依据；
  储物戒功法秘籍物品 MUST NOT 参与装备判定，其唯一用途是作为未领悟拥有凭据（可设为
  修习目标 → 领悟）。代码已如此，改动为 spec 补明确 + 修正激活提示语。
- **秘籍转交走现有物品赠予**：储物戒中的功法秘籍可通过现有 `赠予/接收赠予/拒绝赠予`
  流程转交他人；接收方以秘籍为拥有凭据设修习目标并领悟。**不新增**"已学功法成册"机制。
- **打通旧功法物品**：items.json 中 type="功法" 的 10 件旧物品与 skills.json 技能名
  对齐映射，使其真正可用作领悟凭据；无法对齐的标注 legacy 废弃。
- 修习目标"已拥有"判定统一为：储物戒中存在的对齐秘籍物品，或该功法已装备（已装备即已领悟）。

## Capabilities

### New Capabilities

- 无新 spec：所有行为变更归属 skill-system。

### Modified Capabilities

- `skill-system`：「功法拥有与领悟分离」钉死装备来源=已领悟表、秘籍=仅领悟凭据
  （修改）；「修习目标」已拥有判定统一（修改）；新增秘籍转交 Scenario。

## Impact

- `handlers/technique_handler.py`：激活/修习目标提示语修正（装备=已领悟；修习=需秘籍）
- `config/items.json`：10 件功法物品名称/描述对齐 skills.json（或标 legacy）
- `core/skill_manager.py` / `core/storage_ring_manager.py`：如需按技能名校验秘籍（小改）
- 数据库：无迁移（领悟状态在 player_skills，秘籍为储物戒物品）

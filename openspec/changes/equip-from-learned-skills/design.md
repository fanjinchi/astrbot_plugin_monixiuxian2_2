# Design — equip-from-learned-skills

## 现状（2026-08-08 核查，代码事实）

- **装备来源已是已领悟表**：`handle_activate_technique`（handlers/technique_handler.py）
  只校验 `_is_skill_learned`（player_skills 表）+ 激活槽位（player.techniques，上限
  `max_technique_slots=4`）；`get_battle_loadout`（core/skill_manager.py:522）只装载
  激活槽位且逐个校验已学。储物戒不参与装备判定——**代码已符合新契约，改动集中在
  spec 明确化 + 提示语 + 旧物品打通**。
- **player_skills 表**（v25）：`user_id, skill_id, star_level, source, learned_at`；
  `database_extended.py` 提供 get_learned_skills / is_skill_learned / get_star_level /
  learn_or_star_up（新学 INSERT，重复升星，满星折算修为补偿）。
- **旧功法物品脱节**：items.json 4001-4010 共 10 件 `type="功法"`（长春功残篇、焚天诀上卷、
  他化自在大法、不动明王经、御风诀、龟息功、北冥神功、九阳神功、道经、吞天魔功），
  物品名与 skills.json 技能名（基础吐纳、铁布衫、剑气纵横…）不对齐 → 无法作为修习目标
  拥有凭据（`_find_skill_id_by_name` 按技能名匹配）。
- **修习目标拥有凭据**：`_get_owned_skill_ids`（technique_handler.py）= 储物戒物品名 ∪
  已装备 ∪ 武器/防具/心法，再映射到技能 id。
- **赠予流程已存在**：`赠予 <目标> <物品>` / `接收赠予` / `拒绝赠予`
  （main.py:977/983/989 → storage_ring_handler），对象为储物戒物品。

## 目标机制（单向）

```
储物戒功法秘籍（物品）──拥有凭据──> 设为修习目标 ──领悟判定──> player_skills（已领悟表）
                                                                    │
                                             装备/激活（唯一依据）←─┘
                                                                    │
                                                        战斗 loadout（触发技+大招）

秘籍物品可经赠予转交他人；已领悟状态独立于物品，转交不影响装备能力。
已领悟功法不会（也无需）转回道具——无成册机制。
```

## 改动清单

### 1. 提示语修正（唯一必需代码改动）

- `handle_activate_technique` 未领悟提示：删除"💡 可先将功法物品设为修习目标进行领悟"，
  改为"💡 需先拥有该功法秘籍并设为修习目标，或通过闭关/突破领悟"
- （可选）`handle_set_study_target` 未拥有提示补充："可通过商店/掉落/赠予获得秘籍"

### 2. items.json 旧功法物品打通

- 与 skills.json 技能名一致的（如 龟息功 ↔ 功法池）：保留为静态秘籍，名称对齐技能名后
  即成为有效拥有凭据；
- 无法对齐的（长春功残篇等虚构名）：方案 A 改名对齐到现有技能；方案 B 标
  `"legacy": true` 并从 `shop_weight` 移除（默认走方案 B，不破坏已有玩家物品，
  后续随功法池重做清理）。

### 3. 校验打通（小改）

- `_find_skill_id_by_name` 或 `_get_owned_skill_ids` 增加"物品名→技能名"回退映射
  （秘籍物品名即技能名时已天然匹配；如需支持别名，在 design_note/items 描述中维护映射表）

### 4. 文档同步

- `current-design-report.md` 技能系统段、`project-architecture.md` 子系统表：
  "装备=已领悟表唯一依据；储物戒秘籍=领悟凭据"表述

## 边界与决策

- 秘籍转交后源玩家已领悟状态不变（领悟状态独立于物品持有）
- 接收方星级从 0 星开始（星级记录在接收方 player_skills）
- 秘籍占用储物戒格位（现有物品规则）；无独立数据库迁移
- 不做：已学功法→道具、秘籍直接使用即领悟（必须走修习目标+领悟判定）

## 测试

- 激活：未领悟拒绝（提示修正）；已领悟成功
- 修习目标：储物戒秘籍（对齐后）可设；无凭据拒绝
- 转交后：接收方可设修习目标；源玩家（若已领悟）仍可装备且战斗 loadout 含该功法

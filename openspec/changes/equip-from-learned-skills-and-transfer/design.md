# Design — equip-from-learned-skills-and-transfer

## 现状（2026-08-08 核查，代码事实）

- **装备来源已是已领悟表**：`handle_activate_technique`（handlers/technique_handler.py）
  只校验 `_is_skill_learned`（player_skills 表）+ 激活槽位（player.techniques，上限
  `max_technique_slots=4`）；`get_battle_loadout`（core/skill_manager.py:522）只装载
  激活槽位且逐个校验已学。储物戒不参与装备判定——**代码已符合新契约，改动集中在
  spec 明确化 + 提示语 + 成册转交闭环**。
- **player_skills 表**（v25）：`user_id, skill_id, star_level, source, learned_at`；
  `database_extended.py` 提供 get_learned_skills / is_skill_learned / get_star_level /
  learn_or_star_up（新学 INSERT，重复升星，满星折算修为补偿）。
- **旧功法物品脱节**：items.json 4001-4010 共 10 件 `type="功法"`（长春功残篇、焚天诀上卷、
  他化自在大法、不动明王经、御风诀、龟息功、北冥神功、九阳神功、道经、吞天魔功），
  物品名与 skills.json 技能名（基础吐纳、铁布衫、剑气纵横…）不对齐 → 无法作为修习目标
  拥有凭据（`_find_skill_id_by_name` 按技能名匹配）。
- **修习目标拥有凭据**：`_get_owned_skill_ids` = 储物戒物品名 ∪ 已装备 ∪ 武器/防具/心法，
  再映射到技能 id。

## 目标流程

### 1. 装备（契约明确化，行为不变）

激活功法 → 查 player_skills（唯一依据）→ 写入激活槽位 → 战斗装载。
仅修正 `handle_activate_technique` 未领悟提示语：
"❌ 功法【X】尚未领悟，无法激活"（去掉"可先将功法物品设为修习目标"引导，
改为"💡 可将其设为修习目标（需拥有秘籍）或通过闭关/突破领悟"）。

### 2. 成册（新指令）

`功法成册 <功法名>`：
1. 按技能名解析 skill_id（`_find_skill_id_by_name`），失败 → "未找到功法"
2. 校验 `_is_skill_learned`，未领悟 → 拒绝（"需先领悟"）
3. 校验 config `skill_system.skill_tome`：`enabled`（默认 true）、
   `cost_lingshi`（默认 0，生成消耗灵石）、`cooldown_seconds`（默认 0，成册冷却）
4. 生成秘籍：物品名为**功法名**（与 skills.json name 一致），入储物戒
   （`storage_ring_mgr.store_item`；无同名物品占 1 格，已有同名 +1 计数）
5. 写审计/提示成功

秘籍物品是**运行时生成**，不入 items.json（物品名即技能名，校验走 skills.json）；
items.json 4001-4010 静态物品另作对齐（见 §4）。

### 3. 转交（复用现有赠予流程）

`赠予 <@目标> <秘籍名>` → 接收/拒绝 → 秘籍进对方储物戒。
**复制语义**：源玩家 player_skills 记录不变（仍可装备）；接收方获得未领悟拥有凭据。
秘籍可再次转赠（物品规则内）。

### 4. items.json 旧功法物品打通

- 与 skills.json 技能名一致的（如 龟息功 ↔ heart_methods/功法池）：保留为静态秘籍，
  名称对齐技能名后即成为有效拥有凭据；
- 无法对齐的（长春功残篇等虚构名）：方案 A 改名对齐到现有技能；方案 B 标
  `"legacy": true` 并从商店权重移除（后续随功法池重做清理）。
  默认走方案 B（不破坏旧数据），对齐项单独决策。

### 5. 配置（game_config.json `skill_system`）

```json
"skill_tome": { "enabled": true, "cost_lingshi": 0, "cooldown_seconds": 0 }
```

## 边界与决策

- 已激活/满星功法允许成册；接收方从 0 星开始领悟（星级随接收方 player_skills 独立记录）
- 秘籍占用储物戒格位（现有物品规则）；可被 GM 给予/清除（物品通道）
- 无独立数据库迁移（秘籍=储物戒物品；领悟状态仍在 player_skills）
- 「赠予」目标校验沿用现有白名单/离线校验

## 测试

- 成册：已领悟成功 / 未领悟拒绝 / 消耗灵石 / 冷却
- 转交后：源玩家仍可装备且战斗 loadout 含该功法；接收方可设修习目标
- 修习目标拥有凭据：储物戒秘籍（对齐后）可设；未拥有拒绝

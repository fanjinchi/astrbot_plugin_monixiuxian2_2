# 实施任务：数值、战斗与技能系统重设计

> 依据：`proposal.md`（Why/What）、`design.md`（D1-D7 决策）、`specs/`（行为规约）。
> 项目规范：迁移走 `data/migration.py` 版本化；测试用 `tests/helpers.py` 的 `load_module()`；提交前 `uv run ruff format . && uv run ruff check .`。

## 1. 数据层与配置重构

- [x] 1.1 数据库迁移（`data/migration.py` 新增版本 v22）：`players` 表按四主属性（damage/agility/speed/hp）重建，废弃旧五维、精神力/MP、atkpractice 等旧字段；新增已领悟功法字段 `learned_skills`（JSON）与修习目标字段 `study_target`；旧数据直接废弃不做映射。同步重建 `buff_info` 表（旧字段废弃）。
- [x] 1.2 十进制境界配置：重写 `config/level_config.json`（99 个灵修等级）与 `body_level_config.json`（99 个体修等级）。十位 = 大境界序号（0=练气/锻体, 1=筑基/铜皮...），个位 = 小阶段（0=初期, 1-9=一阶~九阶）；练气/锻体无初期，一阶从 level 1 开始。每个等级含四主属性基础值（base_damage/agility/speed/hp）与突破所需修为（exp_needed）、成功率（success_rate）。数值从旧 36 境界映射占位，保持 config 可调。
- [x] 1.3 装备词条化：`config/weapons.json` 增加 `weapon_coefficient_k`（武器系数 K，按类别区分大/小武器）、`base_damage`（基础伤害）、`armor_value`（护甲值）、`trigger_skills`（触发技结构，占位空列表）、`route_multiplier`（路线倍率）。新增 `config/skills.json`（功法定义：触发技+大招+路线倍率+领悟概率系数）与 `config/heart_methods.json`（心法定义：属性被动+配套功法列表）。
- [x] 1.4 `config/game_config.json` 新增 `skill_system` 战斗参数区：breakthrough_success_learn_rate=0.2、breakthrough_fail_learn_rate=0.1、cultivation_learn_rate=0.15（每满 2 小时一次）、universal_pool_rate=0.05、universal_pool_no_heart_rate=0.03、random_growth_step=5、max_technique_slots=3、battle_report_merge_count=10。新增 `pve` 区 difficulty_multiplier=1.0。combat 区新增 action_limit=200、dodge_cap=0.5。

## 2. 属性与模型层

- [x] 2.1 `models.py`：Player 重构为四主属性（damage/agility/speed/hp）+ armor_value（护甲）+ learned_skills（已领悟功法 JSON）+ study_target（修习目标）。Item 重构为四主属性 + weapon_coefficient_k + base_damage + armor_value + route_multiplier + trigger_skills + passive_bonus + skill_pool。重写 `get_total_attributes`：基础属性 + 装备按路线倍率叠加 + 心法被动加成 + 丹药倍率（废弃 exp 派生与旧五维）。
- [x] 2.2 `models_extended.py`：评估 UserStatus 是否需新增「修习中」状态——**不需要新增状态**（修习目标只是字段，无进行中状态），已确认。
- [x] 2.3 `managers/ranking_manager.py`：战力公式重写为 `damage + agility + speed + hp + armor_value//2`（废弃旧「物伤+法伤+物防+法防+精神力//10」公式）。

## 3. 技能系统（skill-system）

- [x] 3.1 新建 `core/skill_manager.py`：领悟随机池构建（心法配套池按系数加权 + 修习目标 + 通用池仅突破渠道）、三渠道领悟判定（突破成功/失败、闭关结算）
- [x] 3.2 功法升星：重复获得同名功法自动升星（提升触发概率/效果），不占用新槽位
- [x] 3.3 心法属性被动：装备/卸下即时生效与移除，接入总属性计算
- [x] 3.4 修习目标业务逻辑：设置/取消/校验（已拥有且未领悟才可设为目标）
- [x] 3.5 装备校验：未领悟功法禁止装备；功法槽位上限 3 本

## 4. 战斗引擎（combat-core）

- [x] 4.1 重构 `managers/combat_manager.py` 为统一战斗引擎：迅捷加权出手权、行动次数上限与平局、Muxxu 式伤害公式（武器系数 K、护甲减伤、下限 1）
- [x] 4.2 判定链实现：闪避（身法差，上限 50%）→ 格挡 → 暴击（×1.5）→ 触发技 → 大招（每场每功法限一次、多功法独立）→ 伤害结算
- [x] 4.3 战报生成器：叙事化判定记录 + 按用户配置的合并条数输出（默认 10 条，用户可调）
- [x] 4.4 切磋/决斗接入统一引擎；`managers/impart_pk_manager.py` 传承 PK 迁移至统一引擎（废弃旧 `atk - def//2` 公式）

## 5. PvE 数值重校准

- [x] 5.1 `managers/enemy_manager.py`：敌人按「对应境界属性基准区间 × 难度系数」生成四主属性（废弃 base_exp 派生 hp/atk/mp）
- [x] 5.2 `managers/boss_manager.py`：世界 Boss 数值按新框架重生成（含 8 档境界基准与防御词条）
- [x] 5.3 `managers/pve_combat_manager.py`：接入统一战斗引擎，胜负奖励规则保持不变

## 6. 成长流程接入

- [x] 6.1 `core/breakthrough_manager.py`：突破成功随机一项主属性 +N（仅成功发放）；成功 20% / 失败 10% 领悟判定接入 skill_manager
- [x] 6.2 `core/cultivation_manager.py`：闭关结算时按「每满 2 小时一次、每次 15%」判定领悟（需装备心法，仅配套池+修习目标）
- [x] 6.3 `handlers/`：新增「修习目标」设置/查看指令、「战报条数」设置指令；属性面板指令改为四主属性展示；相关指令注册进 `main.py` 并加 `@require_whitelist`

## 7. 测试与收尾

- [x] 7.1 战斗引擎单测：出手权分布、伤害公式边界（下限 1/护甲减伤）、判定链顺序、大招限次、行动上限平局
- [x] 7.2 技能系统单测：领悟池系数加权、通用池渠道隔离（闭关不触及）、无心法 3% 独立判定、修习目标入池、升星与槽位校验
- [x] 7.3 迁移脚本测试：含旧数据的库执行迁移后新 schema 正确、旧字段废弃
- [x] 7.4 质量门禁：`uv run ruff format . && uv run ruff check .` 全过；`uv run python -m pytest tests/ -v` 全绿
- [x] 7.5 版本 checklist：`metadata.yaml` 版本号、`README.md` 更新日志、`handlers/misc_handler.py` 修仙帮助文本同步更新

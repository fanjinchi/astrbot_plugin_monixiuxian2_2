# 实施任务：数值、战斗与技能系统重设计

> 依据：`proposal.md`（Why/What）、`design.md`（D1-D7 决策）、`specs/`（行为规约）。
> 项目规范：迁移走 `data/migration.py` 版本化；测试用 `tests/helpers.py` 的 `load_module()`；提交前 `uv run ruff format . && uv run ruff check .`。

## 1. 数据层与配置重构

- [ ] 1.1 数据库迁移（`data/migration.py` 新增版本）：`players` 表按四主属性（伤害/身法/迅捷/气血）重建，废弃旧五维、精神力/MP、atkpractice 等旧字段；新增已领悟功法字段（JSON）与修习目标字段；旧数据直接废弃不做映射（design D7 / attribute-numerics「旧数据废弃」）
- [ ] 1.2 十进制境界配置：重写 `config/level_config.json` 与 `body_level_config.json`（每大境界 = 初期+一阶~九阶，十位编码大境界；含各境界四主属性基础值；升级曲线数值暂沿用旧表占位，保持 config 可调）
- [ ] 1.3 装备词条化：`config/weapons.json` 增加武器系数 K、基础伤害、触发技词条；心法配置增加属性被动与配套功法列表（各功法带领悟概率系数）；新增功法定义配置（触发技+大招+路线倍率）与通用功法池配置
- [ ] 1.4 `config/game_config.json` 新增战斗参数区：领悟概率（0.20/0.10/0.15 与 2h 步长）、通用池概率（0.05/0.03）、行动上限 200、闪避上限 0.5、暴击倍率 1.5、战报合并默认 10 条、随机成长步长 N、PvE 难度系数

## 2. 属性与模型层

- [ ] 2.1 `models.py`：Player 重构为四主属性 + 护甲（装备派生）+ 已领悟功法/修习目标字段；重写 `get_total_attributes`（废弃 exp 派生与旧五维）
- [ ] 2.2 `models_extended.py`：评估 UserStatus 是否需新增「修习中」状态，如需则同步更新 `handlers/utils.py` 的 `BUSY_STATE_ALLOWED_COMMANDS`
- [ ] 2.3 `managers/ranking_manager.py`：战力公式按四主属性 + 装备/功法加权重写（废弃旧公式）

## 3. 技能系统（skill-system）

- [ ] 3.1 新建 `core/skill_manager.py`：领悟随机池构建（心法配套池按系数加权 + 修习目标 + 通用池仅突破渠道）、三渠道领悟判定（突破成功/失败、闭关结算）
- [ ] 3.2 功法升星：重复获得同名功法自动升星（提升触发概率/效果），不占用新槽位
- [ ] 3.3 心法属性被动：装备/卸下即时生效与移除，接入总属性计算
- [ ] 3.4 修习目标业务逻辑：设置/取消/校验（已拥有且未领悟才可设为目标）
- [ ] 3.5 装备校验：未领悟功法禁止装备；功法槽位上限 3 本

## 4. 战斗引擎（combat-core）

- [ ] 4.1 重构 `managers/combat_manager.py` 为统一战斗引擎：迅捷加权出手权、行动次数上限与平局、Muxxu 式伤害公式（武器系数 K、护甲减伤、下限 1）
- [ ] 4.2 判定链实现：闪避（身法差，上限 50%）→ 格挡 → 暴击（×1.5）→ 触发技 → 大招（每场每功法限一次、多功法独立）→ 伤害结算
- [ ] 4.3 战报生成器：叙事化判定记录 + 按用户配置的合并条数输出（默认 10 条，用户可调）
- [ ] 4.4 切磋/决斗接入统一引擎；`managers/impart_pk_manager.py` 传承 PK 迁移至统一引擎（废弃旧 `atk - def//2` 公式）

## 5. PvE 数值重校准

- [ ] 5.1 `managers/enemy_manager.py`：敌人按「对应境界属性基准区间 × 难度系数」生成四主属性（废弃 base_exp 派生 hp/atk/mp）
- [ ] 5.2 `managers/boss_manager.py`：世界 Boss 数值按新框架重生成（含 8 档境界基准与防御词条）
- [ ] 5.3 `managers/pve_combat_manager.py`：接入统一战斗引擎，胜负奖励规则保持不变

## 6. 成长流程接入

- [ ] 6.1 `core/breakthrough_manager.py`：突破成功随机一项主属性 +N（仅成功发放）；成功 20% / 失败 10% 领悟判定接入 skill_manager
- [ ] 6.2 `core/cultivation_manager.py`：闭关结算时按「每满 2 小时一次、每次 15%」判定领悟（需装备心法，仅配套池+修习目标）
- [ ] 6.3 `handlers/`：新增「修习目标」设置/查看指令、「战报条数」设置指令；属性面板指令改为四主属性展示；相关指令注册进 `main.py` 并加 `@require_whitelist`

## 7. 测试与收尾

- [ ] 7.1 战斗引擎单测：出手权分布、伤害公式边界（下限 1/护甲减伤）、判定链顺序、大招限次、行动上限平局
- [ ] 7.2 技能系统单测：领悟池系数加权、通用池渠道隔离（闭关不触及）、无心法 3% 独立判定、修习目标入池、升星与槽位校验
- [ ] 7.3 迁移脚本测试：含旧数据的库执行迁移后新 schema 正确、旧字段废弃
- [ ] 7.4 质量门禁：`uv run ruff format . && uv run ruff check .` 全过；`uv run python -m pytest tests/ -v` 全绿
- [ ] 7.5 版本 checklist：`metadata.yaml` 版本号、`README.md` 更新日志、`handlers/misc_handler.py` 修仙帮助文本同步更新

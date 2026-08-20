# AstrBot 修仙插件（astrbot_plugin_monixiuxian2_2）架构与数值报告

> **文档状态**：
> - 创建：**2026-07-29**（重设计起点，与 `redesign-combat-skills` 变更同批，commit 8fa47f7）
> - 最近更新：**2026-08-20**（`unify-sect-commands`：宗门功能收敛为「宗门」单入口子命令，宗门悬赏/商店/秘境可见性独立）
> - 定位：**数值细节基线（活文档，非归档）**——架构总览见 `project-architecture.md`，行为契约见
>   `openspec/specs/`；本文是数值/公式/数据库的权威基线，被 `project-architecture.md` §1/§3 引用。
> - 维护义务：内容必须与代码同步（插件根 `AGENTS.md` §14，影响玩法的修改须同步修正本文）；
>   若未来被新报告取代，移入 archive 并更新本标注。
>
> 生成方式：基于源码静态分析（含 `file:line` 引用），数据库结构以 `data/migration.py` 最新版本 **v30** 为准。
> 战斗与属性体系为 **CombatEngine 四主属性框架**（伤害/身法/迅捷/气血 + 护甲），规范见 `openspec/specs/`（attribute-numerics / combat-core / level-progression / skill-system）。

---

## 一、项目概览

- **类型**：AstrBot 插件（群聊文字修仙游戏），Python 异步，无独立构建系统
- **宿主**：运行于 `~/code/AstrBot/data/plugins/` 下，依赖 AstrBot 提供的 `Context`、`filter`、`Star` API
- **数据库**：SQLite（aiosqlite），文件为 `xiuxian_data_lite.db`，存放于 `data/plugin_data/astrbot_plugin_monixiuxian2/`
- **第三方依赖**：仅 `Pillow>=9.0.0`（图片生成）
- **静态配置**：22 个 JSON 文件（`config/`），由 `config_manager.py` 加载，修改后需重启生效
- **动态配置**：`_conf_schema.json` 暴露给 AstrBot WebUI（白名单、数值、灵根、数据库文件名）

---

## 二、代码架构

### 2.1 目录结构与分层

```
main.py                # 插件入口（Star 子类）：~103 个指令注册、依赖装配、定时任务
├── handlers/          # 指令处理层（26 个文件，按系统分类）
│   └── utils.py       # @player_required 装饰器、忙碌白名单、贷款逾期检查
├── managers/          # 业务逻辑层（17 个管理器：战斗/宗门/Boss/银行/悬赏/秘境…）
├── core/              # 通用系统层（9 个模块：修炼/突破/丹药/装备/商店/储物戒/GM）
├── data/              # 数据层
│   ├── data_manager.py        # 连接管理 + 玩家 CRUD（ensure_connection 自动重连）
│   ├── database_extended.py   # 宗门/Boss/秘境/银行/悬赏等扩展 CRUD
│   ├── migration.py           # 版本化迁移（当前 LATEST_DB_VERSION = 30）
│   └── default_configs.py     # 内置默认配置（config/*.json 缺失时创建）
├── models.py          # Player、Item 数据模型（dataclass）
├── models_extended.py # Sect/BuffInfo/Boss/Rift/ImpartInfo/UserCd + UserStatus 枚举
├── config/            # 22 个静态 JSON 配置
├── utils/             # 图片生成、配置加载辅助
└── tests/             # pytest（用 tests/helpers.py 的 load_module 绕过相对导入）
```

> 目录文件计数不含 `__init__.py`。

**调用链**：用户指令 → `main.py` 的 `@filter.command` 方法 → `handlers/xxx_handler.py` → `managers/` 或 `core/` 管理器 → `data/` 数据库封装。

### 2.2 关键机制

1. **命令注册**：`main.py` 中定义 `CMD_XXX` 中文常量 + `@filter.command(CMD_XXX)`，内层 `@require_whitelist`。全部为纯中文无空格指令（92 个，覆盖：修仙/闭关/突破/丹药/装备/商店/储物戒/宗门/Boss/排行/决斗切磋/秘境/历练/炼丹/传承/银行/悬赏/洞天/灵田/双修/灵眼/GM 等）。宗门功能例外：全部收敛为「宗门」单顶层指令 + 子命令分发（sect_handlers.handle_sect_entry），原 18 个宗门顶层指令已删除。
2. **状态双层维护**（易踩坑）：
   - `player.state`（字符串："空闲"/"修炼中"/"历练中"…）
   - `user_cd` 表 `type` 字段（`UserStatus` 枚举：0 空闲 / 1 闭关中 / 2 历练中 / 3 探索秘境中 / 4 宗门任务中）
   - `@player_required`（handlers/utils.py）同时检查两者；忙碌时仅放行 `BUSY_STATE_ALLOWED_COMMANDS`（查看类指令）。
3. **贷款逾期即删号**：每次指令经过 `player_required` 时检查（handlers/utils.py），另有定时任务兜底。
4. **事务保护**：并发敏感操作用 `BEGIN IMMEDIATE` + commit/rollback；定时任务先 `ensure_connection()`。
5. **定时任务**（main.py `initialize()`，均含指数退避重试）：
   - `_schedule_boss_spawn` Boss 自动生成（受 `boss.enabled` 开关控制）
   - `_schedule_loan_check` 贷款逾期检查
   - `_schedule_spirit_eye_spawn` 灵眼生成（间隔 7200s）
   - `_schedule_bounty_check` 悬赏过期检查

### 2.3 配置文件清单（config/）

| 文件 | 内容 |
|---|---|
| `level_config.json` / `body_level_config.json` | 灵修/体修境界配置（新结构：`realms` 十大境界名称、`max_level=99`、`exp_curve` 公式参数、按大境界 `success_rates` 表、`failure_penalty_rate`），**不再含逐級 exp_needed/success_rate/base_\* 字段** |
| `items.json` / `weapons.json` | 防具/法器/心法/功法、武器（品级：凡品→混元先天）。装备词条为四主属性框架字段：`damage/agility/speed/hp/armor_value/base_damage/weapon_coefficient_k/route_multiplier/trigger_skills/passive_bonus/skill_pool`；旧五维词条已废弃移除 |
| `heart_methods.json` / `skills.json` | 心法（属性被动 + 配套功法池）与功法/触发技能定义 |
| `pills.json` / `exp_pills.json` / `utility_pills.json` | 丹药（破境丹、修为丹、功能丹） |
| `alchemy_config.json` / `alchemy_recipes.json` | 炼丹配方与成功率 |
| `enemies.json` | PvE 敌人模板（分组的等级区间与属性倍率） |
| `boss_config.json` / `rift_config.json` / `sect_config.json` | Boss / 秘境 / 宗门配置（sect_config：positions 含 `promotion` 晋升门槛与 `benefits` 职阶福利、`scale_ratio` 捐献折算、`buildings` 洞天/丹房等级与消耗；rift_config 条目可带 `sect_id`+`access=sect_member` 做宗门专属秘境） |
| `sect_factions.json` / `sect_tasks.json` | 默认（系统）宗门定义（join_level_range/长老/建筑物/treasures/heart_methods/skill_pool，v28 起）与宗门建设任务池 + 师承任务链（`config_manager.py:437-441` 加载并校验） |
| `impart_config.json` | 传承等阶（tier）与奖励表 |
| `adventure_config.json` | 历练路线与事件 |
| `bounty_templates.json` | 悬赏模板 |
| `storage_rings.json` | 储物戒指容量与价格 |
| `game_config.json` | 全局常量分区：`cultivation/combat/skill_system/fortune/pve/boss/bank/dual_cultivation/spirit_eye/rift`（含功能开关、战斗判定参数、成长参数，详见下文） |

### 2.4 动态配置（_conf_schema.json）

- **ACCESS_CONTROL**：WHITELIST_GROUPS（白名单群）、SHOP_MANAGERS、BOSS_ADMINS、GM_ADMINS
- **VALUES**：INITIAL_GOLD=100、BASE_EXP_PER_MINUTE=100、CHECK_IN_GOLD_MIN/MAX=50/500、BREAKTHROUGH_DEATH_PROBABILITY=**[0.005, 0.03]**、PAVILION_REFRESH_HOURS=6 等
- **SPIRIT_ROOT_SPEEDS**：伪 0.5 / 四 0.6 / 三 0.75 / 双 0.9 / 五行 1.0 / 雷 1.3 / 冰 1.25 / 风 1.25 / 暗 1.3 / 光 1.3 / 天 1.5 / 阴阳 1.8 / 融合 1.8 / 混沌 2.0 / 先天道体 2.5 / 神体 2.3
- **SPIRIT_ROOT_WEIGHTS**：伪 1 / 四 10 / 三 30 / 双 100 / 五行单 200 / 变异 20 / 天 5 / 传说 2 / 神话 1 / 禁忌体质 1
- **FILES**：DATABASE_FILE = `xiuxian_data_lite.db`

---

## 三、数据模型

### 3.1 Player（models.py）

| 分组 | 字段 |
|---|---|
| 身份 | user_id(PK)、user_name（道号）、level_index（**1-based 等级数字**，1=练气一阶，99=地仙九阶封顶）、spiritual_root、cultivation_type（灵修/体修）、lifespan、state |
| 修为/经济 | experience、gold、level_up_rate（永久突破加成，整数百分点，接入突破成功率计算） |
| 突破 | breakthrough_fail_streak（连败计数，保底机制用） |
| 闭关/签到 | cultivation_start_time、last_check_in_date |
| 装备栏 | weapon、armor、main_technique、techniques（JSON 列表，最多 4 个功法，`game_config.max_technique_slots`） |
| **四主属性** | **damage（伤害/攻击）、agility（身法/闪避命中）、speed（迅捷/出手频率）、hp（气血/生命上限）** |
| 护甲 | armor_value（装备提供的百分比减伤来源，不作为主属性；减伤率 = 护甲/(护甲+K)） |
| 技能修习 | study_target（修习目标）、battle_report_merge_count（战报合并条数偏好） |
| 宗门 | sect_id、sect_position（0宗主/1长老/2亲传/3内门/4外门）、sect_contribution、sect_task、sect_elixir_get、sect_treasure_claims（JSON，宝库已领取 id 列表，v29）、sect_master_progress（JSON，师承任务链进度：chain_id/stage_index/progress/done，v30） |
| 洞天 | blessed_spot_flag、blessed_spot_name |
| 丹药 | active_pill_effects(JSON)、permanent_pill_gains(JSON)、pills_inventory(JSON)、has_resurrection_pill、has_debuff_shield |
| 储物戒 | storage_ring、storage_ring_items(JSON) |
| 每日限制 | daily_pill_usage(JSON)、last_daily_reset |

> **已废弃**（v22 迁移废弃，不做数值映射）：旧五维（physical_damage/magic_damage/physical_defense/magic_defense/mental_power）、精神力/MP 作为战斗属性、atk/atkpractice、spiritual_qi/blood_qi 战斗衍生。

**属性来源**（attribute-numerics 规范）：创角随机初始值 + 突破成功随机成长累加；**不从修为 exp 派生战斗属性，不从境界配置读逐級基础值**。

**总属性计算**（models.py `get_total_attributes`）：基础四主属性 + 装备累加（含 route_multiplier 路线倍率）+ 心法被动（被动加成同样按心法的 route_multiplier 与修炼路线乘算——百分比项与 armor_value 平加项均乘，exp_multiplier 不乘），最后乘丹药倍率（乘区在最后）。

### 3.2 扩展模型（models_extended.py）

- **Sect**：sect_name、sect_owner、sect_scale（建设度）、sect_used_stone、sect_fairyland、sect_materials、mainbuff/secbuff（JSON）、elixir_room_level、is_system（1=系统默认宗门，v28）、faction_id（关联 sect_factions.json，v28）、status/destruction_tier（毁灭重建预留，v28）
- **player_skills**（v28 起）：新增 origin_sect_id（功法来源宗门 faction_id）与 sect_bound（宗门绑定标记，离宗保留可用、不可赠予）
- **BuffInfo**（预留）：main_buff/sec_buff/faqi_buff/fabao_weapon/armor_buff/atk_buff/blessed_spot/sub_buff
- **Boss**：boss_level、hp/max_hp、atk、defense、stone_reward、status
- **Rift**：rift_level、required_level、rewards(JSON)
- **ImpartInfo**（传承，v26 重做）：`impart_value`（传承 PK 累积值）、`claimed_tiers`（已领取等阶 JSON）
- **UserCd**：type（UserStatus）、create_time、scheduled_time、extra_data(JSON)

---

## 四、数值与计算公式（按系统）

### 4.1 闭关修炼（core/cultivation_manager.py）

- **修为公式**（:336-380）：
  `total_exp = int(BASE_EXP_PER_MINUTE(默认100) × minutes × 灵根倍率 × (1 + 心法exp_multiplier) × 丹药cultivation_speed倍率)`
- **时长上限**（handlers/player_handler.py:331-336）：`1440 + ((level_index - 1) // 10) × 360` 分钟（基础 24h，每提升一个大境界 +6h，大境界按 10 级一档）；不足 1 分钟无收益
- 机制：开始仅记录时间戳，出关时按实际分钟结算（即"离线收益"）
- **新玩家初始属性**（:291-310，创角随机区间，不读境界配置）：
  - 灵修：伤害 8-18 / 身法 5-15 / 迅捷 5-15 / 气血 90-130
  - 体修：伤害 15-30 / 身法 3-10 / 迅捷 5-12 / 气血 120-180 / 护甲 3-10；寿命 50-100
- **闭关领悟**（skill_system 规范）：结算时每满 2 小时一次领悟判定，每次 15%（需装备心法），仅触及配套池与修习目标，不含通用池
- **签到**：`gold = randint(50, 500)`，每日 1 次
- **弃道重修**：冷却 7 天，需空闲且无贷款

### 4.2 突破（core/breakthrough_manager.py）

- **成功率**（calculate_breakthrough_success_rate）：
  `final = clamp(大境界success_rate + level_up_rate% + 临时丹bonus + 破境丹bonus, 0, max_success_rate)`，连败保底在丹药 cap 之后叠加（上限 100%）
  - 基础成功率按目标等级所在大境界查表（level_config.success_rates）：练气 100% / 筑基 80% / 金丹 65% / 元婴 55% / 化神 50% / 炼虚 45% / 合体及以后 40% 地板
  - `level_up_rate`：永久加成（整数百分点），并入基础成功率、受丹药 cap 钳制；当前无产出途径（恒为 0）
  - **连败保底**：每败 +5%（`breakthrough_pity_step`），19 连败必成（`breakthrough_pity_guarantee`）
- **成功收益**：level_index +1，触发**方案A成长**（breakthrough_manager.py:200-225）：
  - 气血独立通道：`hp += hp_growth_step`（默认 15）
  - 战斗属性 `random_growth_step`（默认 5）点逐点加权随机：伤害 60% / 身法 25% / 迅捷 15%（`growth_weights`）
  - 突破失败无任何属性奖励
- **失败死亡判定**：`death_rate = clamp(uniform(0.005, 0.03) × 丹药死亡倍率, 0, 1)`（v3.7.0 起由 [0.01,0.1] 下调）
  - 死亡 → 有回生丹则复活（全属性减半），否则删号
- **失败未死惩罚**：`exp_penalty = int(本级需求 E(L) × failure_penalty_rate)`（默认 25%，**不再按总修为比例**）
- **领悟判定**：突破成功 20% / 突破失败 10%（失败领悟与掉修为惩罚并存）；突破渠道领悟池含通用池（5%，无心法时 3% 独立判定）
- 突破贷款成功突破后自动还款：`interest = principal × rate × max(1, days)`

### 4.3 丹药（core/pill_manager.py）

- **无每日次数限制**；限制为境界要求 + 永久丹每境界增益上限 = 该属性境界基础增量 × **30%**
- 临时丹：默认时长 60 分钟，支持属性倍率/寿命消耗/突破加成等效果 key，按整分钟 tick 结算
- 倍率叠加：`mult = 1.0 + Σ临时效果 + Σ永久倍率`（下限 0）
- 特殊丹：修为丹直接加经验；瞬间丹回复；重置丹返还 `int(price × 0.5)`；定魂丹获得一次负面免疫；回生丹死亡时触发复活（属性减半）

### 4.4 装备 / 商店 / 储物戒

- **装备词条**（四主属性框架，equipment_manager.py 解析）：`damage/agility/speed/hp/armor_value` 直接加成；`base_damage + weapon_coefficient_k` 进入伤害公式；`route_multiplier`（灵修/体修路线倍率）；`trigger_skills`（武器/功法触发技）；`passive_bonus`（心法常驻被动）；`skill_pool`（心法配套功法池）。items.json 法器仍走 `equip_effects(attack/defense)` 映射
- 槽位 = 武器 + 防具 + 主修心法 + 功法×3；要求 `level_index ≥ required_level_index`（1-based，0=无门槛）
- **商店**（core/shop_manager.py）：6 小时刷新；折扣 `uniform(0.8, 1.2)`；库存 `max(1, ceil(shop_weight/100))`；按权重加权不放回抽取
- **储物戒**（core/storage_ring_manager.py）：容量默认 20，**每种物品占 1 格**（与数量无关）；丹药不可入戒；升级需容量递增 + 境界达标 + 付费

### 4.5 战斗系统（managers/combat_manager.py，CombatEngine 统一引擎）

切磋、决斗、传承 PK 与 PvE（历练/秘境遭遇、世界 Boss）**共用同一结算入口** `CombatEngine.resolve_combat(fighter1, fighter2, combat_type)`（:107-），各玩法仅注入参数差异。

- **全自动回合制**：战中零操作，胜负由战前配装与随机判定链决定
- **出手权**（迅捷加权）：`P(甲出手) = 迅捷甲 / (迅捷甲 + 迅捷乙)`，每次出手一次攻击；总行动上限 `action_limit=200`（combat.action_limit），达限判平
- **伤害公式**（Muxxu 式，两步结算）：
  1. 原始伤害 `_calc_damage`（:548）：`raw = floor((武器基础伤害 + 伤害属性 × 武器系数K) × 技能倍率 × uniform(0.95, 1.05))`，下限 1；空手保底 base_damage=5、K=0.5
  2. 护甲减伤 `_apply_armor_and_reduction`（:575）：百分比减伤 `减伤率 = 护甲 / (护甲 + K)`，`K = armor_k_base(100) + armor_k_level_coeff(10) × 防守方等级`；`最终伤害 = floor(raw × (1 − 减伤率) × 技能减伤系数)`，总减伤率不超过 `damage_reduction_cap`（0.4），下限 1
- **统一判定链**：出手权 → 闪避 → 格挡 → 暴击 → 触发技 → 大招 → 伤害结算
  - 闪避率由双方身法差决定，上限 `dodge_cap`（0.4）；格挡上限 `block_cap`（0.3）
  - 暴击率基础 `base_crit_rate`（0.15，仅代码默认值，combat 段未配置）、上限 `crit_rate_cap`（0.5），暴击倍率 ×1.5（`crit_damage_multiplier`），减伤上限 `damage_reduction_cap`（0.4）
- **胜负**：一方气血 ≤ 0 即败；切磋无实质惩罚，决斗败者气血置 1
- **战报**：叙事化判定记录按合并条数输出（玩家可配 `battle_report_merge_count`，默认 10）
- **冷却**：切磋 60s / 决斗 300s（combat.spar_cooldown/duel_cooldown）
- **战力公式**（ranking_manager.py:125-126）：`战力 = 伤害 + 身法 + 迅捷 + 气血 + 护甲//2`（含装备，不含临时丹药；玩家信息与排行榜同公式）

### 4.6 技能系统（skill-system 规范，core/skill_manager.py）

- **挂载规则**：技能仅通过装备挂载——心法携带属性被动（常驻）+ 配套功法池；功法携带随机触发技与大招；武器仅携带触发技。无独立技能栏
- **触发技（引擎契约键）**：配置统一使用 `trigger_timing` / `effect_type` / `trigger_rate` / `effect_value` 四键（功法归一化层将 `trigger_condition` 映射为 `trigger_timing`，无第二套同义键）；`combat_manager` 经 `EFFECT_HANDLERS` 注册表按 `effect_type` 分发（damage_bonus/combo/stun/counter/damage_reduction 五类），功法触发技与武器挂载技共用同一入口，未知 effect_type 记 warning 并跳过、不中断战斗
- **大招（必放制）**：每本功法每场战斗最多触发一次，多本功法相互独立；归一化层为未声明概率的大招注入 `trigger_rate = 1.0`（必放），config 不得填写概率字段；触发前 MUST 过解锁门槛：自身已行动数 ≥ `min_action_index` 且满足全部血量条件（`trigger_self_hp_below` / `trigger_opponent_hp_below`），未达门槛保留限次资格（斩杀型/逆袭型/延迟型时机风格）
- **升星**：3 星封顶（`max_star`）；升星加成按乘法 `(1 + STAR_UP_BONUS)^(星级-1)` 缩放触发率与效果值，`STAR_UP_BONUS = 0.10`（config 可调），触发率截断至 1.0；满星重复参悟不再升星，按品级修为基数 × 折算比例（默认 50%）补偿修为并提示
- **领悟**：拥有与领悟分离，未领悟功法不可装备；领悟池 = 心法配套列表（按系数加权）+ 修习目标 +（仅突破渠道）通用池；三渠道概率见 §4.1/§4.2
- **装备来源 = 已领悟表（player_skills 唯一依据，v25 表）**：激活/装备功法只查 `player_skills`，储物戒中的功法秘籍物品仅作为「未领悟拥有凭据」——可设为修习目标并通过领悟判定转为已领悟，MUST NOT 参与装备判定；秘籍可经「赠予」转交他人，转交不影响源玩家已领悟状态（仍可装备）
- **功法秘籍物品**：物品名 = 技能名即为有效凭据（商店 `items.json` 4011 基础吐纳 / 4012 铁布衫；掉落表 adventure/enemies/bounty/rift 已从旧「功法残页/远古秘籍」改为掉具体秘籍名）；items.json 4001-4010 旧功法物品已标 `legacy` 并下架（无对应技能，不可作为凭据）
- **槽位与升星**：最多同时装备 4 本功法；重复获得同名功法自动升星强化（细节见上「升星」）
- **路线装备池**：灵修/体修同属性池、各自专属心法/功法/武器池，通用功法对两路线应用不同倍率；心法被动加成按心法 `route_multiplier` 与玩家修炼路线乘算（百分比项与 armor_value 平加项，exp_multiplier 除外）

### 4.7 PvE 与世界 Boss（过渡期状态）

- **功能开关**：`game_config.json` 的 `pve.enabled` / `boss.enabled`（当前均为 true）。开关关闭时对应玩法入口不可用并提示"玩法维护中"；历练（纯收益玩法）与 PvP 不受影响
- **触发概率**：历练 low/mid/high/extreme = 30/45/65/75%；秘境 = 50/70/90/95%（秘境 1-5 层映射 low/mid/high/extreme/extreme）
- **敌人生成**（enemy_manager.py:336-348，过渡方案）：从 `config_manager.level_data`（由公式配置运行时合成的 shim，仅含 level/level_name/exp_needed/success_rate）读取基准；因合成数据**不含 base_\* 字段**，实际走 exp 派生回退（`damage ≈ exp_needed//10`、`hp ≈ exp_needed//2`），再乘模板/类别（normal 0.85/elite 1.0/boss 1.2）/全局难度系数，±10% 随机
- **奖励**：胜利 `exp = base × 1.2 + 敌人exp`；失败 `exp = base × 0.3` + 安慰灵石 + HP→1；平局不变
- **世界 Boss**（boss_manager.py）：8 档境界 hp_mult 1.0→6.0；数值同样经 level_data shim 派生；Boss 会心率固定 30%（combat.boss_crit_rate）；败给 Boss 安慰奖 `reward = int(boss经验 × 总伤害 / max_hp)`；自动刷 Boss `base_exp = 全服平均exp × 1.2`（无玩家时 50000）
- **已知缺口**：独立于 level_config 的境界基准区间表将在 Boss/PvE 模块重做（bd-9u2，attribute-numerics 的 PvE 数值生成基准需求）落地

### 4.8 宗门（managers/sect_manager.py；config/sect_config.json + sect_factions.json + sect_tasks.json）

- 创建：10000 灵石 + level_index ≥ 3；初始建设度/资材各 100；默认宗门名为禁用名
- **默认（系统）宗门**：`ensure_system_sects()`（sect_manager.py:156）启动时按 `sect_factions.json` 幂等播种（is_system=1 + faction_id，main.py:440 调用）；「加入宗门」统一入口按 is_system 分流——默认宗门校验 `join_level_range` 境界段，玩家宗门走原有逻辑（sect_manager.py:374）
- **权限统一**：职位名称/权限/入口职位全部读 `sect_config.json` positions（sect_manager.py:41 起），旧硬编码 POSITION_PERMISSIONS 已删除
- **捐献**：每灵石 +1 贡献、+`scale_ratio`（默认 10）建设度（sect_manager.py:486，比值读配置）
- **宗门任务**：从 `sect_tasks.json` construction_tasks 随机抽取，按任务 `cost`/`reward` 结算——`cost.stones` 扣玩家灵石入宗门库房（按 scale_ratio 折建设度）、`cost.materials` 直接增加宗门资材（玩家外出采集语义，不消耗玩家货币）、`reward.contribution/exp` 发玩家；冷却用任务自带 `cooldown` 字段（默认 3600s），busy 状态写法不变（sect_manager.py:795）
- **建筑**（sect_config.json buildings）：洞天 `sect_fairyland` 每级 +`exp_bonus_per_level`（默认 2%）全员闭关修为，出关结算点读取（sect_manager.py:910，handlers/player_handler.py:365-374）；丹房 `elixir_room_level` 按 `unlock_pills_per_level` 解锁每日领取（sect_manager.py:995），领取标记 `sect_elixir_get` 随「签到」日重置（handlers/player_handler.py:439）；升级消耗宗门资材，默认宗门任意成员可升级、玩家宗门需长老及以上（sect_manager.py:1125）
- **镇派功法**：`mainbuff` 位由宗主镶嵌（sect_manager.py:1223），全员战斗装配时注入被动触发（core/skill_manager.py:696-705）
- **职阶晋升**：「宗门晋升」自助晋升，双门槛（贡献 + 境界）读 positions.`promotion`（sect_manager.py:1276）；`promotion: null`（宗主档）不设晋升通道，默认宗门无宗主晋升，玩家宗主保留任命/传位；宗主死亡自动按（职位, -贡献）传位
- **职阶福利**（positions.`benefits`）：`daily_stones` 每日俸禄并入「签到」加发（handlers/player_handler.py:459-474）；`shop_discount` 商店结算折扣（core/shop_manager.py:430，handlers/shop_handler.py:188）；`unlocks`/`min_position` 控制宝库领取资格
- **宗门宝库**：默认宗门按 faction `treasures`/`heart_methods` 生成传承列表（玩家宗门为空），领取按 min_position 或 benefits.unlocks 校验，`sect_treasure_claims` 记录已领取 id 防重复领取（跨退宗/重入生效）（sect_manager.py:1415/1454）
- **师承任务链**：默认宗门专属，`sect_tasks.json` master_chains 按境界段匹配，已存储的链优先于境界段重新匹配（sect_manager.py:1567）；阶段目标挂钩 PvE 胜场/历练完成/突破成功/捐献，进度存 players.sect_master_progress；阶段奖励贡献/修为/宗门功法领悟机会
- **离宗回收**（退出 sect_manager.py:446 / 踢出 :729 / 弃道重修 handlers/player_handler.py:537-542 三路径统一走 `reclaim_sect_treasures` :211）：`treasure` 宝物（含装备槽）回收归还宗门；`sect_bound` 功法/心法不回收不封印、离宗保留可用；储物戒赠予路径拦截一切宗门绑定物（core/storage_ring_manager.py:64，handlers/storage_ring_handler.py:271）
- **宗门商店**：「宗门 商店 [购买 <名称>]」，贡献点结算（非灵石），商品池配在 faction `shop` 字段（`{id, price, min_position}`，id 引用 weapons.json/heart_methods.json，min_position 缺省 4=全员），购买走 `buy_sect_shop_item`（BEGIN IMMEDIATE 事务，先职阶门槛后贡献校验，物品入储物戒）（sect_manager.py §6.3）
- **内容联动**：宗门悬赏与全局悬赏全生命周期独立——「宗门 悬赏」子命令组处理 sect_id 悬赏，全局悬赏指令只处理公共悬赏，分流校验先于缓存/冷却/活跃检查，悬赏缓存按 scope 分键（managers/bounty_manager.py scope 参数）；秘境 `sect_id`+`access=sect_member` 仅本宗成员可见（列表直接过滤，不再 🔒 标注）且准入校验不变（managers/rift_manager.py:145）；历练按权重 15 追加本宗事件组、结算消息带「🏯 宗门际遇」前缀标记（managers/adventure_manager.py:50/:331）；功法领悟全渠道注入宗门池并打 origin_sect_id/sect_bound 归属标记（core/skill_manager.py:94-105）

### 4.9 银行（managers/bank_manager.py；game_config.json bank 区）

- **存款利息（复利）**：`interest = balance × ((1 + 0.001)^days - 1)`，日利率 0.1%；存款上限 10,000,000
- **普通贷款**：日息 0.5%，期限 7 天，额度 1,000~1,000,000
- **突破贷款**：日息 0.8%，期限 3 天
- **还款（单利）**：`total = principal + int(principal × rate × max(1, days_borrowed))`
- **逾期 = 删号**

### 4.10 悬赏（managers/bounty_manager.py）

- 难度解锁：easy/normal 恒有，level≥7 解锁 hard，≥12 解锁 elite
- **奖励**：`final = int(base × 难度scale × (target/min_target) × (1 + max(0, level_index-3) × 0.06))`
- **时限**：`max(3600, unit_time × target + max(600, unit_time // 2))`
- 物品掉落 70% 触发 1 件；放弃后 1800s 接取 CD；同时只能进行 1 个；列表缓存 600s

### 4.11 历练（managers/adventure_manager.py）

- **收益**：
  `exp = (minutes × base_exp_per_min + level_index × level_bonus_exp + 完成奖励exp) × 事件exp_mult`
  `gold = (minutes × base_gold_per_min + level_index × level_bonus_gold + 完成奖励gold) × 事件gold_mult`
  - 默认路线：1800s，45 修为/分，10 灵石/分，境界加成 12/3，完成奖励 300/120，疲劳 300s
- 事件组：safe 1.1×/掉率60%；standard 1.2×/50%；risky 0.7×/15% + 受伤
- 休整 = 路线疲劳 300s（+600 受伤 / +600 PvE 战败）
- 纯收益玩法，不依赖境界基础属性，不受 pve.enabled 开关影响

### 4.12 秘境（managers/rift_manager.py）

- 探索时长 1800s；奖励 `exp/gold = randint(*rewards配置区间)`
- 物品掉落按 game_config.json 的 drop_tables 权重表掉 1 件，中/高级 50% 追加 1 件
- 稀有丹概率：1 层 3% / 2 层 5% / 3 层 10%（pill_drop_tables）
- 中途退出无奖励；PvE 战败不掉物品；PvE 战斗入口受 pve.enabled 开关控制

### 4.13 洞天福地（managers/blessed_land_manager.py）

| 档位 | 价格 | exp_bonus | 灵石/时 | 等级上限 | 修为上限/时 |
|---|---|---|---|---|---|
| 1 | 1万 | 5% | 100 | 5 | 5,000 |
| 2 | 5万 | 10% | 500 | 10 | 15,000 |
| 3 | 20万 | 20% | 2,000 | 15 | 30,000 |
| 4 | 50万 | 30% | 5,000 | 20 | 50,000 |
| 5 | 100万 | 50% | 10,000 | 30 | 100,000 |

- 升级费 `int(price × level × 0.5)`；升级后 `exp_bonus = base × (1 + level × 0.1)`，`gold/h = int(base × (1 + level × 0.15))`
- 收取：≥1h 可收，最多累计 24h；`gold = gold_per_hour × hours`；`exp = min(int(player.exp × exp_bonus × hours × 0.01), 上限 × hours)`

### 4.14 灵田（managers/spirit_farm_manager.py）

- 开垦 10000 灵石；成熟后 48h 枯萎（无收益）
- 作物：灵草 1h/500exp/100g → 血灵草 2h/1500/300 → 冰心草 4h/4000/800 → 火焰花 8h/10000/2000 → 九叶灵芝 24h/30000/6000
- 田地 Lv1-5：格数 3/5/8/12/20，升级费 5000/15000/50000/150000

### 4.15 灵眼（managers/spirit_eye_manager.py）

- 生成间隔 7200s；权重：下品 50 / 中品 30 / 上品 15 / 极品 5
- 产出：500 / 2000 / 8000 / 30000 修为每小时
- 收取 ≥1h，最多累计 24h，`exp = exp_per_hour × hours`；每人限占 1 个

### 4.16 双修（managers/dual_cultivation_manager.py）

- 冷却 3600s（双方）；请求 300s 过期；双方修为差距 ≤ 3 倍
- **定额收益**（v3.7.0 起，不再按对方总修为比例）：
  `exp = K小时 × BASE_EXP_PER_MINUTE × 60 × 自身灵根倍率 × f(t)`
  - K = `dual_cultivation.k_hours`（默认 2）；f(t) 为大境界序号系数（`realm_factor` 默认 linear，可配 power1.5/power2）
  - 双方各自按自身境界结算，与对方累计修为无关

### 4.17 传承 / 传道 PK（managers/impart_manager.py、impart_pk_manager.py；v26 重做）

- **传承值**：通过传道 PK 累积 `impart_value`；达到 `impart_config.json` 等阶阈值自动发放等阶奖励（传承心法/功法/等级提升等）
- **传道 PK**：走 CombatEngine 统一结算（`combat_type="impart_pk"`）

### 4.18 炼丹（managers/alchemy_manager.py）

- **成功率**：`rate = min(95, 配方success_rate(默认50) + (level_index - 配方要求等级) × 2)`，roll 1-100 ≤ rate 成功
- 失败材料全损

### 4.19 GM 命令（core/gm_manager.py + handlers/gm_handler.py）

- 统一入口 `修仙GM <子命令> [目标玩家] [参数]` + `修仙GM帮助`；权限独立于 BOSS_ADMINS，由 `_conf_schema.json` 的 `GM_ADMINS` 配置（main.py `_check_gm_admin`）
- 目标解析优先级：@提及 → 数字 user_id → 省略时作用于命令发送者自身
- 子命令：设置境界（境界名 → 1-based level_index，两种修炼路线通用）/设置修为/灵石/气血/真元/攻击/精神力、给予装备/给予物品（进储物戒）、卸下装备（入戒）、清除CD（需 `确认` 参数，同步 user_cd 与 player.state）、触发历练/秘境结算（推进 scheduled_time 后调正常结算）、生成Boss（委托 BossManager）
- **审计日志**：每次调用写一行 JSON 到插件数据目录 `gm_operations.log`（时间戳/GM id/目标 id/子命令/参数/成功与否），达 500MB 滚动改名保留

### 4.20 设计表→config 同步管道（scripts/sync_content_to_config.py）

- 读 `design_docs/content-design/` 下 weapons.csv / heart_methods.csv / skills.csv，按 `name` 键控 merge（同名更新/新名新增/表外不动），仅处理 status=draft/final，legacy 跳过
- 键名映射：weapons.csv `bonus_damage` → config `damage`；引擎契约校验（trigger 四键齐全、trigger_timing 词表、rate 值域、passive_bonus 词表防静默忽略）；写盘前跑 validate_budget.py，FAIL 中止不写盘；--dry-run 输出变更摘要
- 已用本脚本入库：武器 v1（9 标杆件 + 狼牙棒）、心法 v1（18 draft，含 route_multiplier 路线倍率字段）、skills.csv 全量（2026-08-08 `implement-content-design` 起）

---

## 五、数据库（SQLite，当前版本 v30）

### 5.1 表清单

| 表 | 主键 | 用途 |
|---|---|---|
| `db_info` | — | 数据库版本号（version） |
| `players` | user_id | 玩家全部数据（见 §3.1；v22 起为四主属性框架，旧五维/MP 列已废弃） |
| `player_skills` | — | 技能领悟持久化（v25，替代 players.learned_skills；v28 起含 origin_sect_id/sect_bound 宗门归属列） |
| `shop` | shop_id | 商店（'global' 单行：last_refresh_time、current_items JSON） |
| `sects` | sect_id (AI) | 宗门（sect_name UNIQUE，建设度/灵石/资材/功法 buff/丹房等级；v28 起含 is_system/faction_id/status/destruction_tier） |
| `buff_info` | id (AI)，user_id UNIQUE | 用户功法/法器 buff（预留字段） |
| `boss` | boss_id (AI) | 世界 Boss（hp/atk/defense/stone_reward/status） |
| `rifts` | rift_id (AI) | 秘境定义（预置 6 个：青云秘境→上古遗迹 + id 6 青云剑冢，后者为 rift_config.json 标记的青云门专属秘境，v31 播种） |
| `impart_info` | id (AI)，user_id UNIQUE | 传承值与已领取等阶（v26 重做） |
| `user_cd` | user_id | 忙碌状态（type/create_time/scheduled_time/extra_data JSON） |
| `pending_gifts` | id (AI) | 赠予请求（receiver/sender/item/count/expires_at，默认 24h） |
| `bank_accounts` | user_id | 存款（balance、last_interest_time） |
| `bank_loans` | id (AI)，UNIQUE(user_id,status) | 贷款（principal/interest_rate/borrowed_at/due_at/status/loan_type） |
| `bank_transactions` | id (AI) | 银行流水（trans_type/amount/balance_after/description） |
| `bounty_tasks` | id (AI) | 悬赏（target_type/target_count/current_progress/rewards/expire_time/status） |
| `blessed_lands` | id (AI)，user_id UNIQUE | 洞天福地（land_type/level/exp_bonus/gold_per_hour/last_collect_time） |
| `spirit_farms` | id (AI)，user_id UNIQUE | 灵田（level、crops JSON） |
| `dual_cultivation` | id (AI)，user_id UNIQUE | 双修记录（last_dual_time） |
| `dual_cultivation_requests` | id (AI) | 双修请求（from_id/target_id/expires_at） |
| `spirit_eyes` | eye_id (AI) | 灵眼（eye_type/exp_per_hour/owner_id/claim_time/last_collect_time） |
| `combat_cooldowns` | user_id | 战斗冷却（last_duel_time、last_spar_time） |
| `system_config` | key | 系统 KV 配置（value、updated_at） |

### 5.2 迁移历史（data/migration.py）

| 版本 | 内容 |
|---|---|
| v1 | 玩家基础表 |
| v2 | 完整修仙系统（新属性 + 宗门/Boss/秘境/传承/CD/银行/悬赏/洞天/灵田/双修/灵眼/战斗冷却全表） |
| v3-v5 | 闭关时间、签到、装备栏 + 灵气上限 |
| v6-v7 | 丹药系统、定魂丹护盾 |
| v8-v9 | 商店、体修气血 |
| v10 | 清理废弃字段（重建 players 表） |
| v11 | 储物戒 |
| v12 | 战斗属性 + 宗门字段 + 扩展表（为存量用户初始化 buff_info/user_cd/impart_info） |
| v13 | 每日限制字段 |
| v14-v15 | 银行/悬赏、默认秘境数据 |
| v16 | 洞天福地/灵田/双修/灵眼 + 初始灵眼 |
| v17 | 赠予请求持久化 |
| v18-v19 | 银行贷款/流水、银行表完整性修复 |
| v20 | user_cd.extra_data、灵眼 last_collect_time、双修请求表、战斗冷却表 |
| v21 | system_config 表 + 全新安装补齐 |
| v22 | **四主属性重构：废弃旧五维/精神力/MP，引入伤害/身法/迅捷/气血 + 功法领悟**（旧数据不映射，直接重建） |
| v23 | 玩家战报合并条数偏好字段 |
| v24 | 补齐 players.spiritual_root 字段 |
| v25 | 技能领悟持久化到 player_skills 表，players 移除 learned_skills |
| v26 | 传承系统重做：impart_info 改为传承值与已领取等阶 |
| v27 | 方案A成长模型（突破随机成长）+ 突破连败保底（breakthrough_fail_streak） |
| v28 | 默认宗门与宗门功法归属：sects +is_system/faction_id/status/destruction_tier，player_skills +origin_sect_id/sect_bound（存量行保持默认，行为不变） |
| v29 | players +sect_treasure_claims（宗门宝库领取记录，防跨退宗重复领取） |
| v30 | players +sect_master_progress（师承任务链进度 JSON） |
| v31 | rifts 播种青云剑冢（id 6，青云门专属秘境；config/rift_config.json 该条目 id 同步 4→6，消除与 id 4 玄冰地宫的冲突）（当前最新） |

---

## 六、冷却 / 限制速查表

| 系统 | 冷却 / 上限 |
|---|---|
| 闭关 | 上限 1440 + 360×((level_index-1)//10) 分钟 |
| 签到 | 每日 1 次（50~500 灵石） |
| 弃道重修 | 7 天 |
| 切磋 / 决斗 | 60s / 300s |
| 宗门任务 | 3600s |
| 双修 | 3600s（请求 300s 过期，双方修为差 ≤3 倍） |
| 悬赏放弃 / 列表缓存 | 1800s / 600s |
| 商店刷新 | 6h |
| 历练 | 路线时长 + 疲劳 300s（+600 受伤/战败） |
| 秘境探索 | 1800s |
| 洞天/灵眼收取 | ≥1h，累计上限 24h |
| 灵草枯萎 | 成熟后 48h |
| 灵眼生成 | 7200s |
| 银行贷款 | 7 天（突破贷 3 天），**逾期删号** |
| 丹药 | 无每日次数；永久丹每境界 ≤ 基础增量 30% |
| 突破死亡概率 | 失败后 uniform(0.5%, 3%) × 丹药倍率 |
| 突破连败保底 | 每败 +5%，19 连败必成 |
| 战斗行动上限 | 200 次（达限判平） |

---

## 七、附录：公式汇总（速查）

```
闭关修为   = BASE_EXP_PER_MINUTE(100) × 分钟 × 灵根倍率 × (1+心法倍率) × 丹药倍率
经验曲线   = E(L) 分段幂律：early_a·L^1.5 (L≤10)；pivot10·(L/10) (10<L≤50)；pivot50·(L/50)^1.7 (L>50)
突破成功率 = clamp(大境界查表 + level_up_rate% + 临时丹 + 破境丹, 0, 丹上限)；连败保底另加（cap 100%）
突破失败   = E(L) × 25%（未死）；死亡 uniform(0.005, 0.03) × 死亡倍率
突破成长   = hp +15；战斗属性 5 点逐点加权随机（伤害60%/身法25%/迅捷15%）
出手权     = P(甲) = 迅捷甲 / (迅捷甲 + 迅捷乙)
原始伤害   = floor((武器基础伤害 + 伤害 × 武器系数K) × 技能倍率 × uniform(0.95,1.05))，空手保底 5
回合伤害   = floor(原始伤害 × (1 − 护甲/(护甲+100+10×等级)) × 技能减伤系数)，总减伤≤40%，下限 1
判定链     = 出手权 → 闪避 → 格挡 → 暴击 → 触发技 → 大招 → 伤害结算
战力       = 伤害 + 身法 + 迅捷 + 气血 + 护甲//2
双修收益   = K(2)小时 × 100 × 60 × 自身灵根倍率 × f(大境界序号)   （定额，双向）
银行利息   = balance × ((1.001)^天数 - 1)              （复利）
贷款还款   = principal + int(principal × rate × max(1, 天数)) （单利）
悬赏奖励   = base × 难度scale × (target/min_target) × (1 + max(0, level-3) × 0.06)
炼丹成功率 = min(95, 配方rate + (level_index - 要求等级) × 2)
```

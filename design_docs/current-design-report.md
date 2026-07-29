# AstrBot 修仙插件（astrbot_plugin_monixiuxian2_2）架构与数值报告

> 生成方式：基于源码静态分析（含 `file:line` 引用），数据库结构以 `data/migration.py` 最新版本 v21 为准。

---

## 一、项目概览

- **类型**：AstrBot 插件（群聊文字修仙游戏），Python 异步，无独立构建系统
- **宿主**：运行于 `~/code/AstrBot/data/plugins/` 下，依赖 AstrBot 提供的 `Context`、`filter`、`Star` API
- **数据库**：SQLite（aiosqlite），文件为 `xiuxian_data_lite.db`，存放于 `data/plugin_data/astrbot_plugin_monixiuxian2/`
- **第三方依赖**：仅 `Pillow>=9.0.0`（图片生成）
- **静态配置**：17 个 JSON 文件（`config/`），由 `config_manager.py` 加载，修改后需重启生效
- **动态配置**：`_conf_schema.json` 暴露给 AstrBot WebUI（白名单、数值、灵根、数据库文件名）

---

## 二、代码架构

### 2.1 目录结构与分层

```
main.py                # 插件入口（Star 子类）：~90 个指令注册、依赖装配、定时任务
├── handlers/          # 指令处理层（27 个文件，按系统分类）
│   └── utils.py       # @player_required 装饰器、忙碌白名单、贷款逾期检查
├── managers/          # 业务逻辑层（18 个管理器：战斗/宗门/Boss/银行/悬赏/秘境…）
├── core/              # 通用系统层（修炼/突破/丹药/装备/商店/储物戒/GM）
├── data/              # 数据层
│   ├── data_manager.py        # 连接管理 + 玩家 CRUD（ensure_connection 自动重连）
│   ├── database_extended.py   # 宗门/Boss/秘境/银行/悬赏等扩展 CRUD
│   ├── migration.py           # 版本化迁移（当前 LATEST_DB_VERSION = 21）
│   └── default_configs.py     # 内置默认配置（config/*.json 缺失时创建）
├── models.py          # Player、Item 数据模型（dataclass）
├── models_extended.py # Sect/BuffInfo/Boss/Rift/ImpartInfo/UserCd + UserStatus 枚举
├── config/            # 17 个静态 JSON 配置
├── utils/             # 图片生成、配置加载辅助
└── tests/             # pytest（用 tests/helpers.py 的 load_module 绕过相对导入）
```

**调用链**：用户指令 → `main.py` 的 `@filter.command` 方法 → `handlers/xxx_handler.py` → `managers/` 或 `core/` 管理器 → `data/` 数据库封装。

### 2.2 关键机制

1. **命令注册**：`main.py` 中定义 `CMD_XXX` 中文常量 + `@filter.command(CMD_XXX)`，内层 `@require_whitelist`。全部为纯中文无空格指令（约 90 个，覆盖：修仙/闭关/突破/丹药/装备/商店/储物戒/宗门/Boss/排行/决斗切磋/秘境/历练/炼丹/传承/银行/悬赏/洞天/灵田/双修/灵眼/GM 等）。
2. **状态双层维护**（易踩坑）：
   - `player.state`（字符串："空闲"/"修炼中"/"历练中"…）
   - `user_cd` 表 `type` 字段（`UserStatus` 枚举：0 空闲 / 1 闭关中 / 2 历练中 / 3 探索秘境中 / 4 宗门任务中）
   - `@player_required`（handlers/utils.py:57-116）同时检查两者；忙碌时仅放行 `BUSY_STATE_ALLOWED_COMMANDS`（查看类指令，:20-54）。
3. **贷款逾期即删号**：每次指令经过 `player_required` 时检查（handlers/utils.py:123-171），另有定时任务兜底。
4. **事务保护**：并发敏感操作用 `BEGIN IMMEDIATE` + commit/rollback；定时任务先 `ensure_connection()`。
5. **定时任务**（main.py `initialize()`，均含指数退避重试）：
   - `_schedule_boss_spawn`（:393）Boss 自动生成
   - `_schedule_loan_check`（:537）贷款逾期检查
   - `_schedule_spirit_eye_spawn`（:614）灵眼生成（间隔 7200s）
   - `_schedule_bounty_check`（:672）悬赏过期检查

### 2.3 配置文件清单（config/）

| 文件 | 内容 |
|---|---|
| `level_config.json` | 灵修 36 个境界（炼气期一层 → 混元大罗金仙）：exp_needed、success_rate、各 breakthrough_*_gain |
| `body_level_config.json` | 体修 36 个境界（锻体期起），结构同上（blood_qi_gain 替代 spiritual_qi_gain） |
| `items.json` / `weapons.json` | 防具/心法/功法、武器（品级：凡品→混元先天，武器类别：剑/刀/琴/符箓等 10 类） |
| `pills.json` / `exp_pills.json` / `utility_pills.json` | 丹药（破境丹、修为丹、功能丹） |
| `alchemy_config.json` / `alchemy_recipes.json` | 炼丹配方与成功率 |
| `enemies.json` | PvE 敌人模板 |
| `boss_config.json` / `rift_config.json` / `sect_config.json` | Boss / 秘境 / 宗门配置 |
| `adventure_config.json` | 历练路线与事件 |
| `bounty_templates.json` | 悬赏模板 |
| `storage_rings.json` | 储物戒指容量与价格 |
| `game_config.json` | 全局常量（冷却、银行、灵眼、秘境掉落表，详见下文） |

### 2.4 动态配置（_conf_schema.json）

- **ACCESS_CONTROL**：WHITELIST_GROUPS（白名单群）、SHOP_MANAGERS、BOSS_ADMINS、GM_ADMINS
- **VALUES**：INITIAL_GOLD=100、BASE_EXP_PER_MINUTE=100、CHECK_IN_GOLD_MIN/MAX=50/500、BREAKTHROUGH_DEATH_PROBABILITY=[0.01, 0.1]、PAVILION_REFRESH_HOURS=6、PAVILION_PILL/WEAPON/TREASURE_COUNT=10/10/15、SHOP_DISCOUNT_MIN/MAX=0.8/1.2、SHOP_STOCK_DIVISOR=100
- **SPIRIT_ROOT_SPEEDS**：伪 0.5 / 四 0.6 / 三 0.75 / 双 0.9 / 五行 1.0 / 雷 1.3 / 冰 1.25 / 风 1.25 / 暗 1.3 / 光 1.3 / 天 1.5 / 阴阳 1.8 / 融合 1.8 / 混沌 2.0 / 先天道体 2.5 / 神体 2.3
- **SPIRIT_ROOT_WEIGHTS**：伪 1 / 四 10 / 三 30 / 双 100 / 五行单 200 / 变异 20 / 天 5 / 传说 2 / 神话 1 / 禁忌体质 1
- **FILES**：DATABASE_FILE = `xiuxian_data_lite.db`

---

## 三、数据模型

### 3.1 Player（models.py，约 50 个字段）

| 分组 | 字段 |
|---|---|
| 身份 | user_id(PK)、user_name（道号）、level_index、spiritual_root、cultivation_type（灵修/体修）、lifespan、state |
| 修为/经济 | experience、gold、level_up_rate |
| 闭关/签到 | cultivation_start_time、last_check_in_date |
| 装备栏 | weapon、armor、main_technique、techniques（JSON 列表，最多 3 个功法） |
| 战斗 | hp、mp、atk、atkpractice（每级 +4% 攻击） |
| 灵修/体修 | spiritual_qi/max_spiritual_qi、blood_qi/max_blood_qi |
| 五维 | magic_damage、physical_damage、magic_defense、physical_defense、mental_power |
| 宗门 | sect_id、sect_position（0宗主/1长老/2亲传/3内门/4外门）、sect_contribution、sect_task、sect_elixir_get |
| 洞天 | blessed_spot_flag、blessed_spot_name |
| 丹药 | active_pill_effects(JSON)、permanent_pill_gains(JSON)、pills_inventory(JSON)、has_resurrection_pill、has_debuff_shield |
| 储物戒 | storage_ring、storage_ring_items(JSON) |
| 每日限制 | daily_pill_usage(JSON)、last_daily_reset |

**总属性计算**（models.py `get_total_attributes`）：基础属性 + 装备累加 + 心法专属（exp_multiplier/灵气/气血上限），最后乘丹药倍率（乘区在最后）。

### 3.2 扩展模型（models_extended.py）

- **Sect**：sect_name、sect_owner、sect_scale（建设度）、sect_used_stone、sect_fairyland、sect_materials、mainbuff/secbuff（JSON）、elixir_room_level
- **BuffInfo**（预留）：main_buff/sec_buff/faqi_buff/fabao_weapon/armor_buff/atk_buff/blessed_spot/sub_buff
- **Boss**：boss_level、hp/max_hp、atk、defense、stone_reward、status
- **Rift**：rift_level、required_level、rewards(JSON)
- **ImpartInfo**（传承）：impart_hp/mp/atk/know/burst_per（百分比，小数存储）
- **UserCd**：type（UserStatus）、create_time、scheduled_time、extra_data(JSON)

---

## 四、数值与计算公式（按系统）

### 4.1 闭关修炼（core/cultivation_manager.py）

- **修为公式**（:405-424）：
  `total_exp = int(BASE_EXP_PER_MINUTE(默认100) × minutes × 灵根倍率 × (1 + 心法exp_multiplier) × 丹药cultivation_speed倍率)`
- **时长上限**（handlers/player_handler.py:323-328）：`1440 + (level_index // 9) × 360` 分钟（基础 24h，每个大境界 +6h）；不足 1 分钟无收益
- 机制：开始仅记录时间戳，出关时按实际分钟结算（即"离线收益"）
- **新玩家初始属性**（:279-335）：
  - 灵修：灵石 100，灵气上限 randint(100,1000)，法伤 randint(5,100)，物伤/物防 5，法防 0，精神力 randint(100,500)，寿命 100
  - 体修：寿命 randint(50,100)，气血 randint(100,500)，物伤/物防 randint(100,500)，法防 randint(50,200)，精神力 randint(100,500)
- **签到**：`gold = randint(50, 500)`，每日 1 次（player_handler.py:396-420）
- **弃道重修**：冷却 7 天，需空闲且无贷款（player_handler.py:19, 433-466）

### 4.2 突破（core/breakthrough_manager.py）

- **成功率**（:62-112）：`final = clamp(下一境界success_rate + 临时丹bonus + 破境丹bonus, 0, max_success_rate)`
- 成功：累加境界配置的 `breakthrough_*_gain`，灵气/气血回满
- **失败死亡判定**（:251-267）：`death_rate = clamp(uniform(0.01, 0.1) × 丹药死亡倍率, 0, 1)`
  - 死亡 → 有回生丹则复活（全属性减半），否则删号
- 失败未死：`exp_penalty = int(experience × 0.1)`（:290）
- 突破贷款成功突破后自动还款：`interest = principal × rate × max(1, days)`

### 4.3 丹药（core/pill_manager.py）

- **无每日次数限制**；限制为境界要求 + 永久丹每境界增益上限 = 该属性境界基础增量 × **30%**（:325-370）
- 临时丹：默认时长 60 分钟，支持属性倍率/寿命消耗/灵气气血回复/突破加成等效果 key（:204-217），按整分钟 tick 结算
- 倍率叠加：`mult = 1.0 + Σ临时效果 + Σ永久倍率`（下限 0）
- 特殊丹：修为丹直接加经验；瞬间丹回满或定量恢复灵气；重置丹返还 `int(price × 0.5)`；定魂丹获得一次负面免疫；回生丹死亡时触发复活（属性减半）

### 4.4 装备 / 商店 / 储物戒

- 装备：纯配置映射，无公式；槽位 = 武器 + 防具 + 主修心法 + 功法×3；要求 `level_index ≥ required_level_index`
- **商店**（core/shop_manager.py）：6 小时刷新；折扣 `uniform(0.8, 1.2)`；库存 `max(1, ceil(shop_weight/100))`；按权重加权不放回抽取
- **储物戒**（core/storage_ring_manager.py）：容量默认 20，**每种物品占 1 格**（与数量无关）；丹药不可入戒；升级需容量递增 + 境界达标 + 付费

### 4.5 PvP 战斗与战力（managers/combat_manager.py、ranking_manager.py）

- **HP/MP**（:33-50）：`hp = exp // 2 × (1 + hp_buff)`；`mp = exp × (1 + mp_buff)`
- **ATK**（:52-70）：`atk = max(1, int(exp // 10 × (1 + atkpractice × 0.04 + atk_buff)))`
- **回合伤害**（:72-93）：`dmg = int(round(uniform(0.95, 1.05), 2) × atk × (1 + atk_buff))`；会心判定 `randint(0,99) < crit_rate`，暴击 ×1.5
- **减伤**（:95-110）：`reduction = def / (def + 100)`；`final = max(1, int(dmg × (1 - reduction)))`
- PvP 最多 100 回合；切磋不耗 HP/MP，决斗耗，败者 HP=1；冷却：切磋 60s / 决斗 300s
- **战力榜公式**：`power = 物伤 + 法伤 + 物防 + 法防 + 精神力 // 10`（含装备，不含临时丹药，ranking_manager.py:91-126）

### 4.6 PvE（managers/pve_combat_manager.py、enemy_manager.py）

- **触发概率**：历练 low/mid/high/extreme = 30/45/65/75%；秘境 = 50/70/90/95%（秘境 1-5 层映射 low/mid/high/extreme/extreme）
- **敌人生成**（enemy_manager.py:275-344）：
  `base_exp = level_config[敌人等级].exp_needed`；`hp = int(base_exp // 2 × hp_mult)`；`atk = int(base_exp // 10 × atk_mult)`；`mp = base_exp`
  - 难度系数：normal 0.85 / elite 1.0 / boss 1.2
  - 敌人等级范围：同大境界 ∩ [玩家等级-2, 玩家等级+1]
- **奖励**：胜利 `exp = base × 1.2 + 敌人exp`；失败 `exp = base × 0.3` + 安慰灵石 + HP→1；平局不变

### 4.7 世界 Boss（managers/boss_manager.py）

- 8 档境界（练气~大乘）：hp_mult 1.0→6.0，atk_mult 1.0→3.5，reward_mult 1.0→6.0
- **生成数值**（:140-150）：`max_hp = base_exp × hp_mult // 2`；`atk = base_exp × atk_mult // 10`；`stone_reward = base_exp × reward_mult // 10`；炼虚+（level_index≥15）防御 40-90
- Boss 会心率固定 30%；败给 Boss 安慰奖 `reward = int(boss经验 × 总伤害 / max_hp)`
- 掉落：100% 掉 1 件；元婴+ 50%、炼虚+ 70% 追加 1 件
- 自动刷 Boss：`base_exp = 全服平均exp × 1.2`（无玩家时 50000）

### 4.8 宗门（managers/sect_manager.py）

- 创建：10000 灵石 + level_index ≥ 3；初始建设度/资材各 100
- **捐献**：每灵石 +1 贡献、+10 建设度
- **宗门任务**：贡献 randint(10,30)，资材 = 贡献×10；冷却 3600s
- 宗主死亡自动按（职位, -贡献）传位

### 4.9 银行（managers/bank_manager.py；game_config.json）

- **存款利息（复利）**：`interest = balance × ((1 + 0.001)^days - 1)`，日利率 0.1%；存款上限 10,000,000
- **普通贷款**：日息 0.5%，期限 7 天，额度 1,000~1,000,000
- **突破贷款**：日息 0.8%，期限 3 天
- **还款（单利）**：`total = principal + int(principal × rate × max(1, days_borrowed))`
- **逾期 = 删号**（:356-388）

### 4.10 悬赏（managers/bounty_manager.py）

- 难度解锁：easy/normal 恒有，level≥7 解锁 hard，≥12 解锁 elite
- **奖励**（:214-226）：`final = int(base × 难度scale × (target/min_target) × (1 + max(0, level_index-3) × 0.06))`
- **时限**：`max(3600, unit_time × target + max(600, unit_time // 2))`
- 物品掉落 70% 触发 1 件；放弃后 1800s 接取 CD；同时只能进行 1 个；列表缓存 600s

### 4.11 历练（managers/adventure_manager.py）

- **收益**（:395-413）：
  `exp = (minutes × base_exp_per_min + level_index × level_bonus_exp + 完成奖励exp) × 事件exp_mult`
  `gold = (minutes × base_gold_per_min + level_index × level_bonus_gold + 完成奖励gold) × 事件gold_mult`
  - 默认路线：1800s，45 修为/分，10 灵石/分，境界加成 12/3，完成奖励 300/120，疲劳 300s
- 事件组：safe 1.1×/掉率60%；standard 1.2×/50%；risky 0.7×/15% + 受伤
- 休整 = 路线疲劳 300s（+600 受伤 / +600 PvE 战败）

### 4.12 秘境（managers/rift_manager.py）

- 探索时长 1800s；奖励 `exp/gold = randint(*rewards配置区间)`
- 物品掉落按 game_config.json 的 drop_tables 权重表掉 1 件，中/高级 50% 追加 1 件
- 稀有丹概率：1 层 3% / 2 层 5% / 3 层 10%（pill_drop_tables）
- 中途退出无奖励；PvE 战败不掉物品

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
- 收益：`A 得 int(B.exp × 0.1)`，`B 得 int(A.exp × 0.1)`

### 4.17 传承 / 传道 PK（managers/impart_manager.py、impart_pk_manager.py）

- 传承：hp/mp/atk/know（会心）/burst（爆伤）百分比 buff；战斗中 `crit_rate = int(round(know_per × 100))`
- **PK 伤害**：`dmg = max(1, atk - def // 2) × uniform(0.8, 1.2)`，最多 20 回合
- 胜方传承 atk +uniform(0.01, 0.05)（上限 1.0），败方扣胜方增益的一半；挑战失败 `exp_loss = int(exp × 0.01)`

### 4.18 炼丹（managers/alchemy_manager.py）

- **成功率**：`rate = min(95, 配方success_rate(默认50) + (level_index - 配方要求等级) × 2)`，roll 1-100 ≤ rate 成功
- 失败材料全损

---

## 五、数据库（SQLite，当前版本 v21）

### 5.1 表清单（18 张）

| 表 | 主键 | 用途 |
|---|---|---|
| `db_info` | — | 数据库版本号（version） |
| `players` | user_id | 玩家全部数据（见 §3.1，约 50 列） |
| `shop` | shop_id | 商店（'global' 单行：last_refresh_time、current_items JSON） |
| `sects` | sect_id (AI) | 宗门（sect_name UNIQUE，建设度/灵石/资材/功法 buff/丹房等级） |
| `buff_info` | id (AI)，user_id UNIQUE | 用户功法/法器 buff（预留字段） |
| `boss` | boss_id (AI) | 世界 Boss（hp/atk/defense/stone_reward/status） |
| `rifts` | rift_id (AI) | 秘境定义（预置 5 个：青云秘境→上古遗迹） |
| `impart_info` | id (AI)，user_id UNIQUE | 传承百分比增益 |
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

### 5.2 主要索引

- `players(level_index)`；`sects(sect_owner)`、`sects(sect_scale DESC)`
- `buff_info(user_id)`、`impart_info(user_id)`、`boss(status, create_time DESC)`
- `pending_gifts(receiver_id)`、`pending_gifts(expires_at)`
- `bank_loans(user_id)`、`bank_loans(status)`、`bank_transactions(user_id)`、`bank_transactions(created_at)`
- `bounty_tasks(user_id)`、`blessed_lands(user_id)`、`spirit_farms(user_id)`、`dual_cultivation(user_id)`
- `spirit_eyes(owner_id)`、`dual_cultivation_requests(target_id/expires_at)`、`system_config(updated_at)`

### 5.3 迁移历史（data/migration.py）

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
| v21 | system_config 表 + 全新安装补齐（当前最新，新装直接建全量 schema） |

---

## 六、冷却 / 限制速查表

| 系统 | 冷却 / 上限 |
|---|---|
| 闭关 | 上限 1440 + 360×(level_index//9) 分钟 |
| 签到 | 每日 1 次（50~500 灵石） |
| 弃道重修 | 7 天 |
| 切磋 / 决斗 | 60s / 300s |
| 宗门任务 | 3600s |
| 双修 | 3600s（请求 300s 过期） |
| 悬赏放弃 / 列表缓存 | 1800s / 600s |
| 商店刷新 | 6h |
| 历练 | 路线时长 + 疲劳 300s（+600 受伤/战败） |
| 秘境探索 | 1800s |
| 洞天/灵眼收取 | ≥1h，累计上限 24h |
| 灵草枯萎 | 成熟后 48h |
| 灵眼生成 | 7200s |
| 银行贷款 | 7 天（突破贷 3 天），**逾期删号** |
| 丹药 | 无每日次数；永久丹每境界 ≤ 基础增量 30% |
| 突破死亡概率 | 失败后 uniform(1%, 10%) × 丹药倍率 |

---

## 七、附录：公式汇总（速查）

```
闭关修为   = BASE_EXP_PER_MINUTE(100) × 分钟 × 灵根倍率 × (1+心法倍率) × 丹药倍率
突破成功率 = clamp(境界success_rate + 临时丹 + 破境丹, 0, 上限)
突破死亡   = uniform(0.01, 0.1) × 死亡倍率
HP         = exp // 2 × (1 + hp_buff)
MP         = exp × (1 + mp_buff)
ATK        = max(1, int(exp // 10 × (1 + atkpractice × 0.04 + atk_buff)))
回合伤害   = uniform(0.95, 1.05) × atk × (1 + atk_buff)   （会心 ×1.5）
减伤       = def / (def + 100)，最终伤害 max(1, dmg × (1 - 减伤))
战力       = 物伤 + 法伤 + 物防 + 法防 + 精神力 // 10
银行利息   = balance × ((1.001)^天数 - 1)              （复利）
贷款还款   = principal + int(principal × rate × max(1, 天数)) （单利）
悬赏奖励   = base × 难度scale × (target/min_target) × (1 + max(0, level-3) × 0.06)
双修收益   = int(对方exp × 0.1)  双向
炼丹成功率 = min(95, 配方rate + (level_index - 要求等级) × 2)
传承PK伤害 = max(1, atk - def // 2) × uniform(0.8, 1.2)
```

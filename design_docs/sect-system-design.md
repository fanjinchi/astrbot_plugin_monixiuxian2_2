# 宗门系统扩展设计：默认宗门·建设师承·毁灭重建·职阶晋升

> **文档状态**：设计基线（2026-08-18 建立，与玩家拍板后的决策记录）。
> 本文是"宗门系统扩展"的总设计文档；正式变更提案走 OpenSpec（`openspec/changes/`）。
> 标注 **[策划可配]** 的条目表示策划可通过 JSON 配置直接调整，无需改代码。
> 现状分析依据：`managers/sect_manager.py`、`config/sect_config.json`、`models_extended.py:35-81`、`data/migration.py`（sects 表）。

## 0. TL;DR 与分期

现有宗门是纯玩家自建的骨架系统（创建/加入/捐献/任务/职位/排行），数据模型里预留了洞天、丹房、镇派功法等字段但全部未接线，无 NPC/系统宗门概念。本设计引入**默认宗门**（系统势力），并把宗门与功法/悬赏/秘境/历练等系统联动，全部内容走 JSON 配置，方便策划后续修改。

| 期 | 内容 | 对应 OpenSpec change |
|---|---|---|
| **一期（本次实施）** | 默认宗门配置化（1-2 个做功能验证）、宗门建设（接线预留字段）、师承任务线、职阶晋升（基础版）、第一/二梯队联动（宗门功法池/宗门悬赏/宗门秘境/宗门历练事件组） | `add-default-sects-and-sect-growth`（拟） |
| 一期配套 | 上述功能的功能测试用例（测试平台） | 独立测试 change（交其他 agent 实施） |
| **二期** | 宗门毁灭与重建（剧情线/世界事件触发、散落物去向、回忆/寻回/重建任务）、Boss 名称与掉落配置化（前置改造）、世界事件调度抽象 | 待立项 |
| **三期（仅预留扩展点）** | 宗门 NPC 人格化（对话/关系）、分宗、正魔阵营对抗、宗门大比 | 待立项 |

## 1. 设计决策记录（已拍板）

1. **定位 A+B 混合**：默认宗门既是新手出身地（提供入门引导、基础传承），又是持续存在的世界势力（发起事件、发布任务），不由任何玩家拥有。
2. **自由离开**：玩家可自由退出默认宗门；宗门传承功法/心法具有"只可传予本宗之人"的**固有属性**（不可抄录/赠予/交易给他人），与玩家是否在职无关——离宗后本人已习得的功法/心法**仍可正常使用**；宗门之宝（武器/防具）不能带出，离宗时回收归还宗门。
3. **不做分宗**（想法保留，本期不扩展）。
4. **一期范围**：第一、二梯队系统接入宗门可配置 + 新机制先做**建设**和**师承**；默认宗门只配置 1-2 个做功能验证；一切做成可配置。
5. **NPC 系统计入后续开发**，本期架构改动须预留扩展点（见 §5.7）。
6. **毁灭与重建**：宗门可被剧情线/世界事件摧毁，资源宝贝部分散落（不再强制归属宗门），玩家可接任务参与重建；毁灭程度分档（轻/中/重/几乎全毁），先配置一个默认丢失程度。
7. **职阶晋升**：贡献点 + 境界双门槛晋升职位，职位产出福利（灵石、核心传承解锁、宗门内折扣）。

## 2. 概念模型

```
                        ┌─────────────────────────────┐
                        │      config/sect_factions.json     │
                        │  默认宗门定义（策划可配，1~N 个）    │
                        └──────────────┬──────────────┘
                                       │ 插件启动时播种（seed）
                                       ▼
        ┌───────────────────────────────────────────────────┐
        │                 sects 表（统一存储）                 │
        │  is_system=1 默认宗门（无宗主，系统运营）            │
        │  is_system=0 玩家宗门（现有逻辑不变）                │
        └───────┬───────────────────────────────┬───────────┘
                │                               │
      玩家拜入（低门槛/新手）            玩家自建（现有：筑基+1万灵石）
                │                               │
                ▼                               ▼
      ┌──────────────────┐          ┌──────────────────────┐
      │ 师承任务线/建设任务 │          │ 捐献/宗门任务（现有）   │
      │ 职阶晋升→福利解锁   │          │ 建设/职阶晋升（新机制    │
      │ 出师（自由离开）    │          │ 对玩家宗门同样生效）    │
      └──────────────────┘          └──────────────────────┘
```

**关键原则**：建设与职阶晋升机制对默认宗门和玩家宗门**通用**；默认宗门只是多了"系统拥有 + 配置驱动内容 + 可被毁灭重建"的属性。

### 2.1 物品/传承的归属状态机

宗门相关物品分两类，生命周期不同：

- **传承功法/心法**："只可传予本宗之人"是**功法固有属性**——任何时候都不可抄录、赠予、交易给他人；玩家离宗后本人已习得的**仍归本人所有、正常使用**（习得即私有，与在职状态无关）。
- **宗门之宝**（武器/防具）：宗门财物，授予弟子**使用权**；不可交易/赠予，离宗/被逐时**回收归还宗门**。

毁灭玩法的"散落"建立在这套归属上：

```
 宗门宝库/传承 ──授予弟子──▶ 【宗门归属】
      │                     ├─ 功法/心法：本人习得即私有，终身可用；
      │                     │   固有属性=不可转让给他人
      │                     └─ 宗门之宝：仅授予使用权
      │                          │
      │                    玩家离宗/被逐 ──▶ 宝物回收归还宗门（功法不受影响）
      │                          │
      ▼                          ▼（宗门被毁灭时按档位判定，二期）
 【流落】失去宗门属性，可自由传播
      │
      ├─▶ 被某宗门「收纳」──▶ 重新获得该宗门属性
      └─▶ 被玩家获得 ──▶ 普通个人物品（无宗门属性）
```

## 3. 配置层设计（策划通道）

所有新内容走 `config/*.json` 静态配置（`config_manager.py` 自动加载，缺失时从 `data/default_configs.py` 播种默认值；修改后重启生效——这是本项目既有配置通道，策划改法与现有 20 个配置文件完全一致）。

### 3.1 `config/sect_factions.json`（新增，核心）**[策划可配]**

默认宗门定义。一期只放 1-2 个，结构支持任意扩展：

```json
{
  "factions": [
    {
      "id": "qingyun",
      "name": "青云门",
      "alignment": "正",
      "description": "剧情文案：立派渊源、山门所在、当代格局……",
      "join_level_range": [0, 5],
      "skill_pool": "sect_qingyun",
      "heart_methods": ["heart_qy_001"],
      "treasures": [{"type": "weapon", "id": "wpn_qy_001", "min_position": 2}],
      "buildings": {
        "fairyland": {"max_level": 5, "exp_bonus_per_level": 0.02},
        "elixir_room": {"max_level": 5, "unlock_pills_per_level": ["pill_xxx"]}
      },
      "elders": [{"name": "玄诚子", "title": "传功长老"}],
      "destruction": {
        "enabled": true,
        "default_loss_profile": "medium",
        "loss_profiles": {
          "light":  {"scale": 0.2, "materials": 0.2, "stones": 0.2, "skills": 0.1, "treasures": 0.0},
          "medium": {"scale": 0.5, "materials": 0.5, "stones": 0.5, "skills": 0.3, "treasures": 0.2},
          "heavy":  {"scale": 0.8, "materials": 0.8, "stones": 0.8, "skills": 0.6, "treasures": 0.5},
          "ruined": {"scale": 1.0, "materials": 1.0, "stones": 1.0, "skills": 0.9, "treasures": 0.8}
        }
      }
    }
  ]
}
```

- `elders` 仅为文案/任务署名槽位（NPC 人格化在三期，见 §5.7）。
- `destruction` 二期才消费，但**一期就把配置结构定下来**，避免二期返工。
- 播种机制：启动时把 faction 写入 `sects` 表（`is_system=1`），已存在则跳过/按配置同步文案字段。

### 3.2 `config/skills.json`（扩展）**[策划可配]**

现有"池分组"机制（通用/灵修/体修/传承 4 池）直接扩展：新增 `"sect_qingyun": [...]` 池。宗门功法条目增加可选字段 `"sect_bound": true`（固有属性标记：只可传予本宗之人，不可抄录/赠予/交易）。改动：`core/skill_manager.py` 领悟池逻辑支持按玩家宗门注入对应池。

### 3.3 `config/heart_methods.json`（扩展）**[策划可配]**

心法条目增加可选字段 `"sect_id": "qingyun"` + `"sect_bound": true`，即"镇派心法"。获取途径由宗门职阶福利发放（不走商店）。

### 3.4 `config/weapons.json` / `items.json`（扩展）**[策划可配]**

武器/防具条目增加可选字段 `"sect_id"` + `"treasure": true`（宗门之宝，离宗回收）+ `"min_position"`（何职阶可用）。发放走职阶福利/师承任务奖励，不进全局商店。

### 3.5 `config/bounty_templates.json`（扩展）**[策划可配]**

悬赏模板增加可选字段 `"sect_id"`（该模板仅在对应宗门悬赏榜出现）。文案已支持叙事描述，直接写宗门主题悬赏（"为本门巡视后山"等）。

### 3.6 `config/rift_config.json`（扩展）**[策划可配]**

秘境条目增加可选字段 `"sect_id"` + `"access": "sect_member"`（宗门专属秘境，仅本宗成员可探索）。

### 3.7 `config/adventure_config.json`（扩展）**[策划可配]**

事件组增加可选 `"sect_id"` 过滤——宗门主题历练事件（"长老传功""执事堂派差"），仅本宗成员历练时可能触发。

### 3.8 `config/sect_config.json`（扩展）**[策划可配]**

职位体系升级为"晋升门槛 + 福利"定义，对默认/玩家宗门通用：

```json
{
  "positions": {
    "4": {"name": "外门弟子", "permission": 1,
          "promotion": {"contribution": 500, "level_index": 2},
          "benefits": {"daily_stones": 0,   "shop_discount": 1.0,  "unlocks": []}},
    "3": {"name": "内门弟子", "permission": 2,
          "promotion": {"contribution": 2000, "level_index": 4},
          "benefits": {"daily_stones": 100, "shop_discount": 0.95, "unlocks": ["heart_qy_001"]}},
    "2": {"name": "亲传弟子", "permission": 5,
          "promotion": {"contribution": 8000, "level_index": 6},
          "benefits": {"daily_stones": 300, "shop_discount": 0.9,  "unlocks": ["wpn_qy_001"]}},
    "1": {"name": "长老", "permission": 8,
          "promotion": {"contribution": 30000, "level_index": 9},
          "benefits": {"daily_stones": 800, "shop_discount": 0.85, "unlocks": []}},
    "0": {"name": "宗主", "permission": 10,
          "promotion": null,
          "benefits": {"daily_stones": 2000, "shop_discount": 0.8, "unlocks": []}}
  },
  "scale_ratio": 10
}
```

> 高档位补记（实施落地值）：长老 `promotion` = 贡献 30000 + 境界 9、福利 800 灵石/日 + 0.85 折；宗主 `promotion = null`（不设晋升通道，只能传位获得）、福利 2000 灵石/日 + 0.8 折。

> ✅ `scale_ratio` 已接线（实施完成）：捐献折算读配置，原 `sect_manager.py`/`database_extended.py` 硬编码已移除。

### 3.9 `config/sect_tasks.json`（新增）**[策划可配]**

建设任务与师承任务的任务池定义：

```json
{
  "construction_tasks": [
    {"id": "build_001", "name": "修缮山门", "type": "donate_materials",
     "cost": {"materials": 50}, "reward": {"contribution": 30}, "cooldown": 3600}
  ],
  "master_task_chains": [
    {"id": "chain_qy_01", "sect_id": "qingyun", "level_range": [0, 2],
     "stages": [
       {"name": "入门演武", "type": "win_pve", "count": 3,
        "reward": {"contribution": 50, "exp": 200},
        "text": "玄诚子：新入门弟子，先去后山演武场…"},
       {"name": "采药历练", "type": "adventure_complete", "count": 1,
        "reward": {"contribution": 80, "skill_learn_chance": "sect_qingyun"},
        "text": "……"}
     ]}
  ]
}
```

师承任务链 = 按境界段划分的多阶段引导任务，每阶段挂钩现有行为（PvE 胜场、历练完成、突破成功、炼丹等，复用悬赏的 `progress_tags` 进度挂钩思路），奖励含贡献点与宗门功法领悟机会。文案字段承载剧情。

## 4. 玩法机制详设

### 4.1 拜入与出师（一期）

- 新玩家境界在 faction 的 `join_level_range` 内可拜入默认宗门。「加入宗门」为统一入口，按目标宗门 `is_system` 分流校验逻辑（默认宗门校验境界区间，玩家宗门保持现有自由加入）。
- 默认宗门**无宗主职位**，玩家最高可升至长老之下（亲传/执事类）。权限统一读 `sect_config.json` 的 positions.permission（实施时已删除 `sect_manager.py` 硬编码 `POSITION_PERMISSIONS`，两套定义合并为配置单一真源）。
- 「出师」= 退出默认宗门：自由离开，已习得的宗门功法/心法**保留且正常使用**（其不可转让的固有属性不变），宗门之宝回收归还宗门，贡献清零（与现有退出语义一致）。
- 玩家宗门不受 `join_level_range` 限制（保持现有自由加入）。

### 4.2 宗门建设（一期，接线预留字段）

激活 `sects` 表三个死字段，默认/玩家宗门通用：

| 字段 | 玩法 | 配置来源 |
|---|---|---|
| `sect_fairyland` 洞天等级 | 全员闭关修为加成 `exp_bonus_per_level × level` | `sect_factions.json` buildings / 玩家宗门用全局默认表 |
| `elixir_room_level` 丹房等级 | 按等级解锁宗门丹药领取（接线现有死字段 `sect_elixir_get` 与 `reset_sect_elixir_get()`） | 同上 |
| `mainbuff/secbuff` 镇派功法位 | 宗主（玩家宗门）/系统（默认宗门）镶嵌功法，全员获得被动 buff | 功法池配置 |

升级消耗资材 + 建设度；资材来自捐献与建设任务（§3.9）。这就是"宗门建设的任务"的主循环：**做任务得贡献和资材 → 资材升建筑 → 建筑反哺全员**。

### 4.3 师承任务线（一期）

- 仅默认宗门有（配置里 `master_task_chains` 挂在 faction 上）。
- 按玩家境界段匹配任务链，链内阶段顺序推进；阶段类型复用现有行为计数（战斗/历练/突破/捐献）。
- 奖励：贡献点（主）、修为、宗门功法领悟机会、低阶宗门之宝试用。
- 文案以 `elders` 署名发布，制造"师父领进门"的叙事感（NPC 人格化之前的轻量替代）。

### 4.4 职阶晋升（一期基础版）

- 晋升条件：`promotion.contribution`（贡献点）+ `promotion.level_index`（境界）双门槛，玩家主动「宗门晋升」指令触发校验。
- 福利（`benefits`）：每日灵石（并入「签到」按职阶加发）、宗门商店折扣、解锁传承内容（心法/功法/宝物的获取资格）。
- 玩家宗门仍保留宗主任命/传位的现有操作；默认宗门只能走晋升通道。

### 4.5 宗门毁灭与重建（二期，本期仅落配置结构）

- **触发**：设计好的剧情线系列任务（世界事件链）或世界活动事件。技术蓝本 = 现有 Boss 定时生成 + 群广播通道（`main.py:447` `_schedule_boss_spawn`），二期抽象为通用世界事件调度。
- **档位**：轻/中/重/几乎全毁，丢失比例按 `loss_profiles` 配置逐资源结算；`default_loss_profile` 是未指定档位时的默认丢失程度（已拍板：先配 `medium`）。
- **散落**：被毁宗门的功法/心法/宝物按档位比例进入【流落】状态（失去宗门属性，可自由传播），去向可配置：
  - 遗失到秘境 → 生成秘境探索寻回任务
  - 被世界 Boss 夺走 → 追杀 Boss 寻回
  - 流入散修/黑市 → 寻常悬赏式寻回任务
  - 流传到其他宗门 → 对应宗门开出"夺宝/交涉"任务，可配置"无法夺回"
- **重建任务**：捐灵石/资材重建建筑；**回忆任务**：弟子参与"回忆整理"把流落功法重新收纳归宗（恢复宗门属性）；寻回任务对应上面四类去向。
- 前置改造：Boss 名称池与掉落表外移配置（现硬编码 `boss_manager.py:136,155`），否则"Boss 夺走宗门之宝"无法配置化。

## 5. 架构影响与改造清单

按一期实施顺序排列；每项标注（一期/二期/预留）。

### 5.1 数据库迁移（一期）

- `sects` 表新增列：`is_system`（0/1）、`faction_id`（关联配置，可空）、`status`（normal/damaged/rebuilding，二期消费，一期先建列）、`destruction_tier`（可空，二期消费）。
- `player_skills` 表新增：`origin_sect_id` + `sect_bound`（来源宗门与固有不可转让标记；无封印状态）。
- 装备/物品归属：储物戒物品 JSON 结构增加可选 `sect_id`/`treasure` 标记（不入新表，沿用 JSON 字段惯例）。
- 全部进 `data/migration.py` 新版本迁移。

### 5.2 配置加载（一期）

- `config_manager.py` 注册 `sect_factions.json`、`sect_tasks.json`；`data/default_configs.py` 提供默认值（含 1-2 个示例默认宗门）。
- 启动时 faction → `sects` 表的幂等播种（`managers/sect_manager.py` 新增 `ensure_system_sects()`，`main.py` 初始化时调用）。

### 5.3 宗门逻辑重构（一期）

- `sect_manager.py` 拆分：归属/绑定物回收、建设升级、职阶晋升各成方法；`POSITION_PERMISSIONS` 与 `sect_config.json` 的 permission 两套定义已合并——硬编码表已删除，权限判断统一读 `sect_config.json`。
- `sect_fairyland`/`elixir_room_level`/`mainbuff` 接线（§4.2）。
- 退出宗门路径加"宗门之宝回收"钩子（默认宗门与玩家宗门通用；功法/心法离宗不回收）。

### 5.4 功法/心法联动（一期）

- `core/skill_manager.py`：领悟池按 `player.sect_id` → faction `skill_pool` 注入；宗门功法打 `sect_bound` 标记。
- 心法/武器的发放走职阶福利与师承奖励的新发放路径（不进全局商店，避免污染现有经济）。

### 5.5 悬赏/秘境/历练联动（一期）

- 悬赏榜按 `sect_id` 过滤出"宗门悬赏"分区（`bounty_manager.py` 列表与接取逻辑加过滤参数）。
- 秘境准入校验加 `sect_member` 检查（`rift_manager.py`）。
- 历练事件组抽取时按玩家宗门追加过滤（`adventure_manager.py`）。

### 5.6 商店折扣（一期，最小实现）

- `core/shop_manager.py` 购买结算时读玩家职阶 `shop_discount`；宗门限定货架（"宗门宝库"）可后置到二期。

### 5.7 NPC 扩展点（预留，一期不实现人格化）

- faction 配置的 `elders` 槽位固定下来：一期仅用于任务署名与文案；三期人格化（对话/关系/参战）时在同一配置结构上扩展 `dialogue`/`affinity` 等字段，代码侧对应一个 `sect_npc_manager` 挂载点。**一期不做任何 NPC 行为逻辑，只保证配置结构向前兼容。**

### 5.8 世界事件调度（二期）

- 抽象现有 Boss/灵眼定时循环为"世界事件调度器"（统一指数退避、群广播、开关配置），宗门毁灭事件链挂上去。一期不抽象，避免过度设计。

### 5.9 测试配套（一期）

- 单元测试：`tests/test_sect_*.py`（晋升门槛、绑定物回收、建设升级、播种幂等）。
- 功能测试：独立 OpenSpec change，在 `functional_tests/cases/sect/` 下编写测试平台用例（拜入/师承链推进/建设/晋升/出师回收全流程）。注意 `functional_tests/platform-gap-report.md` 的能力边界：RNG seed、DB 直断、时间加速属 Unsupported/Partially，用例设计优先只依赖 Supported 能力（指令链路 + 消息断言）。

### 5.10 实施期决策（2026-08-19 落地补记）

实施过程中拍板的细节，设计文档此前未写明，特此补记（均已在代码中生效）：

1. **师承链匹配优先级**：玩家已存储的未完成链优先于按境界段重新匹配（`sect_manager.py` `_match_master_chain`）——跨境界段时继续原链，不被新区间顶掉。
2. **历练宗门事件组权重**：宗门事件组以固定权重常量 15 追加进抽取池（`adventure_manager.py` `SECT_EVENT_GROUP_WEIGHT = 15`），不进配置文件。
3. **宗门宝库对玩家宗门为空**：宝库条目仅由 faction 配置的 `treasures`/`heart_methods` 生成，玩家自建宗门无 faction 配置，宝库为空（`sect_manager.py` `_get_treasury_entries`）。
4. **建设任务 `donate_materials` 语义**：`cost.materials` 表示玩家为宗门采集/筹备资材——宗门资材直接增加，**不消耗玩家任何货币/物品**；仅 `cost.stones` 类任务扣玩家灵石（并入宗门库房按 `scale_ratio` 折建设度）。
5. **建筑升级权限**：默认（系统）宗门任意成员可升级建筑；玩家宗门需长老及以上职阶（`sect_manager.py` `upgrade_building`）。
6. **建筑升级消耗**：一期实现仅消耗宗门资材（`upgrade_cost` 按当前等级索引），不扣建设度——与 §4.2 "资材 + 建设度" 的原描述有出入，以代码为准，二期如需建设度消耗再补。

## 6. 分期实施计划

**一期（本 change + 测试 change）**
1. DB 迁移与配置加载（§5.1/5.2）
2. faction 播种 + 拜入/出师 + 绑定物回收（§4.1、§5.3）
3. 宗门功法池/心法/宝物配置扩展与发放（§5.4）
4. 建设机制接线（§4.2）
5. 师承任务线（§4.3）+ 建设任务池（§3.9）
6. 职阶晋升与福利（§4.4、§5.6）
7. 悬赏/秘境/历练宗门过滤（§5.5）
8. 单测 + 功能测试用例（§5.9）
9. 文档同步：`current-design-report.md` §4.8 重写、`api-overview.md`、`project-architecture.md`、`README.md` 更新日志

**二期**：毁灭与重建（§4.5）+ Boss 配置化 + 世界事件调度抽象 + 宗门宝库货架。
**三期**：NPC 人格化、分宗、正魔阵营、宗门大比。

## 7. 策划配置速查表

| 策划想改什么 | 改哪个文件 | 字段 |
|---|---|---|
| 新增/修改默认宗门 | `sect_factions.json` | `factions[]` 整条 |
| 宗门剧情文案 | `sect_factions.json` | `description`、`elders[]` |
| 宗门专属功法 | `skills.json` | `"sect_<id>"` 池 |
| 镇派心法 | `heart_methods.json` | `sect_id`/`sect_bound` |
| 宗门之宝 | `weapons.json`/`items.json` | `sect_id`/`treasure`/`min_position` |
| 晋升门槛与福利 | `sect_config.json` | `positions.*.promotion`/`benefits` |
| 建设/师承任务 | `sect_tasks.json` | `construction_tasks`/`master_task_chains` |
| 宗门悬赏 | `bounty_templates.json` | 模板加 `sect_id` |
| 宗门秘境 | `rift_config.json` | `sect_id`/`access` |
| 宗门历练事件 | `adventure_config.json` | 事件组加 `sect_id` |
| 毁灭档位与丢失比例 | `sect_factions.json` | `destruction.loss_profiles`（二期生效） |

## 8. 开放问题（已拍板，2026-08-18）

1. **一期是否含职阶晋升？** ✅ 含基础版（贡献+境界门槛+灵石/折扣/传承解锁三类福利）。
2. **「拜入宗门」与现有「加入宗门」指令** ✅ 合并为一个入口，按目标宗门类型（`is_system`）分流校验逻辑。
3. **出师后能否再拜入其他默认宗门？** ✅ 允许改换门庭，贡献清零；已习得的原宗门功法/心法保留可用（固有不可转让属性不变），宗门之宝已在离宗时回收。
4. **每日灵石福利发放方式** ✅ 并入「签到」，按职阶加发，不设独立指令。
5. **默认宗门一期示例数量与风格** ✅ 2 个：一个正派学院风新手引导向（暂名"青云门"）、一个风格迥异（暂名魔道/散修联盟向），验证配置的差异表达能力；具体名称文案属配置，策划后续可改。

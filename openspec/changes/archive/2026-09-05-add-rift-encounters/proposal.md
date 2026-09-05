# Proposal: add-rift-encounters

## Why

秘境探索目前是纯挂机玩法：进入后等待 30 分钟，结算时按概率强制触发一场自动 PvE 战报，玩家全程无任何决策点。这缺乏修仙小说中"闯秘境"的经典体验（破阵、遭遇、夺宝），且强制 PvE 惩罚（战败气血归零）对无操作空间的玩家不公平感强。传承守护挑战同样在结算时强制立即开打。同时秘境没有自己的怪物生态——所有秘境共用按玩家境界匹配的全局怪物池，万妖洞与玄冰地宫刷出相同的怪。

## What Changes

- **新增秘境遭遇机制**：`/完成探索` 基础结算（修为/灵石/事件/掉落）保持不变，结算后进入遭遇判定。遭遇分三类：古阵谜题、妖兽拦路（按遭遇概率独立判定，**不互斥**可同时触发）、传承之地（沿用既有 `legacy_chance` 触发）。遭遇以内存 pending 状态挂起（每玩家每类最多一个），10 分钟惰性过期，不写入 `UserStatus` 忙碌状态机。
- **新增秘境古阵谜题**：程序生成的多谜题族随机抽取，首版三族——**五行破阵**（生克联想：相克破阵/轮转补缺/逆生溯源三模板，题面碑文自带生克对照表）、**洛书数阵**（三阶幻方挖空求值，碑注给出行列和）、**灵龟辨窟**（真假话逻辑推理，三窟选一）。答案均为单个短 token（五行字/数字/甲乙丙）。通过 `探索秘境` 子命令作答（`/探索秘境 破阵 <答案>`），默认 2 次机会（可配置）；答对获得额外奖励（追加秘境掉落 roll + 小额修为），答错/过期**零惩罚**（仅失去额外奖励）。
- **BREAKING（行为变更）：秘境 PvE 改为可选挑战**。结算时不再自动触发战斗，改为提示"妖兽拦路"遭遇；玩家用 `/探索秘境 迎战` 主动接战，胜利获敌人修为奖励+额外掉落并计入师承任务链 PvE 胜场（win_pve），失败气血受损（hp=1）但不影响已结算的基础奖励，无视则零损失。现有全部秘境的结算自动 PvE 一并改造。
- **BREAKING（行为变更）：传承守护挑战改为可选遭遇**。秘境与历练结算命中 `legacy_chance` 后不再立即自动挑战守护 NPC，改为挂起"传承之地"遭遇；玩家用 `/探索秘境 传承` 应邀挑战（胜利获得对应来源类型传承实例；失败不致死、机缘消耗），无视/过期视为机缘消散，零惩罚。宗门宝库领取路径（玩家主动发起）不变。
- **秘境怪物池配置**：`rift_config.json` 秘境条目新增 `enemy_group` 字段（引用 `enemies.json` 中无 `level_range` 的定向组，经 `spawn_enemy_from_group` 触达）与 `encounter_rate` 覆盖字段；缺省时回落现有按玩家境界匹配的全局池与默认触发率。
- **GM 强制触发**：`修仙GM` 新增 `触发秘境谜题 [目标]`、`触发秘境妖兽 [目标]`、`触发秘境传承 [目标]` 三个子命令，直接为目标玩家挂起对应 pending 遭遇（带默认 rift 上下文），供功能测试使用；同步更新 GM 帮助文本。
- **测试秘境脚手架（验证后拆除）**：双路径播种测试秘境「试炼古境」（id 7、无等级限制、低奖励——`_create_all_tables` 默认种子 + 迁移任务，覆盖全新安装与存量库）+ `rift_config.json` 条目（`enemy_group: "rift_test"`、`encounter_rate: 1.0` 保证确定性触发）+ `enemies.json` 测试组（石傀儡模板，无 `level_range`）。功能验证通过后整体移除，正式秘境怪物届时经 design_docs 内容管线统一配置。

## Capabilities

### New Capabilities

- `rift-encounter`: 秘境遭遇机制——结算后触发判定、pending 遭遇生命周期（挂起/响应/过期）、`探索秘境` 子命令（破阵/迎战/传承）入口、可选 PvE 挑战结算规则（含师承任务链计数）、传承之地遭遇、秘境怪物池与触发率配置。
- `rift-puzzle`: 秘境谜题引擎——多谜题族程序生成与随机抽取（五行破阵/洛书数阵/灵龟辨窟）、按族校验答案与尝试次数、额外奖励发放、零惩罚规则。

### Modified Capabilities

- `gm-commands`: 新增 `触发秘境谜题`、`触发秘境妖兽`、`触发秘境传承` 三个 GM 子命令需求（含目标解析与帮助文本）。
- `impart-system`: 「传承获取途径」需求变更——秘境/历练结算触发后由立即自动挑战守护 NPC 改为挂起传承之地遭遇、玩家应邀挑战；宗门宝库路径不变。

## Impact

- **代码**：`managers/rift_manager.py`（结算流程接入遭遇判定、传承触发改挂起、掉落存储逻辑抽取为可复用辅助方法）、`managers/adventure_manager.py`（历练传承触发改挂起）、`managers/pve_combat_manager.py`（新增 `challenge_rift_beast` 定向组挑战方法，胜负显式比较玩家 ID；秘境结算不再自动调用 `trigger_pve_combat`）、`handlers/rift_handlers.py`（探索秘境子命令分发）、`handlers/gm_handler.py` + `core/gm_manager.py`（新 GM 子命令）、`main.py`（装配共享 EncounterStore、指令 docstring/帮助文本、迎战胜利路径消费 pve_won 推进师承任务链）、新增 `core/rift_puzzle_manager.py`（谜题引擎）与 `core/encounter_store.py`（共享 pending 遭遇存储）。
- **配置**：`config/rift_config.json`（条目新字段 + 测试条目）、`config/enemies.json`（测试组）、`data/default_configs.py`（默认配置同步）；新配置键在读取处按 `explore_events` 先例回落默认值，兼容存量配置文件。
- **数据库**：`data/migration.py` 新增迁移版本 + `_create_all_tables` 默认种子同步（播种测试秘境行）；不新增表，pending 遭遇为内存态。
- **玩法/数值**：秘境结算 PvE 与传承守护挑战均由强制改为可选（全局行为变更），需按 AGENTS.md §14 同步 `design_docs/current-design-report.md` 等相关设计资料。
- **测试**：`tests/` 新增谜题引擎与遭遇流程单测，改写 `tests/test_rift_adventure_narrative.py` 的两个传承内联挑战断言；`functional_tests/cases/` 新增秘境遭遇域用例（webtest 回归由用户手动发起）。
- **文档**：README 更新日志、`metadata.yaml` 版本、`/修仙帮助` 文本、GM 帮助文本。

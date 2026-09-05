# Design: add-rift-encounters

## Context

现状（动机见 proposal.md）：

- 秘境流程为纯挂机：`enter_rift` 写 `UserStatus.EXPLORING`（30 分钟）→ `finish_exploration`（`managers/rift_manager.py:305`）一次性结算修为/灵石/事件/掉落，并按概率**强制**自动 PvE（`trigger_pve_combat`，`managers/pve_combat_manager.py:281`）。
- 传承守护挑战同为结算时内联自动战斗：秘境侧 `legacy_chance` 命中即调 `challenge_legacy_guardian`（`managers/rift_manager.py:420`），历练侧同构（`_maybe_trigger_legacy` 定义于 `managers/adventure_manager.py:359`，结算调用点 `:296`）；宗门宝库领取路径是玩家主动发起，不在本次范围。
- 秘境结算的 `pve_won` 有下游消费者：`main.py:1213` 与 `core/gm_manager.py:1069` 据此推进师承任务链 `win_pve` 计数——移除结算自动 PvE 后必须在新迎战路径补回，否则秘境来源的师承计数归零。
- 掉落分两层：`_roll_rift_drops`（`managers/rift_manager.py:525`）**只 roll 返回物品列表**，入库（丹药背包/储物戒）逻辑内联在 `finish_exploration` 的 `:389-413`——谜题/迎战奖励复用掉落前需先抽取该存储块。
- 怪物按**玩家境界**匹配全局组（`enemies.json` 的 low/mid/high/top 组带 `level_range`）；`spawn_enemy_from_group`（`managers/enemy_manager.py:412`）已支持无 `level_range` 的定向组（传承守护组先例），不会被普通匹配误命中。**注意**：定向组生成敌人的 `user_id` 是 `guardian_` 前缀（`managers/enemy_manager.py:488`），而旧 PvE 奖励/战报用 `winner.startswith("enemy_")` 判负——新挑战方法不得沿用前缀判定。
- 全插件无任何"提问-等待回答"式交互；指令均为单往返。`探索秘境` 当前签名为 `(event, rift_id: int = 0)`（`main.py:1188`），且整条链路只有 `@require_whitelist`，**没有** `@player_required`——忙碌白名单对该指令不生效。
- GM 入口为单指令分发：`/修仙GM <子命令> [目标] [参数]`（`handlers/gm_handler.py:23`），`GMManager` 已注入 `rift_mgr`（`main.py:310`）。
- 迁移三条路径（`data/migration.py:518-611`）：全新安装与旧库重建都只走 `_create_all_tables`（含 `default_rifts` 种子 `:450-480`），不执行 `MIGRATION_TASKS`——测试秘境播种必须双写。
- 约束：AGENTS.md §2 双层状态机（新增进行中状态成本高）、§7 版本更新 checklist、§14 玩法变更同步 design_docs、§15 内容进 design_docs（本变更只含工程性 config 与测试脚手架，不填充正式内容）。

## Goals / Non-Goals

**Goals:**

- 结算后遭遇机制：概率触发、内存 pending、惰性过期、`探索秘境` 子命令响应。
- 多谜题族谜题引擎：五行破阵/洛书数阵/灵龟辨窟三族程序生成，纯函数式、可单测。
- 秘境 PvE 改可选挑战；秘境级 `enemy_group`/`encounter_rate` 配置；迎战胜利推进师承任务链。
- 传承守护挑战改可选遭遇（秘境+历练两条路径）。
- GM 强制触发三个子命令 + 测试秘境脚手架（验证后拆除）。

**Non-Goals:**

- 探索中途推送遭遇（方案 B）与多层互动副本（方案 C）——本次不做，遭遇只在结算点触发。
- 群抢答、图片渲染谜面（机制先跑通，渲染皮肤后续再说）。
- 正式秘境的怪物生态配置——属内容策划，届时走 §15 design_docs 管线，本变更只留测试组。
- 历练（adventure）的普通 PvE 与路线机制保持现状（仅传承触发的交付方式随本变更改造）。
- 宗门宝库传承领取路径保持"领取即挑战"现状。

## Decisions

### D1: pending 遭遇存内存 dict，惰性过期

pending 以内存结构按玩家存三类遭遇（谜题/妖兽/传承之地，每类最多一个），条目带 `created_at`、`expires_at`（默认 600s，配置 `encounter_ttl_seconds`）。响应指令时检查时间戳判过期，无需定时任务；热重载后存储清空，响应指令命中空表 → 回复"机缘已消散"。存储的具体形态见 D8（共享 EncounterStore）。

- **备选**：写 `user_cd.extra_data` 持久化。否决理由：玩家结算后已是空闲态，遭遇不是"进行中状态"，写库会把 AGENTS.md §2 的双层状态机拖进来（还要同步 `_TIME_SKIP_RULES` 与忙碌白名单），为 10 分钟短寿命数据付出迁移+状态机成本不值。
- **代价**：热重载丢遭遇。可接受——零惩罚设计下玩家无损失。

### D2: 子命令挂在 `探索秘境` 参数位

`handle_rift_explore` 签名改为 `(event, action: str = "", value: str = "")`：首参为纯数字 → 走进秘境（向后兼容；AstrBot 对有默认值的 str 参数直接赋值，`/探索秘境 3` → `action="3"` 数字优先回落）；`破阵` → 谜题作答（`value` 为答案，缺答案 → 用法提示不耗次数）；`迎战` → 接受妖兽挑战；`传承` → 应邀挑战传承之地；其他 → 用法提示。不新增顶层指令，避免指令名膨胀（用户明确选择子命令形式）。整条链路受 `_is_pve_enabled()` 维护门控（`main.py:1190`），维护期间子命令一并关闭，可接受。

### D3: 谜题引擎独立成纯逻辑模块，多谜题族随机抽取

新增 `core/rift_puzzle_manager.py`：`RiftPuzzle` 数据类（family、template、question_text、answer、attempts_left=2）+ 谜题族注册表（生成时按族随机抽取）+ `check(answer) -> (correct | wrong | invalid)`。不含 IO、不读数据库，pytest 直接覆盖。首版三个谜题族：

- **五行破阵**：相生 `金→水→木→火→土→金`、相克 `金→木→土→水→火→金` 两张映射表 + 三模板随机；题面把生克对照表作为"碑文"嵌入，防知识门槛也防搜索。
- **洛书数阵**：洛书基阵 `[[4,9,2],[3,5,7],[8,1,6]]` 的 8 种旋转/镜像 × 整体平移量 d（行列和变为 15+3d）生成变体，随机挖一格为答案；碑注直接给出目标和数，玩家零知识门槛。
- **灵龟辨窟**：固化 2-3 个真假话逻辑模板（如「三句碑铭只有一句真话」），按构造保证唯一解；碑铭语句与洞窟（甲/乙/丙）随机置换防背题。

非法输入按族判定（五行题须为单个五行字、数阵题须为数字、辨窟题须为甲/乙/丙），不耗尝试次数。后续新增谜题族只需注册新生成器，遭遇挂起/判分/奖励机制零改动。

题面模板为**结构性工程文案**（含变量槽、由生成器拼装），随代码走，类比 `explore_events` 的 config 文案先例（`managers/rift_manager.py:358`），不属 §15 内容填充；若后续要纳入 narrative lint 管线可另行提案。

### D4: 遭遇编排留在 RiftManager，GM 复用同一入口

`finish_exploration` 基础结算完成后追加 `_roll_encounters(player, rift_id, rift_level)`：按 `puzzle_rate`/`beast_rate`（顶层默认，秘境条目 `encounter_rate` 存在时覆盖两者）独立判定，挂起 pending 并把题面/提示拼进结算消息。GM 子命令调 `rift_mgr.force_puzzle_encounter(user_id)` / `force_beast_encounter(user_id)` / `force_legacy_encounter(user_id)`——与判定路径共用挂起逻辑，仅跳过概率。目标玩家无需处于探索中（测试场景友好）。传承之地遭遇不走 `_roll_encounters`：沿用既有 `legacy_chance` 触发（见 D8），不受 `encounter_rate` 覆盖。

**GM 强触的缺省 rift 上下文**（强触路径无结算上下文，必须定义缺省）：谜题修为基数取秘境 1 级 `exp_range` 生成（与 D6 公式衔接）、妖兽遭遇 `rift_level=1` 且 `enemy_group=None`（回落全局池，走 D5 既有回落路径）、传承遭遇 `legacy_type="rift"`。GM 目标解析须用 `single_token_is_target=True`（参照 `cmd_give_legacy`，`core/gm_manager.py:439-441`）：`_resolve_target` 默认把单个数字 token 当命令数值参数而回落到发送者（`cmd_force_rift` `:1032-1038` 有同款绕过），否则 `修仙GM 触发秘境妖兽 900000002` 会误作用于 GM 本人。

**新配置键的存量兼容**：`_load_config_with_default` 不会把 default_configs 新键合并进已存在的 `config/rift_config.json`，`puzzle_rate`/`beast_rate`/`encounter_ttl_seconds`/`puzzle_attempts` 在读取处按 `explore_events` 先例（`managers/rift_manager.py:358-360`）回落 `RIFT_CONFIG` 默认值，否则存量部署读到 `None`。

### D5: 可选 PvE 的结算与奖励切割，奖励组装留在 RiftManager

`finish_exploration` 删除自动 `trigger_pve_combat` 调用，基础奖励不再被战斗结果修改。迎战路径分层：`pve_combat_mgr.challenge_rift_beast(player, enemy_group_key | None)` **只负责战斗**——有组 key 走 `spawn_enemy_from_group`，无则回落 `spawn_enemy(player.level_index, category)`——返回（胜负、战报、敌人修为）；奖励组装留在 RiftManager 的 `accept_beast_challenge`：胜利时敌人修为入账 + 一次掉落 roll，失败 hp=1，不动已发奖励。低层 pve 管理器不反向依赖 rift 管理器的私有掉落方法。pending 的 beast 遭遇需记录 `rift_level` 与 `enemy_group` 供迎战时使用。

- **胜负判定必须显式比较** `result.winner == player.user_id`（平局单列：视同挑战失败，hp=1、机缘消耗，与传承口径一致）：禁止沿用 `_calculate_rewards` 的 `winner.startswith("enemy_")` 前缀判定——定向组敌人 `user_id` 是 `guardian_` 前缀（`managers/enemy_manager.py:488`），前缀判定会把定向组妖兽获胜误判为玩家胜利。`challenge_legacy_guardian` 的显式比较（`managers/pve_combat_manager.py:384`）为正确先例。
- **迎战通路与师承任务链**：`main.py` 对 `迎战` 子命令**直接调** `rift_mgr.accept_beast_challenge`（不经 rift_handlers 的 yield 字符串，与 `handle_rift_complete` 直调 `finish_exploration` 的既有模式一致；数字/`破阵`/`传承` 仍经 rift_handlers 分发）。`accept_beast_challenge` 胜利时返回含 `pve_won=True` 的结果，由 main.py 消费并调 `sect_mgr.advance_master_progress(user_id, "win_pve")`（复用 `handle_rift_complete` `main.py:1213-1223` 的 try/except 模式）。`修仙GM 触发秘境结算` 不再有战斗，`pve_won` 恒 False，属语义正确（无战斗则无胜场）。
- **掉落入库重构**：`_roll_rift_drops` 只 roll 不入库（`managers/rift_manager.py:525-576`），入库逻辑内联在 `finish_exploration:389-413`。实施时先把该存储块抽为 `_store_dropped_items(player, dropped_items) -> str`，结算/破阵/迎战三处复用——否则谜题与迎战奖励会被 roll 出但静默丢失。

- **平衡注意**：旧逻辑失败会扣基础结算（exp×0.3、gold=0、hp=1），新逻辑失败仅 hp=1 且不动已发奖励，整体对玩家更有利；修为/灵石产出期望上升。属玩法变更，按 §14 同步 `design_docs/current-design-report.md`。

### D6: 谜题奖励复用秘境掉落管线

破阵成功：一次 `_roll_rift_drops(player, rift_level, item_chance=100)` + `_store_dropped_items` 入库（规则与秘境掉落完全一致）+ 小额修为（结算路径 = 本次结算修为 × 0.2 取整；GM 强触路径基数按 D4 缺省生成）。尝试次数可配置（`puzzle_attempts`，默认 2）。谜题 pending 条目需记录 `rift_level` 与修为基数（结算路径来自当次结算，GM 路径来自 D4 缺省）——`RiftPuzzle` 本体不含奖励上下文，由 EncounterStore 条目携带。

### D7: 测试秘境脚手架与拆除路径

- **双播种**（迁移三路径决定）：`data/migration.py` 的 `_create_all_tables` 默认种子 `default_rifts`（`:450-480`）加 id 7 行（覆盖全新安装/重建库），同时新增 `MIGRATION_TASKS` 版本任务 `INSERT OR IGNORE` 同一行（覆盖存量 v32 库升级）。
- **任务链下限门槛**：增量任务链仅对 `>= TASK_CHAIN_MIN_VERSION(=32)` 的库开放——v32 是 `_create_all_tables` 冻结的完整 schema 基线，更早的旧库缺少任务依赖的表（如 rifts），进任务链只会在缺失表上崩溃，必须落入重建路径（`data/migration.py:20-23`、`:584-593`）。
- `config/rift_config.json` 加 id 7 条目：`enemy_group: "rift_test"`、`encounter_rate: 1.0`（必触发，保证测试确定性）；`data/default_configs.py` 的 `RIFT_CONFIG` 同步。
- `config/enemies.json` 加 `rift_test` 组（无 `level_range`，1-2 个石傀儡模板，倍率取低值保证低压测试）。
- 拆除 = 反向 PR：删三组配置 + 移除双播种（种子行与迁移任务）+ 新增一个删除 rift id 7 行的迁移版本。tasks 中列为独立收尾任务。

### D8: 共享 EncounterStore 与传承遭遇改造（秘境+历练同构）

pending 存储抽为独立轻量类 `core/encounter_store.py` 的 `EncounterStore`（内存 dict + TTL + 同类覆盖刷新），由 `main.py` 装配单例并注入 `RiftManager` 与 `AdventureManager`；**GM 不直接持有 store**，经既有的 `rift_mgr.force_*` 方法触达（`GMManager` 已注入 `rift_mgr`，少改构造函数）。**响应逻辑集中在 RiftManager**（它已持有 `pve_combat_mgr`/`impart_mgr`/`storage_ring_manager`，迎战与应邀的奖励/战斗编排无需新依赖）。

传承触发改造（两条路径同构）：

- 秘境：`finish_exploration` 移除内联 `challenge_legacy_guardian` 调用（`managers/rift_manager.py:415-448`），命中 `legacy_chance` 后改为 pend 来源 `rift` 的 legacy 遭遇，结算消息提示"使用 /探索秘境 传承 应邀"。
- 历练：`_maybe_trigger_legacy`（`managers/adventure_manager.py:359`）同构改造（来源 `adventure`），保留现有 try/except 异常降级风格（传承触发失败绝不中断历练正常结算）。
- 响应：`/探索秘境 传承` → `rift_mgr.accept_legacy_challenge(user_id)`：复用 `challenge_legacy_guardian`（失败不致死、无奖励的逻辑一行不动；平局按未胜处理、机缘消耗），胜利后按 pending 记录的 `legacy_type` 调 `impart_mgr.create_legacy(player.user_id, legacy_type, activate=False)`，叙事文案沿用 `legacy_encounter` 模板簇。
- 命名取舍：历练来源的传承遭遇也经 `/探索秘境 传承` 响应（`探索秘境` 实为遭遇响应枢纽），语义瑕疵接受，由结算消息文案指引玩家。

### D9: 忙碌状态与遭遇响应的关系

`探索秘境` 链路无 `@player_required`（仅 `@require_whitelist`），忙碌白名单不生效——**忙碌玩家可以响应遭遇**。接受该现状：破阵是纯文本作答无副作用；迎战/传承会改 hp，与闭关/历练中自动 PvE 交错时叙事略怪但无状态机冲突（遭遇本就不写 `UserStatus`）。不为此给子命令加状态检查（保持简单），也不把 `探索秘境` 加进忙碌白名单。

## Risks / Trade-offs

- **结算消息过长**（基础结算 + 谜题题面 + 妖兽提示三段落）→ 题面文案控制在 6 行内；aiocqhttp 会 strip 首尾空白，需要留白处按 AGENTS.md §9 用零宽空格。
- **玩家不知道有 pending 遭遇**（结算消息被刷屏淹没）→ 响应指令无 pending 时的提示文案引导（"暂无可响应的机缘；完成探索有概率触发"）。
- **EncounterStore 为进程内单例**：多群共用同一插件实例时天然一致，无多进程场景；热重载丢失按 D1 降级。
- **`探索秘境` 参数歧义**：数字优先判定，`破阵`/`迎战`/`传承` 为保留关键字；玩家不可能用数字以外的秘境 ID（DB 自增 int），无真实冲突。
- **可选 PvE 与传承应邀制带来产出/获取期望变化**（见 D5；传承侧由"触发即强打"变为"可无视"，获取率将下降）→ 数值微调留给 design_docs 同步时一并校准，本变更不预调。
- **既有 pytest 破坏面**：`tests/test_rift_adventure_narrative.py:288-334` 两个传承内联挑战文案断言（`_maybe_trigger_legacy` 与秘境 `legacy_chance=1.0` 路径）必然失败，需按应邀制改写——已点名列入 tasks 6.1。
- **测试脚手架误留**→ proposal 与 tasks 明确"验证后拆除"为独立任务；`encounter_rate: 1.0` 只挂在测试条目，不影响正式秘境。

## Migration Plan

1. 新增迁移版本播种测试秘境（`INSERT OR IGNORE`，重复执行安全）+ `_create_all_tables` 默认种子同步（D7 双播种）。
2. 配置/代码上线后需重载插件或重启 AstrBot（JSON 静态配置约定）。
3. 无玩家数据迁移；行为变更（结算自动 PvE 与传承自动挑战移除）随代码生效，玩家侧无感知成本。
4. 回滚：还原代码与配置即可，测试秘境行无玩家引用（无 FK），留一行无害数据，或加删除迁移清除。

## Open Questions

- 谜题/妖兽遭遇的具体默认触发率（初值建议 puzzle 30%、beast 50%，即沿用旧 rift low 难度 50% 量级）在实现时按 design_docs 数值基线定稿——不影响 spec 与任务拆分。

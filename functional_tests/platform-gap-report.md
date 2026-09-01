# 网页测试平台能力差距报告

> 对着 `astrbot_plugin_testplatform`（webtest）实际 REST 能力与首批功能测试用例需求整理。
> 更新日期：2026-09-01。范围：`add-functional-test-suite` 第一批 28 条用例 + `add-sect-functional-tests` 9 条宗门用例 + `update-sect-functional-tests`（宗门指令统一后）新/改用例 + `adapt-pvp-effects-to-platform-v020`（PvP 随机效果用例 deterministic/seed 化）+ `gm-test-time-and-rng-controls`（插件侧 GM 时间快进/清除全部冷却/随机种子）+ `sect-pre-run-hook`（宗门域用例基线复位内嵌 pre_run_hook）。映射平台 v0.3.0（v0.2.0：`deterministic`/`seed`、`expect_not`、`combine`、one-shot 编排 CLI；v0.3.0：pin `isolate` 派生身份、用例级 `pre_run_hook`）。

## Supported（可直接依赖）

| 能力 | 说明 | 用例依赖方式 |
|---|---|---|
| 用例 JSON 加载 | 顶层 `cases/*.json`，`name` 与文件名一致，自动校验必填字段 | 全部用例 |
| 步骤类型 `send` / `expect` / `sleep` | 真实注入消息并轮询回复 | 全部用例 |
| 文本断言 | 子串匹配；`re:` 前缀正则搜索 | 全部期望步骤 |
| 负向断言 `expect_not` | 窗口内任何回复都不得命中 `match`；命中即失败并记录违规消息（v0.2.0）；可配 `combine: true` 跨条拼接后断言 | 非成员秘境列表断言不含 `青云剑冢`（`sect-content-filter`） |
| 确定性随机 `deterministic`+`seed` | 每次 `send` 注入前重置全局随机种子（int，默认 42），尽力让概率型行为可复现（v0.2.0） | 宗门悬赏生命周期、宗门历练事件标记等概率型用例声明 `deterministic: true`；必要时 `--repeat` 采样兑底 |
| 跨条拼接 `combine: true` | 一次 `send` 触发多条回复时按换行拼接后再匹配（v0.2.0） | 多回复结算消息（悬赏/历练）跨条断言用 |
| 批量运行与 one-shot 编排 | `case check --source`（源与平台副本语义比对）、`case run --repeat N` 聚合、`run-all --sync-from --reload --export --quiet --include-manual`、`--export` 落盘结果 + `summary.json`（v0.2.0） | `test_suite_ctl.py run/export` 透传等效参数（任务 3.2/4.2/4.3） |
| 插件热重载运维端点 | `POST /api/ops/plugin-reload`（JSON `{ plugin_name }`）可不经 Dashboard 触发插件重载，迁移/代码变更后立即可测 | 宗门用例起跑前重载插件使 v31 秘境播种与最新折扣文案生效 |
| 临时会话 | 每次运行新建会话，私聊玩家默认唯一 ID，轨迹独立保存 | 私聊冒烟用例 |
| 固定身份 `pin_players` | 群聊可钉住 GM/玩家真实 `user_id`，承担状态继承；值为对象 `{"user_id": "...", "isolate": true}` 时派生隔离身份（v0.3.0） | 全部 PvP / GM / 装备 / 宗门用例（固定 pin）；派生身份用于无需精确身份匹配特权的用例 |
| 逐用例状态隔离 `isolate: true` | `pin_players` 值对象带 `isolate` 时按用例派生 `{user_id}__{case名}`（run-all 跨用例隔离、同用例跨轮稳定）；同设 `fresh` 派生 `{user_id}__{case名}__r{run序号}`（用例级+跨轮双重隔离，v0.3.0） | 需要全新生身份且不依赖 GM 等按 user_id 精确匹配特权的用例 |
| 用例级 `pre_run_hook` | 顶层声明 `{"command": "<shell>", "timeout": 60}`（timeout 可选正数秒、默认 60）：每次运行（含 repeat 每轮）首个步骤前由服务端执行 shell，注入 `WEBTEST_CASE_NAME`/`WEBTEST_RUN_INDEX`/`WEBTEST_CONVERSATION_ID`/`WEBTEST_PLAYERS`（JSON：player 标签→实际 user_id）；非零退出/超时记 error 且不执行后续步骤（v0.3.0） | 宗门全部用例：command 调 `test_suite_ctl.py fixture --profile sect --yes` 每轮前置复位基线 |
| 群聊模拟 | 通过 `webtest!group!{group_id}` 走真实 AstrBot 群聊管线 | 全部群聊用例 |
| 运行结果 API | `POST /api/cases/{name}/runs`、`GET /api/runs/{id}` 返回步骤结果与消息轨迹 | 控制脚本 `run` / `export` |
| 消息流可见 | 会话 `feed` 双向消息、运行轨迹消息快照 | 排查断言超时 |
| 批注 | 网页端可对消息加批注，CLI/REST 可读 | 人工反馈闭环 |

## Partially supported（可用但有条件/需要绕行）

| 能力 | 现状 | 限制 | 绕行方式 |
|---|---|---|---|
| 群聊指令触发 | AstrBot 全局 `wake_prefix` 为 `#`，群聊必须带唤醒前缀 | 不带 `#` 时事件不会进入插件 Filter | 用例中所有群聊 `send` 统一加 `#` 前缀（已落地） |
| GM 身份 | 由插件 `ACCESS_CONTROL.GM_ADMINS` 控制，平台只负责投递 `user_id` | 必须先在 AstrBot 插件配置中加入固定 GM ID 并重载插件 | 测试实例已把 `900000001` 加入 `GM_ADMINS`；随环境配置文档记录 |
| 随机/概率效果验证 | 随机效果单次运行不保证触发；`deterministic`+`seed` 为尽力而为（宿主可能仍有异步活动耗掉 RNG） | 极端情况下同 seed 仍不可复现 | **PvP 20 个 sampled 效果用例已全部声明 `deterministic: true` + `seed: 42`**（seed 在每个 send 注入前重置，固定行为）；必要时用例内 `pre_run_hook`（调 `test_suite_ctl.py fixture`）+ `--repeat N` 聚合文本证据，`_count_evidence` 统计触发次数（v0.3.0 起无需外部 `--fixture`，该参数保留兼容）；宗门随机池/事件用例同此策略；`--repeat` 仅在确定性不可靠时兑底。**插件侧补充（`gm-test-time-and-rng-controls` 起）**：GM「随机种子 <整数>」为当前进程注入固定全局 `random.seed`（突破机缘轮盘等唯一未播种调用点已一并收编），「随机种子 重置」恢复系统熵；与平台 deterministic 同机制、后执行者生效——平台用例开 `deterministic: true` 时每次 send 前会覆盖 GM 种子，故 GM 种子适用于未开 deterministic 的用例与手动探测；进程级污染同进程其他插件，仅限独立测试实例 |
| 技能/功法授予 | 平台无“直接授予已学技能”命令 | 只能通过聊天命令学习，路径长且随机 | fixture 脚本直接写 `player_skills` 表，固定 `skill_id` 与星级（v0.3.0 起由用例 `pre_run_hook` 调 fixture 前置复位，无需外部编排） |
| 心法/功法装配 | 插件 GM `给予装备` 的 `_item_exists` 不识别 `heart_methods.json` | 无法用 GM 命令把心法放储物戒 | 用例 `pre_run_hook` 调 fixture 把 `长春功`/`疾风迅雷功` 写入 `storage_ring_items`（v0.3.0 起无需外部编排）；用例不再依赖 GM 给心法 |
| `@` 目标选择 | 平台只注入 `Plain` 文本，没有结构化 `At` 消息段 | GM 命令无法走 `@目标` 分支 | 用例使用纯数字 ID 参数，走 `_resolve_target` 数字分支 |
| 状态/DB 断言 | 平台只能断言“回复文本” | 不能直接查 DB 验证玩家属性/储物戒/`user_cd` | 用例 `pre_run_hook` 调 fixture 写库复位基线 + 战斗文本证据；GM 命令作为间接断言 |
| 时间推进 | 平台无虚拟时钟/时间加速 | 闭关、历练、Boss 等长周期不可真实等待 | **插件侧已补齐（`gm-test-time-and-rng-controls` 起）**：GM「时间快进 <秒> 确认」将枚举的到期类时间戳（user_cd/闭关/决斗切磋/双修/悬赏/贷款/悬赏放弃冷却/Boss·灵眼下次刷新/传承冷却与保护期）全库前移，冷却与长周期等待立即到期；按玩家粒度清零用 GM「清除全部冷却 [@玩家/ID] 确认」（忙碌/战斗/双修/悬赏/传承/历练路线休整一键归零）；「入口可达」冒烟与 GM 强制结算（触发历练/秘境结算）仍保留用于"立即结算"语义 |
| 结果归档 | 平台有运行记录但没有“导出目录包” | 结果需自行拉取并组织 | 本项目 `scripts/test_suite_ctl.py export` 本地生成 `results/<date>_<target>/` |
| GM 目标解析单数字参数 | 通用 `_resolve_target` 将剩余参数中「唯一数字」视为命令自身数值参数并回落到发送者，强制命令（`触发历练结算 900000002`）曾因此作用到错误目标（检查到 GM 自身，被 sect-master-chain-gm 用例暴露） | 无法通过纯数字单参数定位目标 | v3.9.1 起强制结算类（触发历练/秘境结算/师承推进/清除CD）单数字参数即视为目标 ID |
| 师承链进度推进 | 插件 GM `触发秘境结算`/`触发历练结算`（`core/gm_manager.py` `cmd_force_rift`/`cmd_force_adventure`）**v3.9.1 起**强制结算与正常完成流程一致追加 `sect_manager.advance_master_progress`（adventure_complete 必然推进；win_pve 受 PvE 遭遇概率限制），并新增 GM「师承推进」（`cmd_advance_master`，事件 战斗/历练/突破/捐献）确定性直推 | PvE 遭遇战为概率事件（`pve_combat_manager._should_trigger_combat` adventure low 30% / rift low 50-95%），真实结算的 win_pve 计数不保证递增 | `sect-master-chain-gm` 用例用「师承推进」确定性覆盖三阶段全链（win_pve×3→adventure_complete→breakthrough）；真实历练结算只断言 adventure_complete 阶段（与 PvE 胜负无关） |
| 悬赏冷却清理 | 放弃悬赏写 `system_config.bounty_abandon_cd_<uid>`（30 分钟 CD）；进行中悬赏存 `player_bounties`；既有 GM「清除CD」只清 `user_cd`，不覆盖这两处 | 仅靠原清除CD 无法归零悬赏状态，跨用例会因冷却/活跃残留互相污染 | 插件新增 GM「清除悬赏」（`core/gm_manager.py` `cmd_clear_bounty`，命令末尾追加「确认」），同时清活跃悬赏与放弃冷却；`sect-bounty-lifecycle`/`sect-bounty-split` 首尾用它清洗（依赖 `unify-sect-commands` 任务 2.5）；跨用例的基线残留另由用例 `pre_run_hook`（fixture）每轮前置复位兜底（v0.3.0） |
| 随机选择池（悬赏/任务） | 悬赏普通池（301-306）与宗门池（307/308）按难度加权随机出单，单轮无法断定具体条目；且**宗门专属悬赏与本宗成员不保证出现在悬赏令中**（仅当随机抽中 307/308 时才有『宗门悬赏』分区，bd `astrbot_plugin_monixiuxian2_2-80t`），宗门建设任务随机三选一 | 「宗门 悬赏」列表按 faction 确定性返回（境界 <7 见 easy/normal，qingyun 各难度仅一模板 → 307/308 必现）；宗门专属悬赏统一走宗门入口不依赖全局悬赏令；悬赏 target 用循环推进覆盖区间 + `deterministic: true`（seed 固定）；建设任务断言 `完成建设任务【.+】|获得贡献：\\+\\d+` 与 `--repeat 2` 稳定性证据 || `sect-content-filter` 改用确定性闸门：非成员 `接取悬赏 307/308` → 必现拒绝文本『该悬赏为宗门专属委托，仅面向本宗弟子发布』（sect 校验先于列表缓存校验）；普通断言编号区间（`[30[0-9]]`）；建设任务断言 `完成建设任务【.+】|获得贡献：\\+\\d+` 与 `--repeat 2` 稳定性证据 |
| 反向（不存在）断言 | `expect_not` 为尽力而为（若宿主并行写入其他回复，可能误判窗口内容） | 不能 100% 保证“窗口内确实无匹配” | 优先 `expect_not`（非成员列表不含 `青云剑冢`）；对关键“不可见”再用探索入口的拒绝文案作正向兑底；成员宗门悬赏必现性仍无法验证（bd 80t）；PvP `pvp-effect-unavoidable` 的“躲过了”反向证据因 unavoidable 是一次性消耗标记，窗口后半段可能合法闪避，故保留采样方式不转 `expect_not` |
| 秘境 ID 与 DB 配置漂移 | 秘境表由迁移脚本 `INSERT OR IGNORE` 播种（v31 新增青云剑冢=id 6），**仅改配置不重播种**；被配置移除的旧秘境（玄冰地宫 id4/上古遗迹 id5）仍留在库中 | 断言必须按测试库真实 rifts 表 ID 编写，且新增秘境需重载插件 | 用例对青云剑冢断言使用 `(ID:6)`（测试库 v31 迁移后实际值）；重载插件后再跑用例 |
| 功法赠予无通道 | 游戏无“赠予已学技能”指令，宗门绑定**功法**的不可赠予性无法直接覆盖 | 只能验证物品类绑定物 | 用宗门之宝青云镇山剑（配置 `treasure+sect_id` 标记，`core/storage_ring_manager.py:64` `is_sect_bound_item` 按配置判定）作代理：赠予被拒在持有与离宗后均成立；功法保留可用改由 `我的技能` 断言

## Unsupported（当前没有，列入平台增强建议）

| 能力 | 为什么需要 | 建议平台增强 |
|---|---|---|
| 结构化消息组件注入 | GM `@目标`、图片/文件/引用等路径无法覆盖 | `send` 步骤支持 `components` 数组（At/Image/Reply） |
| 直接 DB 断言 | 强断言需要核对库内落盘状态 | 提供 `GET /api/ops/db-query` 白名单查询或运行后 DB 快照 API |
| 时间加速/虚拟时钟 | 长周期玩法（闭关 1 分钟、Boss 冷却）不适合真实等待。**插件侧已补齐主链路**（`gm-test-time-and-rng-controls`：GM 时间快进/清除全部冷却）；平台增强仍保留给定时任务完整语义——字段前移不唤醒 `asyncio.sleep` 中的 Boss/灵眼循环（仅保证其下次醒来立即触发），要"快进即触发"仍需平台 tick 能力 | 支持 `run.time_offset` / `POST /api/ops/tick` 推进测试会话 |

## 已解决的平台侧问题

- `*.meta.json` 不再写入平台 `cases/` 目录：本项目 `sync-cases` 已改为只同步用例 JSON，并清理历史残留；平台 loader 侧也已过滤。
- 旧代码僵尸服务：平台已实现 `terminate()` 与实例重建逻辑，插件/平台代码改动后 Dashboard 重载即可生效。
- **run-all 共享固定 pin 的跨用例状态污染（隔离缺口，v0.3.0 已关闭）**：宗门用例需固定 GM/业务玩家身份（`GM_ADMINS` 等按 user_id 精确匹配），此前依赖外部 `--fixture` 编排每轮复位基线。v0.3.0 起宗门用例在 JSON 顶层声明 `pre_run_hook`（command 直接调 `scripts/test_suite_ctl.py fixture --profile sect --yes`，服务端每轮首步前执行，以 `WEBTEST_PLAYERS` 对齐本运行实际身份），基线复位内嵌用例、无需外部编排；`--fixture` CLI 参数与 fixture 命令保留兼容。需要全新生身份的用例改用 `isolate`/`fresh` 派生身份（注意派生身份失去按 user_id 精确匹配的特权）。
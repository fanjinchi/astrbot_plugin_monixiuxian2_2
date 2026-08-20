# Design: update-sect-functional-tests

## Context

`functional_tests/cases/sect/` 现有 12 条用例，其中 11 条的 `send` 步骤直接引用将被 `unify-sect-commands` 移除的旧指令（grep 实证：`#宗门列表`/`#创建宗门`/`#加入宗门`/`#退出宗门`/`#我的宗门`/`#宗门晋升`/`#师承任务`/`#宗门捐献`，以及 `sect-content-filter` 的 `#悬赏令`/`#接取悬赏`/`#秘境列表`/`#探索秘境` 断言）。平台能力约束见 `functional_tests/platform-gap-report.md`：平台 v0.2.0 起 `expect` 支持负向断言 `expect_not`（窗口内命中即失败）、用例级 `deterministic: true` + `seed` 重置全局随机种子（尽力而为可复现）、`expect/expect_not` 支持 `combine: true` 跨条拼接；悬赏/事件为随机池（确定性 + 采样兜底）；群聊需 `#` 前缀；GM `设置贡献`/`师承推进`/`触发历练结算` 已可用。随机性用例优先 `deterministic`，`--repeat` 采样降为统计兜底。

## Goals / Non-Goals

**Goals:**

- 存量 sect 域用例全量迁移到 `/宗门` 子命令，`--tag sect` 回归在变更落地后全绿。
- 新增用例覆盖 spec「宗门指令统一与新专属内容的功能测试覆盖」列出的全部验证点。
- 所有断言遵守平台 Supported 能力，受限点登记 gap 报告。

**Non-Goals:**

- 不改插件玩法代码；发现的玩法 Bug 用 `bd` 登记。
- 不为平台开发新能力（如 DB 直断、时间加速）——只登记与绕行。
- 不覆盖 `unify-sect-commands` 的单元测试（由其自身 tasks 负责）。

## Decisions

### 1. 用例组织：原文件改写 + 新文件按功能点拆分

存量 11 条在原 JSON 上改（保持 `name` 与文件名不变，避免同步与历史结果断链）。新增用例拆为独立文件，命名沿用 `sect-<功能点>` 惯例：

- `sect-command-entry.json`：导航帮助、未知子命令、缺参提示（私聊即可）
- `sect-bounty-lifecycle.json`：宗门悬赏查看/接取/进度/放弃全流程（成员）+ 无宗门玩家拒绝
- `sect-bounty-split.json`：双向分流——全局「接取悬赏 307/308」拒（提示走宗门入口）、「宗门 悬赏 接取 <全局编号>」拒；`sect-content-filter` 中对应旧断言改写后并入此文件
- `sect-shop.json`：列表/购买/贡献不足/职阶门槛/无宗门
- `sect-adventure-event-marker.json`：GM 触发历练结算 + repeat 采样

### 2. 秘境"不可见"的断言策略

平台不支持反向断言，无法验证"列表不含青云剑冢"。替代方案：非成员 `#探索秘境 6` 的入口拦截消息（"仅对本宗弟子开放"）作正向断言 + 成员侧 🏯 可见可进保留。gap 报告"反向断言"行补充秘境场景说明。备选"断言列表全文精确匹配"——否决，列表内容随播种/建设度漂移，脆弱。

### 3. 商店用例的资金与商品来源

购买资金用既有 GM「设置贡献」预置（`sect-gm-set-contribution` 已验证该路径），不扩展 fixture 脚本。商品依赖 `unify-sect-commands` 任务 3.2 给默认宗门配置的 `shop` 池；用例断言以最终实现的价格/文案为准，执行前需热重载使配置生效。贡献不足场景在 GM 置 0 贡献后购买断言拒绝文案。

### 4. 悬赏生命周期的确定性与状态清理

悬赏列表是随机池抽样，不保证 307/308 出现；但接取校验先于列表缓存（gap 报告已实证），故直接按编号 307（青云门专属）接取是确定性路径。307 的 `progress_tags` 含 `adventure_scout` 且 `min_target=2`，与巡山路线的 `bounty_tag=adventure_scout` 匹配，故「完成」路径可走 GM「触发历练结算」（已同步推悬赏进度并清内存休整冷却，`gm_manager.py:693-703`）循环 2-4 次确定性达成——生命周期用例覆盖完整闭环：接取 307 → 进度 → GM 推进度 → 完成。

**状态清理依赖新 GM「清除悬赏」**（由 `unify-sect-commands` 实施）：放弃悬赏写 `system_config.bounty_abandon_cd_<uid>`（30 分钟冷却），进行中悬赏存 `player_bounties` 表，现有「清除CD」只清 `user_cd` 忙碌状态，两者都不覆盖。用例在收尾与开场各加一步 GM「清除悬赏 … 确认」，解除用例间顺序耦合与 `--repeat` 阻塞。备选"批跑排序规避"——否决，顺序耦合脆弱；备选"fixture 删表"——不足以解决同一轮批跑内用例间污染，仅作起始状态兜底。

**校验顺序依赖**：分流拒绝断言（全局接宗门悬赏 → 分流提示）要求类型/归属校验先于冷却/活跃检查，否则带冷却时报冷却文案导致断言漂移——已在 `unify-sect-commands` design 决策 2 中明确为实现约束。

### 5. 宗门事件标记的确定性策略

宗门事件组以固定权重 15 追加进路线抽取池（`adventure_manager.py:50`）。用例声明 `deterministic: true` + `seed`（默认 42），每次 send 注入前重置全局随机种子，使抽池路径可复现（尽力而为——宿主其他异步活动可能消耗 RNG）；仍以 GM「触发历练结算」驱动结算。必要时以 `--repeat N`（建议 N≥10） + `_count_evidence` 统计「🏯 宗门际遇」出现次数 > 0 作为统计兜底；同运行内普通事件结算消息不含该标记作为对照（正向断言普通结算结构不变）。

### 6. 执行前置与顺序

用例编写与 `unify-sect-commands` 实施并行；执行必须在其实施完成、`sync-cases` 且插件热重载后。断言文案（拒绝提示、导航帮助文本）以实现最终版为准，实施完成后统一校对一轮再跑回归。

## Risks / Trade-offs

- [断言文案与最终实现漂移导致用例误报] → tasks 设"文案校对"独立任务，实施完成后先人工/自动核对再批跑。
- [悬赏放弃冷却与进行中悬赏污染后续用例] → 用例首尾用新 GM「清除悬赏」清理（由 `unify-sect-commands` 提供）；该 GM 未就绪前悬赏相关用例不得批跑。
- [采样断言（事件标记）偶发不命中造成 flaky] → 优先 `deterministic: true` + seed 确定性路径；回退到采样时 repeat 次数按权重 15 估算取足量（≥10），连续两次不命中才视为失败并查实现。

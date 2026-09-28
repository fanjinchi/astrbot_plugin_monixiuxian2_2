# Design — gm-time-skip-registry

## Context

现状的三份事实：
1. `_TIME_SKIP_RULES`（`core/gm_manager.py:68-122`）是 10 条 `(域标签, 参数化 UPDATE SQL)` 的手工元组，`:62-67` 注释自认设计出处（archive `2026-09-01-gm-test-time-and-rng-controls` design D2 显式枚举）并自带维护约束（「新增等待类冷却域时必须同步补充本清单与 GM 帮助文本」，与 AGENTS.md §2 :77 互为手抄）。
2. 消费方仅两处：`cmd_time_skip` 循环（:1209-1212，秒数按 `?` 计数填充，逐域 `rowcount` 进回复）与间接的 GM 帮助文案（:431-432 人工概述，无域枚举——帮助从未列出域清单，漂移面是「概述与清单语义脱节」而非文本副本）。
3. spec 已把枚举清单写成契约：`openspec/specs/gm-commands/spec.md`「GM 时间快进」需求「覆盖清单**至少包含**」10 项域——枚举是需求级保证，不能随机制一并删去。

字段归属：10 条 SQL 横跨 user_cd/players（player_handler 闭关、user_cd 忙碌）、combat_cooldowns（切磋决斗）、dual_cultivation、bounty_tasks + system_config 放弃冷却键（BountyManager）、bank_loans（BankManager）、boss/spirit_eye 刷新键（boss_manager/spirit_eye_manager）、impart_pk_cooldown / impart_snatch_protection（impart 域）。知识今天全部背井离乡。

## Goals / Non-Goals

**Goals:**
- 覆盖清单从「gm_manager 内手工元组 + 文档义务」反转为「字段属主模块声明 + 装配期汇总」：新增冷却域 = 在属主模块加一个常量并登记 provider，自动获得快进覆盖；**三层防漏**——既有域清单被 registry 最小清单断言 fail fast 钉住；「属主模块声明了 `TIME_SKIP_ENTRIES` 但漏登记 provider」由静态扫描测试钉住；「全新域模块压根没声明」仍靠 review 与 AGENTS.md §2 义务（与现状持平，但手抄面从三处减到一处）。
- `cmd_time_skip` 语义逐行保持：事务全有或全无（现为 :1208 的 `db.transaction()` CM，原手写 `BEGIN IMMEDIATE` 已收编）、逐域计数、回复格式、确认约定、秒数校验、sleep 边界声明。
- GM 帮助的时间快进条目列出实际覆盖域（生成自注册表），既有警示文案保持代码所有、逐字不变。
- spec 契约升级：枚举清单由「机制描述」转为「注册表 MUST 覆盖的保证」。

**Non-Goals:**
- **不拆分 GMManager 的 28 个 `cmd_*` 方法**（原发现 #6 的宽浅分发器部分）——已登记 bd 跟进 issue，属独立 change。
- 不覆盖 design D2 明确排除的域（丹药 buff、商店刷新、灵田、洞天/灵眼收取、双修请求过期等）——首版注册表与现状同域，扩展决策留给各域属主。
- 不改任何 SQL 语句文本（原样迁移，行为零变化；Boss/灵眼单条双键 UPDATE 按 D2a 拆为两条单键 UPDATE——SQL 文本本身由原双键 UPDATE 拆成两条单键 UPDATE，逐键文本不变）；不引入字段级 DSL/ORM 抽象。
- 不触碰 `cmd_clear_all_cooldowns` 步骤 3 内联的 `UPDATE dual_cultivation SET last_dual_time = 0`（test marker `tests/test_transaction_atomicity.py:1405`）——迁移后 dual 域快进 SQL 与该内联 UPDATE 分处两文件，属 `fix-two-stage-commit-atomicity` 归档 change 的既定边界，保持内联、不纳入本 change。
- 不触碰 `add-transaction-unit-of-work` 的事务 CM 本身（本 change 在其 CM 形态之上改循环数据源；若先实施则留下 rebase 提示，见 Risks）。

## Decisions

**D1 · 条目形态保持 `(域标签, 参数化 UPDATE SQL)`，不发明字段描述 DSL。**
SQL 已是 `table.column + WHERE 条件` 的精确编码（含 `system_config` TEXT 列的 CAST 守卫 :98-105 这类易错细节）；抽象成 `(table, column, where)` 描述符要再推导 SQL，反而把易错点藏进组装器。机制反转不等于条目形态反转——本 change 只改「清单长在哪、谁来汇总」。

**D2 · 声明形态：属主模块的模块级 `TIME_SKIP_ENTRIES` 常量 + provider 列表装配，而非 manager `__init__` 内 `register()` 调用。**
考虑过 `register(label, sql)` 运行时注册：在 composition-root 落地前，同一 manager 存在多处 ad-hoc 重建（见 `composition-root` change 的病灶清单），运行时会重复注册或要求幂等去重，且注册副作用藏在构造里不可静态检索。模块常量形态：声明与字段知识同文件（locality）、静态可 grep（review 可直接看到「该模块声明了快进覆盖」）、装配纯函数（`TimeSkipRegistry.from_providers([...])`）、测试可直接断言常量内容。代价：provider 列表本身是一处集中登记（新增全新域模块时要把模块加进列表）——但这是 fail fast 的落点之一，优于今天「忘改 SQL 清单 + 忘改帮助 + 忘改 AGENTS.md」三处漂移面。

**D2a · Boss/灵眼组合条目定案：拆条 + 同 label 聚合（2026-09-29 评审拍板，取代初稿「不得拆条」禁区）。**
初稿顾虑是拆条会把回复明细行数 10→11、破坏既有锚点；但按 label 聚合计数即可两全：`boss_next_spawn_time` → `managers/boss_manager.py`、`spirit_eye_next_spawn_time` → `managers/spirit_eye_manager.py`（各归写点属主），两条目**共享同一域标签**「Boss/灵眼下次刷新时间」，`cmd_time_skip` 按 label 聚合（同 label 多条 SQL 的 rowcount 相加输出一行）——回复明细行数仍为 10、「Boss/灵眼下次刷新时间：2 条」（1+1=2）与「共前移 11 条」等既有测试锚点全部保持。代价：循环从「逐 SQL 一行」改为「按 label 聚合」、注册表条目 10→11；收益：两键知识各归写点属主，D2「声明与字段知识同文件」不设例外。`impart` 两条同理按写点钉死：均落 `managers/impart_manager.py`（实际写点 `record_challenge_failure:255` / `record_snatch_protection:271`）。`user_cd.scheduled_time` 落 `core/busy_state.py`（写点属主是 `set_busy`/`clear`——该字段的唯一写者；且 busy_state 在 `core/__init__.py:4` 先于 gm_manager 导入，无半初始化风险），与修炼闭关无领域关系，不随 cultivation 字段捆绑。

**D3 · 注册表装配位置：gm_manager 构造时一次性汇总，实例随 GMManager 持有。**
零新增构造参数。**provider 列表只存模块名字符串，`from_providers` 内部惰性 import**——GMManager 构造时 core 包已完整初始化，import 顺序零风险；若在 registry 模块顶部直接 import 候选 managers 模块，则候选模块将来新增任何排在 gm_manager 之后的 core 依赖（pill/shop/skill/storage_ring，见 `core/__init__.py` 顺序）时会炸半初始化 ImportError（review Finding B 的 managers 侧同款）。与 `composition-root` 的注入惯例不冲突——provider 列表是声明式数据而非服务依赖；composition-root 落地后本机制仍成立，若届时改注入惯例，改动面仅一行（非「无需返工」，但返工成本可忽略）。

**D4 · GM 帮助自动化的边界：域列表生成，警示文案代码所有。**
`cmd_help` 时间快进条目（:431-432）拆为「代码持有警示句（不可逆/不唤醒睡眠任务/贷款逾期警告，逐字不变）+ 生成段（覆盖域：标签 joined）」。帮助场景契约（「GM 测试命令安全边界」之「帮助文本列出测试命令」）要求列出用法说明——生成段是加法，不触碰该场景断言。

**D5 · spec 采用 Modified Capability（不设 skip_specs）。**
「GM 时间快进」需求正文内嵌了被替换的机制（「明确枚举」），且枚举清单本身是需求级保证——两者都要在 delta 中处理：机制句改为注册表描述，枚举清单保留并升级为「注册表 MUST 覆盖以下最小清单」。其余需求（帮助/审计/清除全部冷却等）行为不受影响，不修改。

**D6 · 实施顺序：建议后于 `add-transaction-unit-of-work`（软依赖）。**
其 tasks 3.3 已把 `core/gm_manager.py:1208` 的手写 `BEGIN IMMEDIATE` 改为事务 CM（`add-transaction-unit-of-work`，2026-09-19 归档）——与本 change 的循环块同一区域。本 change 直接在 CM 形态上改数据源即可，无 rebase 负担。

## Risks / Trade-offs

- [注册表条目顺序与现状不同 → 时间快进回复中各域排列顺序变化，功能测试锚点失配] → `from_providers` 按 provider 列表顺序展开、各模块内按常量声明序，迁移时保持现状 10 条的原序（任务显式列出顺序；Boss/灵眼拆条后两同 label 条目相邻，顺序 boss→spirit_eye）；按 label 聚合计数保证明细行序 = 现状域序；补一条回复文本快照测试。
- [属主模块拆分后有人只加字段、忘加 `TIME_SKIP_ENTRIES`；或声明了常量、忘登记 provider] → 三层防漏（Goals）：最小清单断言钉既有域 fail fast；静态扫描测试遍历 core/managers/handlers 源码、凡含 `TIME_SKIP_ENTRIES =` 声明的模块必须 ∈ provider 列表（抓「声明了但漏登记」）；「全新域模块未声明」仍靠 review checklist 对新增时间戳字段 grep `TIME_SKIP_ENTRIES` + AGENTS.md §2 义务——残余风险与现状持平，但手抄面从三处减到一处。
- [`scripts/test_suite_ctl.py:1255` 注释引用 `_TIME_SKIP_RULES` 名称] → 该注释描述快进幽灵数据对「闭关开始时间」计数的影响，与机制无关；实施时改为指向注册表或泛化表述，语义不得失真。
- [与 `add-transaction-unit-of-work` 的顺序倒置] → tasks 0.1 要求核对其合入状态；若本 change 先落地，其 tasks 3.3 rebase 时以本 change 的循环为准（机制改动优先归并）。
- [帮助文本新增生成段导致 `修仙GM帮助` 输出变长，超出展示预期] → 生成段为一行 joined 标签（10 域约一行半），属加法；functional_tests 帮助相关用例重跑确认。

## Migration Plan

无部署/迁移步骤：纯代码重构 + spec delta + 文档，随插件重载生效；无数据库与配置变更。回滚 = revert 单个 commit（`_TIME_SKIP_RULES` 删除是可回滚的单点）。

## Open Questions

无（机制反转、条目形态、装配位置、spec 处理与实施顺序均已收敛）。

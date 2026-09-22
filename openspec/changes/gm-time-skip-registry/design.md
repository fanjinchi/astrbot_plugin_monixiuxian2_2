# Design — gm-time-skip-registry

## Context

现状的三份事实：
1. `_TIME_SKIP_RULES`（`core/gm_manager.py:68-122`）是 10 条 `(域标签, 参数化 UPDATE SQL)` 的手工元组，`:62-67` 注释自认设计出处（archive `2026-09-01-gm-test-time-and-rng-controls` design D2 显式枚举）并自带维护约束（「新增等待类冷却域时必须同步补充本清单与 GM 帮助文本」，与 AGENTS.md §2 :77 互为手抄）。
2. 消费方仅两处：`cmd_time_skip` 循环（:1200-1203，秒数按 `?` 计数填充，逐域 `rowcount` 进回复）与间接的 GM 帮助文案（:428-429 人工概述，无域枚举——帮助从未列出域清单，漂移面是「概述与清单语义脱节」而非文本副本）。
3. spec 已把枚举清单写成契约：`openspec/specs/gm-commands/spec.md`「GM 时间快进」需求「覆盖清单**至少包含**」10 项域——枚举是需求级保证，不能随机制一并删去。

字段归属：10 条 SQL 横跨 user_cd/players（player_handler 闭关、user_cd 忙碌）、combat_cooldowns（切磋决斗）、dual_cultivation、bounty_tasks + system_config 放弃冷却键（BountyManager）、bank_loans（BankManager）、boss/spirit_eye 刷新键（boss_manager/spirit_eye_manager）、impart_pk_cooldown / impart_snatch_protection（impart 域）。知识今天全部背井离乡。

## Goals / Non-Goals

**Goals:**
- 覆盖清单从「gm_manager 内手工元组 + 文档义务」反转为「字段属主模块声明 + 装配期汇总」：新增冷却域 = 在属主模块加一个常量，自动获得快进覆盖；忘记声明被 registry 测试钉住的最小清单断言 fail fast 捕获（而非冷却类测试隐性超时）。
- `cmd_time_skip` 语义逐行保持：事务全有或全无（现为 :1199 的 `db.transaction()` CM，原手写 `BEGIN IMMEDIATE` 已收编）、逐域计数、回复格式、确认约定、秒数校验、sleep 边界声明。
- GM 帮助的时间快进条目列出实际覆盖域（生成自注册表），既有警示文案保持代码所有、逐字不变。
- spec 契约升级：枚举清单由「机制描述」转为「注册表 MUST 覆盖的保证」。

**Non-Goals:**
- **不拆分 GMManager 的 28 个 `cmd_*` 方法**（原发现 #6 的宽浅分发器部分）——已登记 bd 跟进 issue，属独立 change。
- 不覆盖 design D2 明确排除的域（丹药 buff、商店刷新、灵田、洞天/灵眼收取、双修请求过期等）——首版注册表与现状同域，扩展决策留给各域属主。
- 不改任何 SQL 语句文本（原样迁移，行为零变化）；不引入字段级 DSL/ORM 抽象。
- 不触碰 `add-transaction-unit-of-work` 的事务 CM 本身（本 change 在其 CM 形态之上改循环数据源；若先实施则留下 rebase 提示，见 Risks）。

## Decisions

**D1 · 条目形态保持 `(域标签, 参数化 UPDATE SQL)`，不发明字段描述 DSL。**
SQL 已是 `table.column + WHERE 条件` 的精确编码（含 `system_config` TEXT 列的 CAST 守卫 :98-105 这类易错细节）；抽象成 `(table, column, where)` 描述符要再推导 SQL，反而把易错点藏进组装器。机制反转不等于条目形态反转——本 change 只改「清单长在哪、谁来汇总」。

**D2 · 声明形态：属主模块的模块级 `TIME_SKIP_ENTRIES` 常量 + provider 列表装配，而非 manager `__init__` 内 `register()` 调用。**
考虑过 `register(label, sql)` 运行时注册：在 composition-root 落地前，同一 manager 存在多处 ad-hoc 重建（见 `composition-root` change 的病灶清单），运行时会重复注册或要求幂等去重，且注册副作用藏在构造里不可静态检索。模块常量形态：声明与字段知识同文件（locality）、静态可 grep（review 可直接看到「该模块声明了快进覆盖」）、装配纯函数（`TimeSkipRegistry.from_providers([...])`）、测试可直接断言常量内容。代价：provider 列表本身是一处集中登记（新增全新域模块时要把模块加进列表）——但这正是 fail fast 的落点，优于今天「忘改 SQL 清单 + 忘改帮助 + 忘改 AGENTS.md」三处漂移面。

**D3 · 注册表装配位置：gm_manager 构造时（或装配段）一次性汇总，实例随 GMManager 持有。**
零新增构造参数（装配器 import 属主模块读常量），与 `composition-root` 的注入惯例不冲突——provider 列表是声明式数据而非服务依赖；composition-root 落地后无需返工。

**D4 · GM 帮助自动化的边界：域列表生成，警示文案代码所有。**
`cmd_help` 时间快进条目（:428-429）拆为「代码持有警示句（不可逆/不唤醒睡眠任务/贷款逾期警告，逐字不变）+ 生成段（覆盖域：标签 joined）」。帮助场景契约（「GM 测试命令安全边界」之「帮助文本列出测试命令」）要求列出用法说明——生成段是加法，不触碰该场景断言。

**D5 · spec 采用 Modified Capability（不设 skip_specs）。**
「GM 时间快进」需求正文内嵌了被替换的机制（「明确枚举」），且枚举清单本身是需求级保证——两者都要在 delta 中处理：机制句改为注册表描述，枚举清单保留并升级为「注册表 MUST 覆盖以下最小清单」。其余需求（帮助/审计/清除全部冷却等）行为不受影响，不修改。

**D6 · 实施顺序：建议后于 `add-transaction-unit-of-work`（软依赖）。**
其 tasks 3.3 已把 `core/gm_manager.py:1199` 的手写 `BEGIN IMMEDIATE` 改为事务 CM（`add-transaction-unit-of-work`，2026-09-19 归档）——与本 change 的循环块同一区域。本 change 直接在 CM 形态上改数据源即可，无 rebase 负担。

## Risks / Trade-offs

- [注册表条目顺序与现状不同 → 时间快进回复中各域排列顺序变化，功能测试锚点失配] → `from_providers` 按 provider 列表顺序展开、各模块内按常量声明序，迁移时保持现状 10 条的原序（任务显式列出顺序）；补一条回复文本快照测试。
- [属主模块拆分后有人只加字段、忘加 `TIME_SKIP_ENTRIES`] → registry 测试钉住 spec 最小清单（fail fast）；AGENTS.md §2 改写为「声明常量」指引；review checklist 对新增时间戳字段 grep `TIME_SKIP_ENTRIES`。残余风险（全新域模块未入 provider 列表）在装配器集中一处，远优于今天三处手抄。
- [`scripts/test_suite_ctl.py:1255` 注释引用 `_TIME_SKIP_RULES` 名称] → 该注释描述快进幽灵数据对「闭关开始时间」计数的影响，与机制无关；实施时改为指向注册表或泛化表述，语义不得失真。
- [与 `add-transaction-unit-of-work` 的顺序倒置] → tasks 0.1 要求核对其合入状态；若本 change 先落地，其 tasks 3.3 rebase 时以本 change 的循环为准（机制改动优先归并）。
- [帮助文本新增生成段导致 `修仙GM帮助` 输出变长，超出展示预期] → 生成段为一行 joined 标签（10 域约一行半），属加法；functional_tests 帮助相关用例重跑确认。

## Migration Plan

无部署/迁移步骤：纯代码重构 + spec delta + 文档，随插件重载生效；无数据库与配置变更。回滚 = revert 单个 commit（`_TIME_SKIP_RULES` 删除是可回滚的单点）。

## Open Questions

无（机制反转、条目形态、装配位置、spec 处理与实施顺序均已收敛）。

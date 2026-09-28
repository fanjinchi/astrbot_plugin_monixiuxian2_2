# Tasks — gm-time-skip-registry

## 0. 前置检查

- [ ] 0.1 核实在飞变更状态并重新锚定行号：`add-transaction-unit-of-work`（其 tasks 3.3 改 `core/gm_manager.py:1208` 时间快进块为事务 CM——**建议其先合入**，本 change 直接落在 CM 形态上）、`busy-state-owner`（触碰 `:915-919`/`:1255-1260` 清除路径，与本 change 区域不相交）；确认 `_TIME_SKIP_RULES`（:68-122）、`cmd_help`（:384-440）、`cmd_time_skip`（:1179-1222）行号仍有效
- [ ] 0.2 grep 基线：`_TIME_SKIP_RULES` 全部引用（运行时代码/文档/脚本/测试）与本 tasks 清单一致——已知引用点：`AGENTS.md:77`、`design_docs/api-overview.md:107`、`scripts/test_suite_ctl.py:1255`（注释）、`tests/test_transaction_atomicity.py:1405`（测试 marker 注释引用其 SQL 文本与行号 :87，迁移后名称+行号全部失效，列入 2.3 收尾同步）

## 1. 注册表与迁移（core + 属主模块）

- [ ] 1.1 新增 `core/time_skip_registry.py`：`TimeSkipRegistry`（不可变元组包装，`from_providers(provider_modules)` 按模块顺序汇总各模块的 `TIME_SKIP_ENTRIES` 常量，`entries() -> tuple[tuple[str, str], ...]`）；英文 Google 风格 docstring 写明「声明即覆盖」不变量与 SQL 参数约定（`?` 以前移秒数按个数填充）
- [ ] 1.2 迁移 11 条 SQL（**逐键文本原样**，顺序保持现状；**Boss/灵眼单条双键 UPDATE 按 design D2a 拆为两条单键 UPDATE**，条目 10→11、回复行数不变）——归属钉死，不留「A 或 B」：① `user_cd.scheduled_time` → `core/busy_state.py`（busy_state 是 user_cd 领域属主：`set_busy`/`clear` 是常态写路径，GM force-settle 直写是既有例外见 `busy_state.py:71-74`；busy_state 在 `core/__init__.py:4` 先于 gm_manager 导入，无半初始化风险；与修炼闭关无领域关系，不随 cultivation 字段捆绑）；② `players.cultivation_start_time` → `core/cultivation_manager.py`；③ `combat_cooldowns` → **`managers/combat_manager.py`**（钉死——写点在 `handlers/combat_handlers.py:60-71`，被末尾分层约束排除；按域归属判据落决斗/切磋域 manager CombatEngine 所在，`pve_combat_manager.py` 是秘境战斗与决斗/切磋无关、非候选；判据同 D2a ⑦⑧：写点在别处、域归属到 manager）；④ `dual_cultivation` → `managers/dual_cultivation_manager.py`；⑤ `bounty_tasks` + `system_config bounty_abandon_cd_%` → `managers/bounty_manager.py`；⑥ `bank_loans` → `managers/bank_manager.py`；⑦ `boss_next_spawn_time` → `managers/boss_manager.py`、⑧ `spirit_eye_next_spawn_time` → `managers/spirit_eye_manager.py`（⑦⑧共享域标签「Boss/灵眼下次刷新时间」，⑦在⑧前相邻展开；两键实际写点在 main.py 定时任务，此处按域属主归位，见 design D2a）；⑨ `impart_pk_cooldown.failed_at` 与 ⑩ `impart_snatch_protection.snatched_at` → **`managers/impart_manager.py`**（钉死——实际写点 `record_challenge_failure:255` / `record_snatch_protection:271` 都在该模块；`impart_pk_manager.py` 不在写点链上，非候选）；**不得落 `handlers/` 任何模块**——core 不得反向依赖 handlers 层（分层方向约束；D3 惰性 import 已定案后无 import 链风险，但该归属仍违反分层）；每条注释保留原「只动到期判定时间戳」原则
- [ ] 1.3 删 `core/gm_manager.py` 的 `_TIME_SKIP_RULES`（:62-122 含注释）与 `:1209` 的循环数据源引用；`GMManager.__init__` 构造注册表（`from_providers([...])`）；**provider 列表集中声明于 `time_skip_registry.py` 顶部、只存模块名字符串并注释「新增冷却域 = 属主模块加常量 + 此处登记模块」，实际 import 在 `from_providers` 内部惰性进行**（design D3：GMManager 构造时 core 包已完整初始化，零顺序风险）

## 2. 消费方改造（语义逐行保持）

- [ ] 2.1 `cmd_time_skip`（:1179-1222）：循环改 `for label, sql in self._time_skip.entries():`；**按 label 聚合计数**——同 label 多条 SQL（Boss/灵眼两条）各自执行、rowcount 相加后按 label 首次出现序各输出一行明细（明细行数 = 10 不变；「Boss/灵眼下次刷新时间：2 条」= 1+1、「共前移 11 条」= 全 label 合计，既有锚点保持）；事务边界（现为 :1208 的 `db.transaction()` CM——`add-transaction-unit-of-work` 已收编原手写 `BEGIN IMMEDIATE`/commit/rollback，全有或全无语义不变）、`params = (seconds,) * sql.count("?")`、回复格式（「✅ 时间已快进 N 秒（共前移 M 条记录）」+ 域计数明细 + 警示尾句）**逐字不变**
- [ ] 2.2 `cmd_help`（:384-440）：时间快进条目（:431-432）保持既有警示文案逐字不变，追加生成段「覆盖域：<标签 joined>」（来源注册表 `entries()`）；**注意 `cmd_help` 字面量当前是普通字符串拼接（非 f-string）且无 `{`，追加生成段需转 f-string 或继续拼接（f-string 化安全）**；docstring 注明生成段与代码持有段的边界
- [ ] 2.3 收尾 grep：运行时代码 `_TIME_SKIP_RULES` 零命中；`time_skip_registry` 注册表为唯一覆盖清单来源；`tests/test_transaction_atomicity.py:1405` marker 注释同步（名称与行号 :87 均已失效，改指注册表条目或泛化表述，保持「与 marker SQL 只差运算符」的语义说明）

## 3. 测试

- [ ] 3.1 注册表装配测试：provider 汇总顺序 = 拆条后 11 条原序（Boss/灵眼两同 label 条目相邻、顺序 boss→spirit_eye，总体保持现状 10 条域序）；结构断言只钉**条目数 = 11** 且 **label 集合 = 10 个域标签**；**不内联第二份 SQL 文本**（生产/测试双份 SQL 是文本级自证陷阱，改 WHERE 要双改且测不出语义）——迁移正确性由既有行为测试网保障：`tests/test_gm_manager.py:978-1160`（`_seed_time_skip_domains` + `test_skip_shifts_all_domains`：逐字段断言 10 域前移语义 + 全部 10 条回复片段 + 「共前移 11 条」，本 change 的主力回归网，必须原样全绿）+ 3.3 快照测试
- [ ] 3.2 契约钉住测试（三层防漏，design Goals）：① **最小清单**——测试内联 **10 域 field→label 映射**（field 清单抄自 spec 保证枚举：`user_cd.scheduled_time` 等 10 项；label 为注册表显示文案），断言注册表 label 集合 == 映射值集——field（spec 契约面）与 label（实现输出面）的对应经此映射显式搭桥，漏域/错配即 fail fast（替代 AGENTS.md §2 的人工义务；若只内联 label 清单则 spec 与测试仍是两处手抄，映射表才真正证明对应关系）；② **登记完整性静态扫描**——遍历 core/managers/handlers 源码，凡含 `TIME_SKIP_ENTRIES =` 声明的模块必须 ∈ provider 列表（抓「声明了但漏登记」）；③ 已知残余：「全新域模块未声明」只能靠 review（与现状持平）——不在测试承诺范围，避免「测试会钉住一切漏登记」的误导表述
- [ ] 3.3 `cmd_time_skip` 行为测试：逐域计数与回复格式快照（与改造前一致）；`cmd_help` 含时间快进用法行 + 全部域标签；无确认/非法秒数分支不变
- [ ] 3.4 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过

## 4. Spec delta 与文档

- [ ] 4.1 本 change 的 `specs/gm-commands/spec.md` delta（## MODIFIED Requirements ·「GM 时间快进」）：机制句「明确枚举」改为「字段属主声明 `TIME_SKIP_ENTRIES`、注册表装配覆盖」；枚举清单保留并改写为「注册表 MUST 至少覆盖以下清单」（保证语义）；新增场景「新冷却域自动覆盖」；实施核对 `openspec validate` 与主 spec 的 apply 语义
- [ ] 4.2 `AGENTS.md:77` 改写：人工义务（「必须同步补充 _TIME_SKIP_RULES 与 GM 帮助文本」）改为「在字段属主模块声明 `TIME_SKIP_ENTRIES` 常量并登记注册表 provider——登记后自动被时间快进覆盖与 GM 帮助列出。既有域清单由注册表最小清单测试钉住；声明了常量但漏登记 provider 由静态扫描测试钉住；全新域未声明仍靠 review」
- [ ] 4.3 `design_docs/api-overview.md:107`「按 `_TIME_SKIP_RULES` 枚举」改指注册表（`core/time_skip_registry.py`）；`scripts/test_suite_ctl.py:1255` 注释核对（名称改注册表或泛化，语义保持）

## 5. 验证与收尾

- [ ] 5.1 functional_tests：点名重跑两个直接锚时间快进输出的用例——`functional_tests/cases/gm/gm-time-tools.json`、`functional_tests/cases/player/breakthrough-fail-pity.json`——回复域计数与帮助文本锚点全过；含时间快进的其余冷却类用例按 tag 回归
- [ ] 5.2 按 AGENTS.md §7 版本 checklist 评估（纯工程重构无玩法变化，通常无需升版本号）
- [ ] 5.3 `openspec validate --changes gm-time-skip-registry` 通过；本地 conventional commit（不 push）

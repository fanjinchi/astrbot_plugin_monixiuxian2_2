# Design — unify-combat-power-formula

## Context

战力公式以逐字相同的内联表达式存在于两处：`managers/ranking_manager.py:125-132`（排行榜，传 `pill_multipliers=None`）与 `handlers/player_handler.py:187-194`（玩家信息面板，传 `pill_multipliers`）。两处的输入都来自 `Player.get_total_attributes(equipped_items, pill_multipliers)`（`models.py:258-347`，返回键 `damage/agility/speed/hp/armor_value/block_armor_value/exp_multiplier`），差异仅是第二参数——这正是「是否含临时丹药」策略的全部形态，无需额外布尔参数。注意两处调用点在求和之外都还复用 `total_attrs`（排行 :133/:144 展示 `attrs["damage"]` 等；面板 :260-264 展示四主属性），重构只替换求和表达式，不删该语句。

`openspec/specs/attribute-numerics/spec.md:84-91` 已定义战力行为的契约（四主属性 + 装备/功法，MUST NOT 用旧公式）；本变更为纯重构，不触碰该需求，故 `skip_specs: true`。

## Goals / Non-Goals

**Goals:**
- 公式实现收敛为 `Player` 上的单一深方法，行为与现状逐位一致（含 `int()` 转换与 `//2` 取整）。
- 排行榜与面板两个调用点各缩为一行；「是否含临时丹药」由调用方传入的 `pill_multipliers`（实参或 `None`）表达，保持现状语义。
- 文档单一事实源：`design_docs` 记公式文本，`AGENTS.md` 只留指针，`README` 历史 changelog 行加注记（不改写历史）。

**Non-Goals:**
- 不改变战力数值、排行顺序、面板显示的任何行为（用户已确认纯重构）。
- 不处理 `player_handler.py:109,117` 创角文案遗留的「精神力」展示文本（旧五维文案，属内容清理，另立 issue）。
- 不引入 CONTEXT.md / ADR（本变更未新增需要登记的领域概念名——`combat_power` 是既有概念 `战力` 的代码符号，非新造概念）。

## Decisions

**D1 · 落点：`Player.combat_power` 方法（models.py），而非 ranking_manager 权威或独立自由函数。**
数据模型 `Player` 是所有调用方（handlers、managers、tests）的共同依赖，方法紧挨 `get_total_attributes` 形成自然的 locality；manager 权威是「谁第一个写它」的历史遗留（`api-overview.md:91` 已把该历史写成事实，本次一并纠正）。自由函数次之——战力是「玩家的派生属性」，方法形态更贴领域语言。深度收益：interface 为两个参数 + 一行调用，实现吸收五元求和与取整细节。

**D2 · 签名 `combat_power(equipped_items, pill_multipliers=None) -> int`，不引入 `include_temporary: bool`。**
「临时丹药策略」现状就是第二参数实参形态；布尔旗标会要求函数内部再去取倍率，反而把知识从调用方藏进实现，违背 locality。保持透传是对现状的忠实抽象。Google 风格英文 docstring（含格挡护甲不计入的说明，移植 `models.py:332-345` 既有注释语义）。

**D3 · 文档所有权：AGENTS.md §8 改为指针式，不内联公式。**
`design_docs/current-design-report.md` 已是三处正确记载中的主文档；AGENTS.md 内联公式是第四副本，正是漂移来源。指针文本大意：「战力公式单一实现在 `Player.combat_power`（models.py）；设计权威与公式文本见 `design_docs/current-design-report.md`；改公式须同步 design_docs（§14）」。

**D4 · 测试落在 `tests/test_models.py`，钉公式而非钉调用方。**
全仓当前无任何战力数值断言。测试构造固定属性 `Player`（`@dataclass` 全默认字段，直接 kwargs 构造），断言：四主属性之和 + `armor_value//2` 取整；`pill_multipliers` 分支（如 damage×2 时结果变化）；`block_armor_value` 不计入。导入复用 `tests/test_models.py` 既有的 `load_package_module("models.py", ...)` shim，无新增 shim。

## Risks / Trade-offs

- [调用点改造的回归风险（排行/面板数值变化）] → 纯机械替换：两处调用点的 `total_attrs` 语句都保留（排行 :133/:144 与面板 :260-264 展示仍依赖它），仅求和表达式替换为方法调用；实施后以面板/排行文本快照比对验证，且比对须覆盖**排行顺序**（排序键 `x[1]`，含并列与排序稳定性），不只是显示数值。
- [有人"顺手清理"调用点残留的 `total_attrs` 语句] → tasks 中显式标注两处展示依赖（排行 :144、面板 :260-264），review checklist 核对。
- [`player_handler.py` 面板路径中 `equipped_items` 变量的来源与异常分支] → 实施时核对该处 `equipped_items` 获取逻辑（含 None 兜底）保持原样，方法只接收同一实参；`equipped_items=None` 时新方法与现状 `get_total_attributes` 一样报错，parity 保留，不新增兜底。
- [design_docs 行引用因本次编辑再漂移] → `current-design-report.md` 活基线本就要求随改随更（§14），接受。
- [玩家信息面板传的 `pill_multipliers` 与排行榜的语义差异未来被误改平] → docstring 明确两参数语义；单测钉住两个分支。

## Migration Plan

无部署/迁移步骤：纯代码重构 + 文档 + 测试，随插件重载生效；无数据库与配置变更。回滚 = revert 单个 commit。

## Open Questions

无（设计树已在 grilling 中收敛：行为不变、指针式文档、Player 方法落点、补单测）。

# Design — narrative-contract-module

## Context

架构评审（data/config/render 层）确认病灶：

**契约解析多份实现。** `extract_template_vars`（`utils/narrative_text.py:111-124`，`string.Formatter`）是运行时唯一真值；`scripts/sync_copy_variants_to_config.py:141-143` 的 `_template_vars` regex（`\{(\w+)`）只取 `\w+` 前缀——对 `{next_bonus:.0%}` 得 `next_bonus`（与 Formatter 一致， lucky），但对 `{{literal}}` 转义会**多报**一个变量、对 `{player.name}` 取根 `player` 是 regex 巧合而非语义；同文件 `:126` 的 `_default_scene_vars` 里还有一份同款内联 regex（第四处）；`lint_narrative.py:118` 的 `_WHITELIST_VAR_RE`（`\{([a-zA-Z_0-9]+)(?::[^}]*)?\}`）再算一份。多份对当前稿子的判定恰好一致（稿子只用 `{var}` 与 `{var:spec}`；257 个叶子条目实测零差异），所以 bug 是潜伏的：任一稿子引入转义/嵌套即出现「闸门过、加载拒」的双标。此外 `config_manager.py:23-28` 私有 import（`_NARRATIVE_ROUTES`、`_iter_scene_entries`）使 `narrative_text` 的私有改名成为跨模块破坏面；`narrative_text` 本身被 4 处 shim 按文件路径加载（`managers/combat_manager.py:43-45`、`managers/rift_manager.py:77`、`managers/adventure_manager.py:69`、`core/breakthrough_fortune.py:26`），新增任何裸相对 import 都会同时破坏这 4 条 standalone 路径。

**config 生成物身份未声明。** `config/narrative_config.json`（38 KB 已入库，tmp+replace 写入）由同步脚本生成，但文件内无任何标注，运营/新开发者无法从文件本身得知内容真源与手改政策。

**排除掉的假病灶（评审实测纠正）：** 「文案三拷贝漂移」不成立。实测 `DEFAULT_NARRATIVE_CONFIG` 与 `config/narrative_config.json` 在 43/55 场景上形状与内容不同（defaults 是单条「内嵌最小默认」兜底串，config 是全量分桶/双槽变体池；spec「分桶池合并取用」/「文学描述行可选」等场景明确钉死回退目标是**最小**默认）。二者语义角色不同、不是副本，不存在可消除的重复；且 `render_narrative` 的内嵌默认回退路径（`narrative_text.py:321-331`）只按普通池处理 default_value，若把 defaults 改成 config 快照（含双槽 dict），缺失场景兜底会丢 panel 机械信息——真这么做反而是 spec 违约。故 defaults 维持手维护不动（Non-Goal）。

注意 `NARRATIVE_SCENE_VARS`（渲染点声明变量集）是**代码所有**的契约声明（spec「模板插值变量契约校验」的锚点），不是文案——它留在 `data/narrative_defaults/` 包中不动，contract 模块只做消费。

## Goals / Non-Goals

**Goals:**
- 契约解析/校验/池迭代单源在 `utils/narrative_contract.py`，公共 API 三五个符号；运行时（config_manager 加载校验）、同步脚本、未来 lint 对齐共用一份实现。
- 三处既有消费点的**外部行为**逐位不变：加载校验的日志文案（含 `[配置]`/`[内嵌默认]` 前缀与 warning/error 级别）与回退动作、渲染回退链、同步闸门的写入/跳过/失败语义（`_default_scene_vars` 输出逐位不变，⊇ 放行判定不退化）。
- config 生成物身份显式化：`_meta` 段声明 generated_by 与手改政策（同步域 FORBIDDEN / 非同步域保留现值），可被 `config_manager` 与脚本安全忽略。
- 全部稿子零改动（本变更不动 design_docs 任何内容行）；`data/narrative_defaults/*.py` 内容零改动。

**Non-Goals:**
- **不再生/重排 `data/narrative_defaults/*.py`。** 评审实测 defaults 与 config 在 43/55 场景形状/内容不同——defaults 是「内嵌最小默认」兜底（spec 多处钉死「回退内嵌**最小**默认文案」），config 是全量可调池，二者语义不同源、非拷贝；sync 脚本不负责再生 defaults，该层继续手维护，由「内嵌默认全量符合契约」测试（`tests/test_narrative_config.py`）与 lint/导入双闸门间接约束。曾考虑 `--emit-defaults` 从 config 池冻结快照，因上述语义差异与双槽默认回退路径（`render_narrative:321-331` 不处理双槽 default_value，会丢 panel 机械信息）否决。
- 不合并 `lint_narrative.py` 的白名单 regex（design_docs 侧独立工具，合并需 design_docs 反向依赖插件包——登记 bd 跟进，见 Risks）。
- 不改 `render_narrative` 的回退链语义（config→内嵌默认→"" 的三级顺序、双槽短路先于默认回退等均已由 spec 场景钉住）。
- 不动 `NARRATIVE_SCENE_VARS` 的位置与内容（代码所有的声明层）。
- 不引入 ADR/CONTEXT.md（`narrative_contract` 是既有契约概念的代码符号，非新领域概念）。

## Decisions

**D1 · 落点：新建 `utils/narrative_contract.py`，而非把校验下沉进 `narrative_text.py` 或上提进 `config_manager`。**
`narrative_text` 是渲染层（热路径，被战斗每回合调用），校验是加载/同步期的离线关注点——两者生命周期不同，合一会让渲染模块背负离线校验的全部形态分支（深模块变胖接口）。`config_manager` 是插件包内类，脚本（无 AstrBot 环境）按路径加载它成本极高，故契约必须住在「standalone 可加载」的 utils 层。`utils/` 已有 standalone 双路径先例（`narrative_text.py:47-71`），contract 沿用同款 trick，脚本与测试 shim 零新机制。

**D2 · API 面：`used_vars` / `validate_scene` / `iter_scene_entries` / 两个常量，五个公共符号；`extract_template_vars` 保留为薄包装。**
`extract_template_vars` 被 `config_manager`、若干测试 import，保留名字变包装避免连锁 diff；新代码一律用 `used_vars`。`validate_scene(section, scene, value, declared, *, source)` 吸收 `_check_narrative_scene` 的全部分支（双槽非法形态整场景拒绝、未知桶键仅告警、route 标注合法性、逐条目变量子集校验），返回 `(ok, diagnostics)`，每条 diagnostic 为 `(severity, message)` 且 message 已含 `[{source}]` 插值——**校验判定与处置动作分离，但日志逐字可复现**：现状 config_manager.py:606-657 的日志混合 warning（桶键/route）与 error（契约违例）且全部内嵌 `[配置]`/`[内嵌默认]` 前缀，若 diagnostics 只带裸字符串则调用方无法复现级别与文案；由 contract 生成最终文案（纯函数、好测试），config_manager 只做「按 severity 写日志 + 回退默认」两个动作，locality 不丢。`source` 为 keyword-only 参数。

**D3 · 解析器真值 = `string.Formatter`；regex 镜像全删（含 `:126` 第四份），不做「兼容 regex 行为」的过渡层。**
当前稿子集合下两实现逐位一致（257 叶子条目实测零差异：全池条目只用 `{var}`/`{var:spec}`），无过渡兼容负担。`{var:spec}` 由 Formatter 原生支持（`lint_narrative.py` 注释 :117 确认稿子存在该用法），regex 版本只是前缀巧合。统一后 `{{` 转义按 Python 格式串语义处理，与渲染时 `format_map` 真值同源——**校验器与渲染器共用同一套语法理解**，这是本变更的核心深度收益。唯一行为差：Formatter 对畸形花括号抛 `ValueError` 而 regex 静默——同步脚本两处调用点（:248/:318）包 try/except，按「契约不满足」跳过场景（与加载校验对同模板的处置一致）。`_default_scene_vars`（:117-127）同样改用 `used_vars`，但**故意不包 try/except**：畸形内嵌默认是开发期错误，由 `tests/test_narrative_config.py:206-220` 既有契约测试在 CI 拦截（中断即红）——中断导入优于静默产出错误默认（评审补审钉死）；并**删除 `isinstance(value, str)` 门**，改 `iter_scene_entries` 全叶子遍历 + `used_vars` 并集——今日 55 个 default 全 str、输出逐位不变，dict 形态 default 未来不再从 default_vars 静默消失（三轮评审采纳）。

**D4 · config JSON 标 `_meta`，但不改变 reconcile 语义。**
同步脚本现状是「CSV 有的场景写池、CSV 没有的场景保留 JSON 原值」——非 CSV 场景（legacy_encounter 等当年外部化 dump 落入的键）仍是 config 的内容。`_meta.hand_edit` 政策据此分两档写清：**同步域场景以 CSV 为准、手改 FORBIDDEN（要改走 design_docs 流程，§15）；非同步域场景手改保留现值**。这与 spec「改文案不改代码」场景（spec.md:30-33）不冲突且保持其有效性：非同步域场景手改 config 仍是运营路径，重载后生效；同步域场景自迁移期起已由 §15 CSV→sync 流程取代直改。JSON 无注释语法，`_meta` 为顶层字典段；`config_manager` 按 section 名读取、校验只遍历 `NARRATIVE_SCENE_VARS` 声明域，多余顶层键零影响（实施时以一条加载日志验证）；脚本读写整个 dict，`_meta` 自然 round-trip；另 **sync 脚本写盘时 `cfg.setdefault("_meta", {...})` 幂等注入**（常量定义在 sync 脚本内）——覆盖 ConfigManager materialize 新生成文件（config_manager.py:315-327，不带 _meta）与手工删除两种缺失场景，否则「生成物身份显式化」在 materialize 路径失效（三轮评审补）。spec prose 补一句流程指向（tasks 5.2），不动任何 SHALL/Scenario 断言。

**D5 · 测试策略：钉解析器边界 + 校验全形态 + 消费点回归，不钉调用点的重复实现。**
contract 单测覆盖：`{{}}` 转义不产生变量、`{var:spec}` 提取根名、`{player.name}`/`{x[0]}` 根提取、畸形花括号抛 `ValueError`；`validate_scene` 全形态真假例（双槽非法形态、未知桶键仅告警、route 越界、panel 越界变量定位 `[panel]#0`），并断言 diagnostic 文案与 config_manager 现状日志逐字一致（含 `[source]` 与级别）；`iter_scene_entries` 分桶/扁平两形态 location 标记。`tests/test_sync_copy_variants_admission.py` 必须零改动通过——它驱动真实的 `_default_scene_vars()`/`_apply_short_text`，是 `:126` regex 迁移后「⊇ 放行语义逐位不变」的机械锚。

**D6 · narrative_text 引入 contract 必须走双路径回退。**
`narrative_text.py` 被 4 处 shim 按文件路径加载（见 Context），其现有 `from ..data.narrative_defaults import ...` 就有 try/except 回退（:47-71）。`from .narrative_contract import ...` 必须照抄同一模式：包内相对导入失败时按路径加载 contract 模块。contract 本身不 import astrbot/logger（纯函数），standalone 加载零环境负担；`data/narrative_defaults/` 的加载路径与手维护性质完全不变。

## Risks / Trade-offs

- [regex→Formatter 的统一在边缘语法上「改」了闸门判定（`{{` 转义不再误报、畸形花括号从静默变抛错）] → 这是对潜伏 bug 的修复而非回归；257 叶子条目实测零差异；tasks 中要求实施时跑一次全池对比（新旧解析器对 config + defaults 全部叶子条目的输出集合 diff 为空）作为机械验证，结果贴进 PR 描述。
- [sync 脚本 `used_vars` 抛 `ValueError` 中断导入] → :248/:318 两处包 try/except 按契约不满足跳过场景，与加载校验处置一致；`tests/test_sync_copy_variants_admission.py` 的现有用例（合法模板）零改动通过即证明未误伤。
- [`config_manager` 校验从「私有 import」改为「公共 API」后，有人绕过 contract 直接手写校验] → contract 的 `validate_scene` 是唯一做形态分支的地方，review checklist 核对 config_manager 不再出现 `_check` 私有逻辑残留。
- [`lint_narrative.py` 继续用第三份 regex，双标风险残留] → 登记 bd issue 跟进「lint 闸门对齐 narrative_contract」（design_docs 侧允许按路径 import 插件 utils，无环境负担，适合独立小变更）。
- [`_meta` 顶层键被误当域读取] → config_manager 与渲染路径全部按 `NARRATIVE_SCENE_VARS` 声明域/section 名访问，不遍历顶层键；实施时以一条加载日志验证 `_meta` 零影响，并以 sync 脚本一次 `--dry-run` 验证 round-trip。

## Migration Plan

无部署/数据库迁移。运行时行为不变，随插件重载生效；脚本侧无新 flag（仅删 regex 与增按路径加载），旧调用方式不变。回滚 = revert 单个 commit。`config/narrative_config.json` 的 `_meta` 段随下一次脚本写入自然入库，无需用户确认（内容等价，非内容变更）。

## Open Questions

无（落点、API 面、解析器真值、生成物标注语义、测试策略五处设计点均已按 settled direction 结合代码事实与评审实测收敛）。

# Design — narrative-contract-module

## Context

架构评审（data/config/render 层）确认两处独立病灶：

**病灶一：契约解析三份实现。** `extract_template_vars`（`utils/narrative_text.py:111-124`，`string.Formatter`）是运行时唯一真值；`scripts/sync_copy_variants_to_config.py:141-143` 的 `_template_vars` regex（`\{(\w+)`）只取 `\w+` 前缀——对 `{next_bonus:.0%}` 得 `next_bonus`（与 Formatter 一致， lucky），但对 `{{literal}}` 转义会**多报**一个变量、对 `{player.name}` 取根 `player` 是 regex 巧合而非语义；`lint_narrative.py:117` 的 `_WHITELIST_VAR_RE`（`\{([a-zA-Z_0-9]+)(?::[^}]*)?\}`）第三份。三份对当前稿子的判定恰好一致（稿子只用 `{var}` 与 `{var:spec}`），所以 bug 是潜伏的：任一稿子引入转义/嵌套即出现「闸门过、加载拒」的双标。此外 `config_manager.py:23-28` 私有 import（`_NARRATIVE_ROUTES`、`_iter_scene_entries`）使 `narrative_text` 的私有改名成为跨模块破坏面。

**病灶二：文案三拷贝 + 生成关系未声明。** `copy_variants.csv`（设计真源，§15 唯一内容入口）→ 同步脚本 → `config/narrative_config.json`（38 KB 已入库，tmp+replace 写入，**实际是生成物**）；`data/narrative_defaults/*.py`（514 行）是运行时回退与大量测试的 fixture（`tests/test_breakthrough_manager.py:33`、`test_combat_report_structure.py:31`、`test_rift_adventure_narrative.py:32` 等按路径加载），却只靠手维护 + 「内嵌默认全量符合契约」测试兜底，与 config 无生成关系，可静默漂移。

注意 `NARRATIVE_SCENE_VARS`（渲染点声明变量集）是**代码所有**的契约声明（spec「模板插值变量契约校验」的锚点），不是文案——它留在 `data/narrative_defaults/` 包中不动，contract 模块只做消费。

## Goals / Non-Goals

**Goals:**
- 契约解析/校验/池迭代单源在 `utils/narrative_contract.py`，公共 API 三五个符号；运行时（config_manager 加载校验）、同步脚本、未来 lint 对齐共用一份实现。
- 三处既有消费点的**外部行为**逐位不变：加载校验的日志文案与回退动作、渲染回退链、同步闸门的写入/跳过/失败语义。
- 文案管线三层关系显式化：CSV=真源，config JSON=声明过的生成物，defaults=脚本冻结快照；漂移可被 `--check` 机械发现。
- 全部稿子零改动（本变更不动 design_docs 任何内容行）。

**Non-Goals:**
- 不合并 `lint_narrative.py` 的白名单 regex（design_docs 侧独立工具，合并需 design_docs 反向依赖插件包——登记 bd 跟进，见 Risks）。
- 不改 `render_narrative` 的回退链语义（config→内嵌默认→"" 的三级顺序、双槽短路先于默认回退等均已由 spec 场景钉住）。
- 不动 `NARRATIVE_SCENE_VARS` 的位置与内容（代码所有的声明层）。
- 不引入 ADR/CONTEXT.md（`narrative_contract` 是既有契约概念的代码符号，非新领域概念）。

## Decisions

**D1 · 落点：新建 `utils/narrative_contract.py`，而非把校验下沉进 `narrative_text.py` 或上提进 `config_manager`。**
`narrative_text` 是渲染层（热路径，被战斗每回合调用），校验是加载/同步期的离线关注点——两者生命周期不同，合一会让渲染模块背负离线校验的全部形态分支（深模块变胖接口）。`config_manager` 是插件包内类，脚本（无 AstrBot 环境）按路径加载它成本极高，故契约必须住在「standalone 可加载」的 utils 层。`utils/` 已有 standalone 双路径先例（`narrative_text.py:47-71`），contract 沿用同款 trick，脚本与测试 shim 零新机制。

**D2 · API 面：`used_vars` / `validate_scene` / `iter_scene_entries` / 两个常量，五个公共符号；`extract_template_vars` 保留为薄包装。**
`extract_template_vars` 被 `config_manager`、若干测试 import，保留名字变包装避免连锁 diff；新代码一律用 `used_vars`。`validate_scene` 吸收 `_check_narrative_scene` 的全部分支（双槽非法形态整场景拒绝、未知桶键仅告警、route 标注合法性、逐条目变量子集校验），返回 `(ok, diagnostics)` 结构，config_manager 负责「日志 + 回退默认」的动作执行——**校验判定与处置动作分离**：contract 不 import logger 写死动作，保持纯函数好测试；处置语义留在唯一调用方 config_manager，locality 不丢。

**D3 · 解析器真值 = `string.Formatter`；regex 镜像删除，不做「兼容 regex 行为」的过渡层。**
当前稿子集合下两实现逐位一致（已逐场景验证：全池条目只用 `{var}`/`{var:spec}`），无过渡兼容负担。`{var:spec}` 由 Formatter 原生支持（`lint_narrative.py` 注释 :117 确认稿子存在该用法），regex 版本只是前缀巧合。统一后 `{{` 转义按 Python 格式串语义处理，与渲染时 `format_map` 真值同源——**校验器与渲染器共用同一套语法理解**，这是本变更的核心深度收益。

**D4 · defaults 快照的生成源 = 通过双闸门后的 config 池，而非 copy_variants.csv 直接生成。**
曾考虑从 CSV 直接生成 defaults（省一层），但 CSV 行无「默认 vs 变体」分层标记，直接生成会把全部变体灌进回退层，改变「内嵌**最小**默认」的 spec 语义（空池回退场景会随机到与 config 相同的整池）。改为：同步脚本在写完 config 后，`--emit-defaults` 以**当前 config 池**为源生成 defaults 快照（键集合 = `NARRATIVE_SCENE_VARS` 声明域，池 = config 现状冻结）——语义=「内容基线时刻的最小回退」，与现状手维护内容逐场景等价（现状 defaults 正是从早期 config 基线手工抄录的产物）。**校验前置**：生成前先跑与加载校验同一份 `validate_scene`，不合格场景不进快照（等价现状「内嵌默认全量符合契约」）。漂移检查 `--check-defaults` 重生成并与入库文件 diff，非零退出。

**D5 · config JSON 标 GENERATED，但不改变 reconcile 语义。**
同步脚本现状是「CSV 有的场景写池、CSV 没有的场景保留 JSON 原值」——非 CSV 场景（代码迁移期落入的模板）仍是 config 的内容，标 GENERATED 后这些场景的手改会被「保留原值」语义吞掉，故在文件头注释中明示：**同步场景以 CSV 为准、非同步场景保留现值、任何场景都不要手改**（要改走 design_docs 流程，§15）。这与 spec「改文案不改代码」场景不冲突（运营改 JSON 的场景已被 §15 流程取代——该 spec 场景写于迁移期，本次在 spec prose 中补一句流程指向）。

**D6 · 测试策略：钉解析器边界 + 校验全形态 + 快照漂移，不钉三处调用点的重复实现。**
contract 单测覆盖：`{{}}` 转义不产生变量、`{var:spec}` 提取根名、`{player.name}`/`{x[0]}` 根提取、畸形花括号抛 `ValueError`；`validate_scene` 全形态真假例（双槽非法形态、未知桶键仅告警、route 越界、panel 越界）。快照漂移作为 pytest 场景（`--check-defaults` 的 in-process 版），失败信息给出再生成命令。

## Risks / Trade-offs

- [regex→Formatter 的统一在边缘语法上「改」了闸门判定（`{{` 转义不再误报）] → 这是对潜伏 bug 的修复而非回归；全池扫描确认无现存条目命中差异；tasks 中要求实施时跑一次全池对比（新旧解析器对 config + defaults 全部叶子条目的输出集合 diff 为空）作为机械验证。
- [defaults 生成格式（排序/换行）导致首次 `--emit-defaults` 大 diff] → 接受一次性重排（内容等价，git blame 断点在提交信息中说明）；快照文件头标注生成器版本，未来格式演进可识别。
- [`config_manager` 校验从「私有 import」改为「公共 API」后，有人绕过 contract 直接手写校验] → contract 的 `validate_scene` 是唯一做形态分支的地方，review checklist 核对 config_manager 不再出现 `_check` 私有逻辑残留。
- [`lint_narrative.py` 继续用第三份 regex，双标风险残留] → 登记 bd issue 跟进「lint 闸门对齐 narrative_contract」（design_docs 侧允许按路径 import 插件 utils，无环境负担，适合独立小变更）。
- [defaults 改生成物后，测试 fixture 语义从「手抄代码资源」变「冻结内容」] → `tests/test_narrative_config.py:499` 注释明确「defaults are code-owned resources」，需改述；fixture 的按路径加载路径不变，测试零改动。
- [`--emit-defaults` 与双闸门的次序（先生成后过闸？）] → 决定：gates 先全绿 → 写 config → 从 config 生成 defaults → `--check` 模式天然复用同一函数；任何一步失败不写文件（沿用 tmp+replace）。

## Migration Plan

无部署/数据库迁移。运行时行为不变，随插件重载生效；脚本侧新 flag（`--emit-defaults`/`--check-defaults`）为增量能力，旧调用方式不变。回滚 = revert 单个 commit（快照重排随回滚一并还原）。首次 `--emit-defaults` 需用户确认（内容等价 diff），符合 §15「导入由用户发起」约定。

## Open Questions

无（落点、API 面、解析器真值、生成源、GENERATED 语义、测试策略六处设计点均已按 settled direction 结合代码事实收敛）。

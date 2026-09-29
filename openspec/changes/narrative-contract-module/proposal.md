# narrative-contract-module

## Why

叙事文案的「模板插值变量契约」在仓内被实现了至少三份，且解析器互相不一致：

1. 运行时校验：`utils/narrative_text.py:111-124` 的 `extract_template_vars` 用 `string.Formatter` 解析；
2. 同步闸门：`scripts/sync_copy_variants_to_config.py:141-143` 的 `_template_vars` 是 regex「镜像」（`re.findall(r"\{(\w+)", ...)`），且 `:126` 的 `_default_scene_vars` 里还藏着**第四份**同款内联 regex；regex 在转义花括号、`{x[0]}` 嵌套字段、`{var:spec}` 格式符上与 `string.Formatter` 语义发散——闸门放行的稿子可能在加载校验处被拒，反之亦然，二者只能靠日志事后发现；
3. lint 闸门：`design_docs/content-design/lint_narrative.py:118` 的 `_WHITELIST_VAR_RE` 是第三个 regex。

同时 `config_manager.py:23-28` 为做加载校验**私有** import 了 `narrative_text` 的内部符号（`_NARRATIVE_ROUTES`、`_iter_scene_entries`），跨模块泄漏实现细节；`narrative_text` 被 4 处 shim 按文件路径独立加载（`managers/combat_manager.py:43-45`、`managers/rift_manager.py:77`、`managers/adventure_manager.py:69`、`core/breakthrough_fortune.py:26`），其导入结构任何裸相对 import 都会破坏这些 standalone 路径。

另一处关系未声明：`config/narrative_config.json`（38 KB，已入库、由同步脚本 tmp+replace 写入）**实际上已是生成物但无声明**。注意这不是「三份拷贝漂移」问题——实测 `data/narrative_defaults/*.py` 与 config 在 43/55 场景上形状与内容**刻意不同**（defaults 是单条「内嵌最小默认」兜底串，config 是全量分桶/双槽变体池），二者语义角色不同、不是副本关系；需要修复的只是 config 生成物身份的显式标注。

## What Changes

- 新增单一深模块 `utils/narrative_contract.py`，导出公共 API：`used_vars(template)`（唯一模板变量解析器，`string.Formatter` 实现）、`validate_scene(section, scene, value, declared, *, source)`（吸收 `config_manager._check_narrative_scene` 的全部形态分支：单模板/扁平池/分桶池/route 标注/双槽 panel；诊断携带 severity 与 `[source]` 插值位，使调用方日志可逐字复现）、`iter_scene_entries(value)`（吸收 `_iter_scene_entries`）、`NARRATIVE_BUCKET_KEYS`/`NARRATIVE_ROUTES` 常量。模块同时支持包内 import 与按路径独立加载（沿用 `utils/narrative_text.py:47-71` 的 standalone trick，供 managers 测试 shim 与脚本复用）。
- `utils/narrative_text.py` 的 `extract_template_vars` 变为对 `narrative_contract.used_vars` 的薄包装（保留公开名，避免连锁改动），池迭代改从 contract 导入——**import 必须走与 defaults 相同的 try/except 双路径回退**（该文件被 4 处 shim 按路径加载）；渲染主路径（`render_narrative` :278-343 的 config→内嵌默认回退链）行为不变，`data/narrative_defaults/` 的加载与手维护现状不变。
- `config_manager.py:23-28` 改从 `narrative_contract` 公共 API 导入；`_validate_narrative_config`/`_check_narrative_scene`（:548-659）委托给 `validate_scene`（传入 source=配置/内嵌默认），按返回的 severity 写日志——日志文案与回退语义保持现状逐字一致。
- `scripts/sync_copy_variants_to_config.py`：删 regex `_template_vars`（:141-143）**与 `_default_scene_vars` 内联 regex（:126）**，改用按路径加载的 `narrative_contract.used_vars`（加载手法同 :103-114）；`:248` 与 `:318` 两处调用点包 try/except `ValueError`（畸形花括号按契约不满足处理，场景跳过——regex 时代不会抛，Formatter 时代会）；模块 docstring Usage 块（:43-45）与 `--dry-run` 输出同步明示 `_meta` 约定。
- config 生成物身份显式化：`config/narrative_config.json` 增加顶层 `"_meta"` 段标注 `generated_by` 与 hand-edit 政策——**CSV 同步域场景以 copy_variants.csv 为准（§15 流程，手改 FORBIDDEN）；非同步域场景（legacy_encounter 等，当年外部化 dump 落入）保留手改现值**。`config_manager` 按 section 名读取、`NARRATIVE_SCENE_VARS` 声明域校验，多余顶层键零影响（实施时以一条加载日志验证）；`AGENTS.md` §5 加一行指针。
- `data/narrative_defaults/*.py` **保持手维护不动**（语义=「内嵌最小默认」兜底层，与 config 全量池不同源，不存在可消除的重复——详见 design.md Non-Goals）。
- `scripts/import_copy_variants.py`（剧本册→CSV，无模板解析）与 `lint_narrative.py`（design_docs 侧白名单 regex）不在本次合并范围，但在 design.md Non-Goals 中登记跟进方向（bd issue）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 — 纯重构 + 生成物标注显式化：模板变量契约校验、config→内嵌默认回退、双槽拼装、换行所有权等行为契约已在 `openspec/specs/narrative-text-config` 的需求级条目中定义，本变更不修改任何需求级行为——三个解析器统一后校验语义以 `string.Formatter` 为准，对**现有全部稿子**（无转义花括号、无嵌套字段下标的 `{}` 用法）结论逐位一致（257 个叶子条目实测零差异）；`_meta` 标注不改变「改文案不改代码」场景（spec.md:30-33）的可用性——非同步域场景手改 config 仍是运营路径，同步域场景按 §15 走 CSV→sync 流程。故 `.openspec.yaml` 设 `skip_specs: true`。）

## Impact

- **代码**：新增 `utils/narrative_contract.py`（深模块，吸收 4 处 regex/校验实现）；`utils/narrative_text.py`（瘦身：删解析器与池迭代实现，import 加双路径回退）、`config_manager.py`（:23-28 公共导入、:548-659 校验委托）、`scripts/sync_copy_variants_to_config.py`（删 2 处 regex，+按路径加载 contract 与 try/except，Usage 同步）。
- **生成物**：`config/narrative_config.json` 增加顶层 `_meta` 段（其余内容字节不变）。
- **测试**：`tests/test_narrative_config.py` 补 contract 单测（解析器边界：转义 `{{}}`、`{var:spec}`、嵌套字段根提取；`validate_scene` 全形态）；`tests/test_sync_copy_variants_admission.py` 必须零改动通过（钉死 `:126` regex 迁移后 `_default_scene_vars` 输出逐位不变，⊇ 放行语义不退化）。
- **文档**：`AGENTS.md` §5 配置系统加 `_meta` 指针；`openspec/specs/narrative-text-config/spec.md`「改文案不改代码」场景补一句流程指向（同步域走 CSV→sync；**仅 prose 同步，不动 SHALL/Scenario 断言**）。
- **无**数据库迁移、无对外玩法行为变化；脚本双闸门（预算 + lint）继续生效；`data/narrative_defaults/` 内容零改动。

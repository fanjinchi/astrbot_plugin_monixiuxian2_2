# Tasks — narrative-contract-module

## 1. 契约深模块 utils/narrative_contract.py

- [ ] 1.1 新建 `utils/narrative_contract.py`：公共 API `used_vars(template) -> set[str]`（`string.Formatter` 实现，移植 `utils/narrative_text.py:111-124` 语义：`{player.name}`/`{x[0]}` 取根、畸形花括号抛 `ValueError`）、`iter_scene_entries(value)`（移植 `_iter_scene_entries`，:346-358）、`validate_scene(section, scene, value, declared, *, source) -> tuple[bool, list[tuple[str, str]]]`（吸收 `config_manager._check_narrative_scene` :585-659 全部分支；每条 diagnostic 为 `(severity, message)`，severity ∈ {"warning", "error"}，message 已含 `[{source}]` 前缀且与 config_manager.py:606-657 现状日志**逐字一致**——现状混用 warning（未知桶键/route 越界）与 error（缺 text/花括号不配对/未知变量），diagnostics 丢级别或丢 source 都无法复现）、常量 `NARRATIVE_BUCKET_KEYS`（narrative_text.py:76）/`NARRATIVE_ROUTES`（:87）；模块支持包内 import 与按路径 standalone 加载（双路径 trick 沿用 `narrative_text.py:47-71` 结构）；不 import astrbot/logger（纯函数）；英文 Google 风格 docstring
- [ ] 1.2 `utils/narrative_text.py`：`extract_template_vars` 函数体改为调用 `narrative_contract.used_vars`（公开名保留）；删 `_iter_pool_entries` 之外的池迭代重复实现，`_iter_scene_entries` 改从 contract 导入；`NARRATIVE_BUCKET_KEYS`/`_NARRATIVE_ROUTES` 改为 re-export（`narrative_text` 现有公开消费方不破）；**`from .narrative_contract import ...` 必须照抄 :47-71 的 try/except 双路径回退**——本文件被 4 处 shim 按文件路径加载（`managers/combat_manager.py:44-45`、`managers/rift_manager.py:77`、`managers/adventure_manager.py:69`、`core/breakthrough_fortune.py:26`），裸相对 import 会同时破坏这 4 条 standalone 路径；模块渲染行为（`render_narrative` :278-343 三级回退链、`_render_dual_slot` :240-275）零改动；`data/narrative_defaults/` 加载路径与内容零改动

## 2. 消费点切换（config_manager + 同步脚本）

- [ ] 2.1 `config_manager.py:23-28`：私有 import（`_NARRATIVE_ROUTES`、`_iter_scene_entries`、`extract_template_vars`）改为从 `narrative_contract` 公共 API 导入；`_validate_narrative_config`（:548-583）与 `_check_narrative_scene`（:585-659）改为调用 `validate_scene`（内嵌默认侧传 `source="内嵌默认"`、配置侧传 `source="配置"`），按返回的 severity 写日志（warning/error 调用与文案逐字一致）、按判定执行「整场景回退内嵌默认」动作；校验/处置分离后 config_manager 内不得残留形态分支私有逻辑
- [ ] 2.2 `scripts/sync_copy_variants_to_config.py`：删 regex `_template_vars`（:141-143）**和 `_default_scene_vars` 内联 regex（:126）**，改用按路径加载的 `narrative_contract.used_vars`（加载手法同该文件 :103-114 的 narrative_defaults 加载）；`:248` 与 `:318` 两处调用点包 try/except `ValueError`（畸形花括号按契约不满足跳过场景，regex 时代不抛、Formatter 时代会抛）；调用语义不变——`_default_scene_vars()` 输出集合必须逐位不变（⊇ 放行判定不退化，由 3.3 的准入测试钉死）；Usage docstring 块（:43-45）补充 `_meta` 手改政策说明；`--dry-run` 输出同步明示该约定
- [ ] 2.3 机械验证：`uv run python -c` 脚本对比新旧解析器对 `config/narrative_config.json` + `data/narrative_defaults/*` 全部叶子模板（单 str / 池条目 text / panel）的变量集合输出，diff 必须为空；同时断言 `_default_scene_vars()` 迁移前后输出相等；结果贴进 PR 描述
- [ ] 2.4 `config/narrative_config.json` 生成物标注：增加顶层 `"_meta": {"generated_by": "scripts/sync_copy_variants_to_config.py", "hand_edit": "同步域场景（CSV 有行）以 design_docs/content-design/copy_variants.csv 为准（§15 流程），手改 FORBIDDEN；非同步域场景（legacy_encounter 等）手改保留现值"}`（JSON 无注释语法故用元信息段；`config_manager` 按 section 名读取、校验只遍历 `NARRATIVE_SCENE_VARS` 声明域，多余顶层键零影响——实施时以一条加载日志验证）；`AGENTS.md` §5 配置系统加一行指针

## 3. 测试

- [ ] 3.1 `tests/test_narrative_config.py` 新增 contract 单测：`used_vars` 边界（`{{literal}}` 不产生变量、`{next_bonus:.0%}` 提取 `next_bonus`、`{player.name}` 提取 `player`、畸形花括号 `ValueError`）；`validate_scene` 全形态真假例（双槽非法形态整场景拒绝、未知桶键仅告警不拒、route 越界标注告警、panel 越界变量定位 `[panel]#0`），并断言每条 diagnostic 的 (severity, message) 与 config_manager 现状日志逐字一致（含 `[配置]`/`[内嵌默认]`）；`iter_scene_entries` 分桶/扁平两形态 location 标记
- [ ] 3.2 `tests/test_sync_copy_variants_admission.py` 零改动通过——它驱动真实的 `_default_scene_vars()`/`_apply_short_text`，是「:126 regex 迁移后输出与 ⊇ 放行语义逐位不变」的机械锚；若翻红，说明 2.2 改了语义，回退修 migration 而非改测试
- [ ] 3.3 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过；`openspec validate --change narrative-contract-module` 通过

## 4. 文档同步

- [ ] 4.1 `AGENTS.md` §5 配置系统补 `narrative_config.json` 的 `_meta` 手改政策指针（同步域 FORBIDDEN / 非同步域保留）；§架构速览与 §15 中 `data/narrative_defaults/` 的「手维护」表述**保持原样**（本变更不再生 defaults，该层仍是代码所有的最小兜底）
- [ ] 4.2 `openspec/specs/narrative-text-config/spec.md`「改文案不改代码」场景（spec.md:30-33）补一句流程指向：非同步域场景手改 config 仍是运营路径（`_meta` 政策保留现值）；同步域场景经 design_docs CSV → sync 脚本入库（§15）。**仅 prose 同步，不动任何 SHALL/Scenario 断言**——该场景 WHEN（运营/策划修改 narrative_config.json）对非同步域依然成立
- [ ] 4.3 用 `bd` 登记跟进 issue：`lint_narrative.py` 白名单 regex 对齐 `narrative_contract`（design_docs 侧独立小变更，消除第三份解析器）

## 5. 收尾

- [ ] 5.1 按 AGENTS.md §7 版本 checklist 评估：纯重构 + 生成物标注，无玩法变化——无需升版本号
- [ ] 5.2 `scripts/sync_content_to_config.py`（数值内容管线）核对不受影响（本变更不触碰其 CSV↔config 映射）
- [ ] 5.3 本地 conventional commit（不 push）；PR 描述附 2.3 的全池对比结果

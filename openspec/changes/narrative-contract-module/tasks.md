# Tasks — narrative-contract-module

## 1. 契约深模块 utils/narrative_contract.py

- [ ] 1.1 新建 `utils/narrative_contract.py`：公共 API `used_vars(template) -> set[str]`（`string.Formatter` 实现，移植 `utils/narrative_text.py:111-124` 语义：`{player.name}`/`{x[0]}` 取根、畸形花括号抛 `ValueError`）、`iter_scene_entries(value)`（移植 `_iter_scene_entries`，:346-358）、`validate_scene(section, scene, value, declared) -> tuple[bool, list[str]]`（吸收 `config_manager._check_narrative_scene` :558-632 全部分支，返回判定+诊断消息而非直接 logger 动作）、常量 `NARRATIVE_BUCKET_KEYS`（:76）/`NARRATIVE_ROUTES`（:87）；模块支持包内 import 与按路径 standalone 加载（双路径 trick 沿用 `narrative_text.py:47-71` 结构）；英文 Google 风格 docstring
- [ ] 1.2 `utils/narrative_text.py`：`extract_template_vars` 函数体改为调用 `narrative_contract.used_vars`（公开名保留）；删 `_iter_pool_entries` 之外的池迭代重复实现，`_iter_scene_entries` 改从 contract 导入；`NARRATIVE_BUCKET_KEYS`/`_NARRATIVE_ROUTES` 改为 re-export（`narrative_text` 现有公开消费方不破）；模块渲染行为（`render_narrative` :278-343 三级回退链、`_render_dual_slot` :240-275）零改动

## 2. 消费点切换（config_manager + 同步脚本）

- [ ] 2.1 `config_manager.py:23-28`：私有 import（`_NARRATIVE_ROUTES`、`_iter_scene_entries`、`extract_template_vars`）改为从 `narrative_contract` 公共 API 导入；`_validate_narrative_config`（:521-556）与 `_check_narrative_scene`（:558-632）改为调用 `validate_scene` 并按返回的诊断消息写日志（日志文案与现状逐字一致）、按判定执行「整场景回退内嵌默认」动作；校验/处置分离后 config_manager 内不得残留形态分支私有逻辑
- [ ] 2.2 `scripts/sync_copy_variants_to_config.py`：删 regex `_template_vars`（:141-143），改用按路径加载的 `narrative_contract.used_vars`（加载手法同该文件 :103-116 的 narrative_defaults 加载）；:248 与 :318 两处调用点语义不变；导入语句集中至文件头常量区
- [ ] 2.3 机械验证：`uv run python -c` 脚本对比新旧解析器对 `config/narrative_config.json` + `data/narrative_defaults/*` 全部叶子模板（单 str / 池条目 text / panel）的变量集合输出，diff 必须为空；结果贴进 PR 描述

## 3. 文案管线显式化（生成物 + 快照）

- [ ] 3.1 `config/narrative_config.json` 生成物声明：JSON 无注释语法，采用顶层 `"_meta": {"generated_by": "scripts/sync_copy_variants_to_config.py", "hand_edit": "FORBIDDEN — 内容真源 design_docs/content-design/copy_variants.csv（§15）；同步场景以 CSV 为准，非同步场景保留现值"}` 元信息段（`config_manager` 按 section 名读取、校验只遍历 `NARRATIVE_SCENE_VARS` 声明域，多余顶层键零影响——实施时以一条加载日志验证）；`AGENTS.md` §5 配置系统加一行指针；脚本 `--dry-run` 输出与模块 docstring 同步明示该约定
- [ ] 3.2 `scripts/sync_copy_variants_to_config.py` 新增 `--emit-defaults`：双闸门全绿 + config 写入后，以 `NARRATIVE_SCENE_VARS` 声明域为键集、以**当次通过校验的 config 池**为源，重新生成 `data/narrative_defaults/*.py` 快照（每域一个文件，结构与现状相同：模块级 dict + `__init__.py` 汇编；文件头 GENERATED 注释）；快照生成前对每个场景跑与加载校验同一份 `validate_scene`，不合格场景不进快照并 ERROR 退出
- [ ] 3.3 同脚本新增 `--check-defaults`：重生成快照并与入库文件 diff，不一致非零退出（供 CI/本地漂移检查）；`tests/test_narrative_config.py` 增加 in-process 等价场景：调用生成函数比对入库快照，漂移即测试失败（失败信息附 `--emit-defaults` 提示）
- [ ] 3.4 用户确认后执行一次 `--emit-defaults`（§15：导入由用户发起）：预期为一次性格式重排 diff（内容等价）；提交信息注明 blame 断点原因
- [ ] 3.5 更新 `tests/test_narrative_config.py:499` 附近「defaults are code-owned resources」注释为「generated frozen snapshot（见 scripts/sync_copy_variants_to_config.py --emit-defaults）」；核对 `tests/test_breakthrough_manager.py:33`、`test_combat_report_structure.py:31`、`test_rift_adventure_narrative.py:32` 等按路径加载 fixture 的测试零改动通过

## 4. 测试

- [ ] 4.1 `tests/test_narrative_config.py` 新增 contract 单测：`used_vars` 边界（`{{literal}}` 不产生变量、`{next_bonus:.0%}` 提取 `next_bonus`、`{player.name}` 提取 `player`、畸形花括号 `ValueError`）；`validate_scene` 全形态真假例（双槽非法形态整场景拒绝、未知桶键仅告警不拒、route 越界标注告警、panel 越界变量定位 `[panel]#0`）；`iter_scene_entries` 分桶/扁平两形态 location 标记
- [ ] 4.2 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过；`openspec validate --change narrative-contract-module` 通过

## 5. 文档同步

- [ ] 5.1 `AGENTS.md` §架构速览与 §15 如涉及 `data/narrative_defaults/` 手维护性质的表述，改述为「由 sync 脚本 `--emit-defaults` 生成的冻结快照（回退层），内容真源在 design_docs」；`design_docs/README.md` 如登记该目录为手维护资料，同步改注
- [ ] 5.2 `openspec/specs/narrative-text-config/spec.md` 的载体括注（「默认值存 `data/default_configs.py`，按域分片于 `data/narrative_defaults/`」）修正为「由同步脚本生成的冻结快照」；「改文案不改代码」场景补一句流程指向（改动经 design_docs → sync 脚本入库）；**仅 prose 同步，不动任何 SHALL/Scenario 断言**
- [ ] 5.3 用 `bd` 登记跟进 issue：`lint_narrative.py` 白名单 regex 对齐 `narrative_contract`（design_docs 侧独立小变更，消除第三份解析器）

## 6. 收尾

- [ ] 6.1 按 AGENTS.md §7 版本 checklist 评估：纯重构 + 生成管线显式化，无玩法变化——通常无需升版本号；若 metadata/README 有遗漏则补
- [ ] 6.2 `scripts/sync_content_to_config.py`（数值内容管线）核对不受影响（本变更不触碰其 CSV↔config 映射）
- [ ] 6.3 本地 conventional commit（不 push）；汇报 `--check-defaults` 漂移检查接入方式（pytest 场景已覆盖，是否另挂 webtest 回归由用户决定）

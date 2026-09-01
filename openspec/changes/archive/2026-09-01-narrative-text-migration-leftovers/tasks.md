# Tasks: narrative-text-migration-leftovers

## 1. 默认值与契约登记

- [x] 1.1 `data/narrative_defaults/fortune.py` 新增场景 `storage_full_drop`（文案逐字搬运自 `core/breakthrough_manager.py:538`：`🎁 机缘天降，获得【{name}】，但储物戒已满无法存入。`），`SCENE_VARS` 登记 `{name}`
- [x] 1.2 `data/narrative_defaults/combat.py` 新增 7 场景（文案逐字搬运，模板与变量集合见 design D2 表）：`round_header`（`:255`）、`effect_counter`（`:478-481`）、`effect_heal`（`:521-523`）、`effect_dot_attach`（`:568-570`）、`effect_stack_cap_rejected`（`:645-648`）、`effect_survive_grant`（`:699`）、`effect_dot_tick`（`:807-809`），逐场景登记 `SCENE_VARS`
- [x] 1.3 同步修正 `combat.py` 分片 docstring：删除"回合头与效果处理器句式不在范围"的过时注记，改为说明这些句式已纳入（过时注释视同 bug）

## 2. 突破域取数点替换

- [x] 2.1 `core/breakthrough_manager.py` `_apply_breakthrough_fortune`（`:538`）储物戒已满分支改为 `render_narrative(self.config_manager, "fortune", "storage_full_drop", {"name": item_name})`
- [x] 2.2 逐字核对：`fortune.storage_full_drop` 配置文本 == 原代码文本（含 emoji 与标点）

## 3. 战斗域取数点替换

- [x] 3.1 `resolve_combat` 回合头（`:255`）改为 `self._narrative("round_header", {"rounds": rounds})`
- [x] 3.2 实例方法两句：`_attach_stat_status` 叠加上限拒绝句（`:645-648`）→ `self._narrative("effect_stack_cap_rejected", ...)`；`_tick_status_effects` dot 侵蚀句（`:807-809`）→ `self._narrative("effect_dot_tick", ...)`
- [x] 3.3 staticmethod 处理器四句：`_handler_counter`（`:478-481`）/ `_handler_heal`（`:521-523`）/ `_handler_dot`（`:568-570`）/ `_handler_survive`（`:699`）经 `state["engine"]._narrative(scene, vars)` 渲染（design D3；不得直接调 `render_narrative`，保住 RNG 状态保存/恢复）；原 `skill.get('name', '反击')` 等缺省兜底在渲染点求值后作为变量传入
- [x] 3.4 逐字核对：7 个场景的 config 文本 == 原代码文本（含回合头的半角连字符、全角括号等细节）

## 4. 测试与质量门

- [x] 4.1 `tests/` 新增/更新外移核对用例：新场景默认文案与渲染结果核对（含 `SCENE_VARS` 契约登记）；可参照既有叙事载体用例
- [x] 4.2 `uv run python -m pytest tests/ -v` 全量通过（重点：`test_combat_engine.py`、`test_combat_handlers.py`、`test_breakthrough_manager.py`、`test_breakthrough_fortune.py`；池长 1 逐字搬运下断言不应变红）
- [x] 4.3 `uv run ruff format . && uv run ruff check .` 通过

## 5. 收尾

- [x] 5.1 `openspec validate narrative-text-migration-leftovers --strict` 通过
- [x] 5.2 版本 checklist（AGENTS.md §7）：`metadata.yaml` version 递增；`README.md` 更新日志末尾追加；本变更无指令变化，`修仙帮助` 文本无需更新
- [x] 5.3 流程注记：本次新增文案键位属工程性 config 变更，AGENTS.md §15 例外条款适用（不视为内容填充，无需先走 design_docs 管线）；后续对这些键位的内容文案改写仍须走 design_docs 管线
- [x] 5.4 关闭 bd `astrbot_plugin_monixiuxian2_2-9ux`、`astrbot_plugin_monixiuxian2_2-ji7`；functional_tests 相关域（战斗/突破）回归由用户手动发起（AGENTS.md 网页端测试平台节，2026-08-30 定）

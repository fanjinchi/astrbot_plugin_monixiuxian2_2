# Tasks: flavor-copy-assembly

## 1. 工具链前置修复（解锁内容闸门）

- [x] 1.1 `design_docs/content-design/lint_narrative.py`：脱槽正则 `_WHITELIST_VAR_RE` 支持 `{var:spec}` 格式符（如 `{next_bonus:.0%}`），格式符部分用非捕获组（`(?::[^}]*)?`）以免 `findall` 返回元组；脱槽后再做禁词/百分号/长度检查
- [x] 1.2 `design_docs/content-design/lint_narrative.py`：变量白名单改从 `NARRATIVE_SCENE_VARS` 读取（替代只认 str 形态场景的正则提取），保留 adventure_event 分支（事件域不在声明集内）
- [x] 1.3 `design_docs/content-design/scene_key_registry.md`：按 `NARRATIVE_SCENE_VARS` 全量重生成登记表白名单列（不止 pity_hint 缺 `next_bonus`，retreat_settlement 也缺 `gained_exp`/`current_exp`）；登记 6 个 B 场景的双槽载体形态
- [x] 1.4 lint 修复后存量 477 行回归：0 FAIL（确认无新误报/漏报）

## 2. 运行时双槽渲染

- [x] 2.1 `utils/narrative_text.py`：`render_narrative` 识别双槽形态（dict、`panel` 键值为字符串、且不含 `text` 键），flavor 池用剥离 `panel` 键后的值复用 `select_narrative_pool`（该函数零改动），实现 `flavor + "\n" + panel` 拼装；flavor 池空时只出 panel（**不得落入现有"pool 空 → 回退默认池"分支**，双槽分支须在其前短路）；缺 `panel` 键的 dict 维持原分桶池语义
- [x] 2.2 降级纪律：双槽分支内单设 try/except——flavor 渲染异常 → 记日志、跳过 flavor 只出 panel；panel format 失败 → 降级输出原始 panel（均不 raise）
- [x] 2.3 更新四处 docstring：`utils/narrative_text.py` 模块头与同文件 `render_narrative` 函数 docstring、`data/narrative_defaults/__init__.py`、`config_manager.py::_validate_narrative_config`——三种形态 → 四种形态

## 3. 加载校验扩展

- [x] 3.1 `config_manager.py` `_check_narrative_scene`：含 `panel` 键的 dict 场景，桶键告警豁免写成 `bucket != "panel"`（不误伤其他未知键告警）；字符串 panel 值经 `_iter_scene_entries` 自然成为 `[panel]#0` 条目接受变量子集校验
- [x] 3.2 非字符串 panel 特判必须放在 `_iter_scene_entries` 遍历**之前**短路（否则 list 形态 panel 被当 flavor 条目校验、语义冲突）：`panel` 键存在但值非字符串 → 告警 + 整场景回退内嵌默认；dict 同含 `text` 与 `panel` 键 → 同等告警回退（防止半畸形形态绕过）
- [x] 3.3 任一条目越界 → 整场景回退内嵌默认（复用现有回退分支）

## 4. 调用点补传 route/level_index

- [x] 4.1 `core/breakthrough_manager.py`：全部 11 处 `render_narrative` 调用统一补传 `route`/`level_index`（19 场景相关 9 处 + 顺带的 lose_streak_reward/storage_full_drop 2 处）；success 传突破后境界（渲染发生在 level_index +1 之后，直接用当前值）
- [x] 4.2 `handlers/player_handler.py` `_render_narrative` 与 `core/breakthrough_fortune.py`：补传（fortune 的 `format_fortune_message` 加可选参数，生产调用方仅 breakthrough_manager 一处）
- [x] 4.3 combat 域本次不补传：5 个 combat A 场景 CSV 变体全部 route=通用/band=通用（已核实），补传无行为差别；未来 combat 文案加路线标注时再定攻/守方取值规则（届时 `FighterState` 需加 route 字段）——在 `_narrative` 处留一行注释说明
- [x] 4.4 内嵌默认换行调整：`data/narrative_defaults/breakthrough.py` survive 模板 `{pity_msg}` 前补 `\n`、pity_hint 默认文案去前导 `\n`

## 5. 测试

- [x] 5.1 双槽渲染用例：拼装输出、flavor 池空只出 panel（验证不落入默认池回退）、route 过滤、分桶合并、缺 panel 键回退普通池、非字符串 panel 回退默认、text+panel 同 dict 回退
- [x] 5.2 校验用例：flavor 越界变量回退默认、panel 越界变量回退默认、panel 键不触发桶键告警
- [x] 5.3 回归：`select_narrative_pool` 对含 panel dict 的行为锁定（保护 adventure desc_variants 复用路径）；存量叙事测试全绿
- [x] 5.4 D6 组合测试：新 survive 默认/panel + pity_msg 渲染结果的拼接断言（换行恰好一次）；新旧组合（新 panel + 旧 pity_hint 等）降级有界性断言
- [x] 5.5 调用点传参后 success/survive 等场景的端到端渲染冒烟（含突破后段位桶选择）

## 6. 内容补写与终审（design_docs 流程，用户确认后导入）

- [x] 6.1 `design_docs/content-design/copy_variants.csv`：13 个 A 场景变体补写机械变量（清单见 design.md D2），口径为导入器契约"每条变体 ⊇ 默认模板变量集"
- [x] 6.2 五处结构性改写：`ultimate_cast` v02 改 `{attacker_name}` 视角；`weapon_drop` 去写死兵器形态；`pill_drop` v01 单复数中性化；`comprehend_fail` 两条变体按"失败中意外领悟"机制口径改写（现为"没悟成"，与软保底机制矛盾）；`retreat_settlement` flavor 去掉 `{time_str}`（与 panel 重复）
- [x] 6.3 B 场景 flavor 终审（design.md D9）：`breakthrough.death` 8 条"濒死获救"变体（no=02/04/06/08/10/12/14/16）与"身死道消"结局矛盾——逐条改写为死亡结局、删除或挪入 survive 池；其余 5 个 B 场景过一遍结局一致性抽查
- [x] 6.4 修复后 lint 通过（✓ 0 FAIL）；用户在 design_docs 侧确认文案（已确认）

## 7. 导入器扩展与入库

- [x] 7.1 `scripts/sync_copy_variants_to_config.py`：内置 6 个 B 场景清单；B 场景 panel 迁移（旧值 str → panel，**仅此迁移分支**在 survive 面板 `{pity_msg}` 前补 `\n`；旧值已是双槽 → 取其 `panel` 键原样保留，不重复补）；flavor 行按 level_band/route 写分桶；B 场景 flavor 导入校验改为 ⊆ 声明变量集
- [x] 7.2 dry-run 确认 19 个场景全部放行（0 FAIL），执行导入 `config/narrative_config.json`（43 场景写入，0 跳过；含 6 双槽 + 13 A 场景）
- [x] 7.3 导入后 pytest 全绿（762 passed；ConfigManager 加载新 config 零告警）
- [x] 7.4 跑一遍 `functional_tests/` 相关用例确认（gm-basics、gm-time-tools、player-lifecycle；断言均为 contains/未锚定 re，预期不破）——已跑（2026-09-11，`--sync --reload` + `--tag core-smoke` 8 例 + `--case gm-time-tools`，归档 `functional_tests/results/2026-09-11_flavor-copy-webtest/`）：三条具名用例全绿（gm-time-tools 需先清理平台虚拟玩家残留，见 -777），flavor 前置未打破任何闭关/结算断言。**但「预期不破」的前提只在被断言字面量上成立**：本轮导入删除了 `ultimate_cast`「施展大招」、`dodge`「身形一闪，躲过了」，加上上一轮 b1ff0c8 删除的「】作用于 / 受到的伤害降低 / 反弹 / 吸取 / 触发【」，pvp-effect*/pvp-ultimate*/pvp-weapon-trigger 的断言首分支已永久失配、只剩 `|战斗开始` 兜底（假绿，登记 -khh）；`battle_opening`/`battle_victory` 横幅在 b1ff0c8 已被文学句替换，pvp-basic-duel(526)/pvp-basic-spar(527) 真失败（登记 -r0a）；`remaining_hp` 恒定追加导致满血也被描述为濒死（登记 -hcn）；route B（突破双槽）零 webtest 覆盖（登记 -b5h）

## 8. 收尾

- [x] 8.1 `bd update 3bt` 标记 ① 部分完成（州条部分保持 open）
- [x] 8.2 `uv run ruff format . && uv run ruff check . && uv run python -m pytest tests/ -v` 全绿
- [x] 8.3 按 §7 版本 checklist：metadata.yaml 版本号、README 更新日志；按 §14 同步 design_docs（README 清单、current-design-report 如涉及）
- [x] 8.4 `openspec validate flavor-copy-assembly --strict` 通过，任务全部勾选（7.4 webtest 回归按项目约定留用户手动发起）

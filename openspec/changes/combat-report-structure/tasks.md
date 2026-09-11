# Tasks: combat-report-structure

## 1. 战报横幅代码化（bd -r0a）

- [ ] 1.1 `managers/combat_manager.py`：新增模块级横幅常量（`_BANNER_OPENING`/`_BANNER_VICTORY`/`_BANNER_DRAW`/`_BANNER_DRAW_STALEMATE`/`_BANNER_MUTUAL_DESTRUCTION`），文本逐字取自 `data/narrative_defaults/combat.py` 现存默认值（D1）
- [ ] 1.2 `resolve_combat` 改造：开局与四个结局分支均改为「append 代码横幅 + `if flavor:` 追加场景描述行」（D2）；`render_narrative` 返回 `""` 时跳过描述行
- [ ] 1.3 `data/narrative_defaults/combat.py`：五个框架场景默认值从横幅改写为最小文学描述句（D3，内容终审后落笔）；SCENE_VARS 不变
- [ ] 1.4 单测：五横幅恒定在场（含 config 池清空回退内嵌默认、场景缺失仍出横幅）；横幅+描述行拼装顺序；描述行场景"双缺失"（config 与内嵌默认均无）时 `render_narrative` 返回 `""`、只出横幅不报错；断言逐字横幅文本与 `{name}` 插值（注意真实契约：format 失败降级为原始模板文本而非 `""`，该路径由加载校验保证不可达，不做"异常只出横幅"断言）

## 2. remaining_hp 阈值分档（bd -hcn 机制侧）

- [ ] 2.1 `_resolve_attack` 分档判定（D4）：`ratio = hp / max(1, max_hp)`；`hp<=0` 或 `ratio>mid` 不输出；`(low,mid]` → `remaining_hp_mid`；`(0,low]` → `remaining_hp_low`；变量 `remaining_hp` 以 `f"{hp:,}"` 千分位传入
- [ ] 2.2 阈值配置：`self._combat_cfg` 读 `remaining_hp_mid_threshold`（默认 0.6）/`remaining_hp_low_threshold`（默认 0.3），缺省走代码默认；`config/game_config.json` 战斗段补两键（工程性字段）
- [ ] 2.3 `data/narrative_defaults/combat.py`：新增 `remaining_hp_mid`/`remaining_hp_low` 各一条中性最小默认句 + SCENE_VARS 登记 `{"defender_name","remaining_hp"}`；删除旧 `remaining_hp` 场景与其 SCENE_VARS 条目（D5）
- [ ] 2.4 `scene_key_registry.md` 重生成（新场景登记、旧场景移除）
- [ ] 2.5 单测：分档四格边界（ratio 恰等 mid / 恰等 low / hp=0 / 高血量）、千分位断言、代码不再引用旧场景键（grep 钉）

## 3. 内容成稿与用户确认（design_docs 流程）

- [ ] 3.1 `copy_variants.csv`：4 条 remaining_hp 变体改写（千分位变量织入成句、收紧濒死语义、不得描述死者）并改 scene 为 `remaining_hp_low`；`remaining_hp_mid` 残局档新稿（D6 规范：残局档不得出现濒死语义）
- [ ] 3.2 框架场景 5 条内嵌默认句与 remaining_hp 两档默认句的内容终审（world-bible 正档）
- [ ] 3.3 `lint_narrative.py` 0 FAIL；**等用户确认文案**后进入组 4

## 4. 导入与配置退役

- [ ] 4.1 导入器改动（评审 C1）：`sync_copy_variants_to_config.py::_apply_short_text` 放行"config 缺失但已在 `NARRATIVE_SCENE_VARS` 声明且有内嵌默认"的新场景键（直接创建分桶池）；unknown 仅保留给完全未声明的键；脚本 docstring 同步
- [ ] 4.2 跑 `sync_copy_variants_to_config.py` 导入两档场景（dry-run 确认 `remaining_hp_mid/low` 落库、0 跳过）；显式移除 `config/narrative_config.json` 的旧 `remaining_hp` 键（一次性内容退役，commit 说明）
- [ ] 4.3 ConfigManager 加载零告警；`uv run python -m pytest tests/ -v` 全绿

## 5. 功能测试同步

- [ ] 5.1 pvp-basic-duel/spar 断言改回锚代码横幅（`☆━━━━ 战斗开始` / `☆━━━━ .* 胜利`），撤销 flavor-copy-assembly 7.5 的绕行锚；检查其余 pvp 用例无残留依赖
- [ ] 5.2 濒死档覆盖：调整/新增一例使战斗必到低血（利用 pvp fixture 血量与武器伤害配置），断言 `remaining_hp_low` 池句出现且含千分位
- [ ] 5.3 webtest 回归由用户手动发起后归档结果

## 6. 收尾

- [ ] 6.1 `bd close` -hcn 与 -r0a（注明修复变更）；检查 -xdl（pvp 创建步锚文案池）是否顺带可修
- [ ] 6.2 `uv run ruff format . && uv run ruff check . && uv run python -m pytest tests/ -v` 全绿
- [ ] 6.3 §7 版本 checklist：metadata.yaml、README 更新日志；§14 同步 `design_docs/current-design-report.md` 战报结构段
- [ ] 6.4 `openspec validate combat-report-structure --strict` 通过，任务全部勾选

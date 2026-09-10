## Why

`copy_variants.csv` 477 条定稿文案中，19 个场景的变体是纯文学 flavor 句、不携带默认模板的机械变量（如 `breakthrough.success` 缺整张属性成长面板、`combat.damage_normal` 缺 `{final_damage}`），整体替换会让玩家看不到伤害数字/修为损失/结算面板，因此导入时被契约闸门整体拦截。这些场景需要一个既不丢机械信息、又不牺牲文案质量的落地方案。

## What Changes

按信息密度把 19 个场景拆成两条路线落地：

- **路线 A（13 个轻信息场景，1~3 个变量）**：文案补写，把机械变量织回散文（如 dodge 变体织入 `{attacker_name}`/`{defender_name}`）。运行时零改动，过现有契约校验即可导入。场景：comprehend_fail/comprehend_success/comprehend_universal、pity_hint、damage_normal/damage_crit/dodge/status_expired/ultimate_cast、retreat_epiphany、heart_method_drop/pill_drop/weapon_drop。
- **路线 B（6 个重面板场景）**：新增"flavor 引子 + 机械面板"双槽场景形态——flavor 句进分桶池，机械面板作为单源 `panel` 模板保留，渲染时拼装。场景：breakthrough.success/survive/death/revive、retreat_settlement、retreat_start。
- 运行时：`render_narrative` 识别双槽形态（含字符串 `panel` 键的场景值），先抽 flavor 再渲染面板拼接；`select_narrative_pool` 行为不变（adventure `desc_variants` 复用路径不受影响）；`_validate_narrative_config` 扩展校验——panel 与 flavor 条目分别做"变量 ⊆ 声明集"子集校验，越界整场景回退内嵌默认。
- 调用点：B 场景相关渲染调用点（breakthrough_manager 全部 11 处渲染调用、player_handler、breakthrough_fortune）补传 `route`/`level_index`，使分桶与路线标注实际生效（当前全部调用点不传，52 条 B 场景 flavor 中 47 条（90%）带段桶/路线标注、会是死文案）。combat 域不补传——5 个 combat 场景 CSV 变体全部 route=通用/band=通用（已核实），补传无行为差别。
- 工具链：`design_docs/content-design/lint_narrative.py` 脱槽正则支持 `{var:spec}` 格式符（pity_hint 的 `{next_bonus:.0%}` 否则永远过不了闸门）；变量白名单改读 `NARRATIVE_SCENE_VARS`（现有正则只认 str 形态场景，场景转 dict 后白名单校验失效）；`design_docs/content-design/scene_key_registry.md` 同步。
- 导入器：`sync_copy_variants_to_config.py` 对 B 场景把现有默认模板移入 `panel`、flavor 写入分桶（幂等：二次运行取旧值的 `panel` 键）；对 A 场景维持现有契约校验导入。
- 内容：`copy_variants.csv` 的 13 个 A 场景变体补写变量（design_docs 内容流程，lint 闸门）。
- 换行约定修复：survive 面板 `{pity_msg}` 的换行改由面板自身承担（内嵌默认同步调整），不再依赖 pity_hint 文案的前导 `\n`（导入器 strip 会剥掉它）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `narrative-text-config`: 场景值新增第四种形态——双槽形态（分桶 flavor 池 + 单源 panel 模板）；变量契约校验扩展为 flavor/panel 分别校验；渲染语义变为 flavor 引子与面板拼装输出；重面板场景渲染调用点 SHALL 提供玩家路线与境界段。

## Impact

- **运行时**：`utils/narrative_text.py`（`render_narrative` 双槽识别）、`config_manager.py`（`_check_narrative_scene` 校验扩展）
- **调用点**：`core/breakthrough_manager.py`（11 处渲染调用）、`handlers/player_handler.py`（`_render_narrative`）、`core/breakthrough_fortune.py`（`format_fortune_message` 加签名）——补传 `route`/`level_index`，不改业务逻辑；`managers/combat_manager.py` 仅加注释说明本次不补传
- **内嵌默认**：`data/narrative_defaults/breakthrough.py`——survive 默认模板 `{pity_msg}` 前补换行、pity_hint 默认文案去前导 `\n`（换行责任移入面板）
- **工具链**：`design_docs/content-design/lint_narrative.py`（格式符脱槽、白名单来源）、`design_docs/content-design/scene_key_registry.md`（pity_hint 白名单补 `next_bonus`、B 场景载体形态登记）
- **导入器**：`scripts/sync_copy_variants_to_config.py`（B 场景 panel 迁移 + 幂等 + flavor ⊆ 校验、A 场景放行）
- **内容**：`design_docs/content-design/copy_variants.csv`（13 个 A 场景变体补写；ultimate_cast v02 视角、weapon_drop 兵器形态、pill_drop 单复数需结构性改写）
- **配置**：`config/narrative_config.json` 6 个 B 场景转为双槽形态（由导入器生成，兼容旧形态——纯字符串/分桶池继续可用）
- **测试**：`tests/` 叙事渲染与契约校验用例扩展；核查 `functional_tests/` 中断言闭关/结算消息开头的用例（gm-time-tools 等）是否被 flavor 前置打破
- 不涉及数据库迁移；不涉及 `_conf_schema.json`；场景值形态向后兼容（旧形态照常渲染）

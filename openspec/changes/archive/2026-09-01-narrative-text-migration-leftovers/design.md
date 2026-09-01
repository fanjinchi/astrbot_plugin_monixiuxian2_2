# Design: narrative-text-migration-leftovers

## Context

`externalize-narrative-texts`（已归档）建立了叙事文案配置化载体：`config/narrative_config.json` 按域分节，默认值按域分片于 `data/narrative_defaults/`（每片暴露 `SCENES` + `SCENE_VARS`，由 `__init__.py` 装配为 `DEFAULT_NARRATIVE_CONFIG` / `NARRATIVE_SCENE_VARS`），运行时统一经 `utils/narrative_text.py` 的 `render_narrative` 渲染，加载时由 `ConfigManager._validate_narrative_config` 做插值变量契约校验。动机见 proposal.md - Why。

遗留点位现状（2026-08-30 重新定位；bd issue 中行号创建于约 2026-08-19，已漂移）：

- 突破域 1 处：`core/breakthrough_manager.py:538`（`_apply_breakthrough_fortune`）储物戒已满机缘句。同函数成功路径已走 `format_fortune_message` → `fortune` 节渲染（`core/breakthrough_fortune.py:301`）。
- 战斗域 7 处，均在 `managers/combat_manager.py`：
  - `:255` 回合头 `-- 第 {rounds} 回合 --`（`resolve_combat`，实例方法）
  - `:478-481` 反击结算句（`_handler_counter`，**staticmethod**）
  - `:521-523` 治疗结算句（`_handler_heal`，**staticmethod**）
  - `:568-570` dot 附着句（`_handler_dot`，**staticmethod**）
  - `:645-648` 叠加上限拒绝句（`_attach_stat_status`，实例方法，同函数成功分支已走 `self._narrative("buff_applied")`）
  - `:699` 免死庇护授予句（`_handler_survive`，**staticmethod**）
  - `:807-809` dot 侵蚀结算句（`_tick_status_effects`，实例方法，同函数过期句已走 `self._narrative("status_expired")`）
- `data/narrative_defaults/combat.py` 分片 docstring 明确注记"回合头与效果处理器句式不在本（原）变更范围"——本变更落地后该注记过时，须同步修正。
- 既有约束：战斗渲染必须经 `CombatEngine._narrative` 包装（`:183-200`），它在渲染前后保存/恢复全局 RNG 状态，防止模板轮换的 `random.choice` 污染战斗 RNG 流（种子统计测试稳定性）。

## Goals / Non-Goals

**Goals:**

- 上述 8 个点位全部改为从 `narrative_config` 读取渲染，改文案不再改代码
- 新场景纳入既有契约校验与回落链路，零新机制
- 逐字搬运，输出与迁移前完全一致，既有测试断言不变红

**Non-Goals:**

- 不改文案内容、不预填变体（全部池长 1 单模板形态）；分桶/route 标注形态本变更不使用
- 不外移数值说明类文本（战斗属性面板行 `:238-245`、突破 `rate_info` 等，沿用归档变更 D6）
- 不重构静态效果处理器的分发结构（`EFFECT_HANDLERS` 表、staticmethod 形态保持不变）

## Decisions

### D1：场景 key 与节归属

- 储物戒已满机缘句入 `fortune` 节，场景 key `storage_full_drop`——它与机缘三句（`weapon_drop`/`heart_method_drop`/`pill_drop`）是同一掉落轮盘的四个结果分支，虽由 `breakthrough_manager` 渲染，但语义属机缘域，与同节兄弟场景并列最直觉。
- 战斗域 7 场景入 `combat` 节，命名沿用既有键风（`buff_applied`/`status_expired`/`survive`）：`round_header`、`effect_counter`、`effect_heal`、`effect_dot_attach`、`effect_stack_cap_rejected`、`effect_survive_grant`、`effect_dot_tick`。
- **理由**：归档变更 D1 的"按域分节、按场景挂模板"结构不变，本变更只是补场景；备选"为效果句式单开 `combat_effects` 节"放弃——节越少，内容侧写作时要开的文件越少。

### D2：插值变量清单（逐场景契约）

新场景在对应分片 `SCENE_VARS` 登记后，自动纳入 `_validate_narrative_config`（该校验器按 `NARRATIVE_SCENE_VARS` 全量遍历，内嵌默认与用户配置两侧都校验）。变量命名对齐既有场景习惯（`actor_name`/`target_name`/`skill_name`/`effect_name`）：

| 场景 | 模板（逐字搬运） | 变量集合 |
|---|---|---|
| fortune.`storage_full_drop` | `🎁 机缘天降，获得【{name}】，但储物戒已满无法存入。` | `{name}` |
| combat.`round_header` | `-- 第 {rounds} 回合 --` | `{rounds}` |
| combat.`effect_counter` | `{actor_name} 触发【{skill_name}】反击，对 {target_name} 造成 {counter_dmg} 点伤害！` | `{actor_name, skill_name, target_name, counter_dmg}` |
| combat.`effect_heal` | `{actor_name} 触发【{skill_name}】，恢复 {heal} 气血！` | `{actor_name, skill_name, heal}` |
| combat.`effect_dot_attach` | `{actor_name} 使【{skill_name}】附着于 {target_name}` | `{actor_name, skill_name, target_name}` |
| combat.`effect_stack_cap_rejected` | `{actor_name} 的【{effect_name}】未生效：同类效果已达叠加上限（{stack_cap}）` | `{actor_name, effect_name, stack_cap}` |
| combat.`effect_survive_grant` | `{actor_name} 获得【{skill_name}】庇护！` | `{actor_name, skill_name}` |
| combat.`effect_dot_tick` | `{name} 受【{effect_name}】侵蚀，损失 {dot_dmg} 气血！` | `{name, effect_name, dot_dmg}` |

原代码中 `skill.get('name', '反击')` 等缺省兜底在渲染点求值后作为 `skill_name` 传入，模板本身不含兜底逻辑。实现时以各渲染点实际可提供的变量为准，若与上表有出入以代码为准修订 `SCENE_VARS`（校验器会抓住脱节）。

### D3：静态效果处理器的渲染入口

4 个 staticmethod 处理器（counter/heal/dot/survive）无 `self`，但 `state["engine"]` 已在用（`_handler_counter` 现即以 `state["engine"]._try_survive` 调引擎）——渲染同样经 `state["engine"]._narrative(scene, vars)`；实例方法（`resolve_combat`/`_attach_stat_status`/`_tick_status_effects`）直接 `self._narrative(...)`。**所有新渲染点必须走 `_narrative` 包装而非直接调 `render_narrative`**，以保住 RNG 状态保存/恢复。

### D4：空桶/缺 key 回落——沿用既有链路，不写新机制

- 存量部署的 `narrative_config.json` 不含新场景 key：`_load_config_with_default` 不做键合并（文件存在即原样加载），`render_narrative` 在场景缺失时回落 `DEFAULT_NARRATIVE_CONFIG` 内嵌默认——这是既有回落路径，行为与逐字搬运后的原文一致，无需迁移脚本。
- 契约校验违例场景：加载时替换为内嵌默认并报错（场景 key + 变量名），不崩溃（既有行为）。
- 测试 fake config（无 `narrative_config` 属性）：静默走内嵌默认（既有行为，`test_combat_engine.py` 等不变红）。

### D5：逐字搬运，内容零变更

对齐归档变更 D5：所有外移文案逐字复制（含 emoji、全/半角标点、回合头的半角连字符），diff 审查逐条核对"配置文本 == 原代码文本"。

## Risks / Trade-offs

- [战斗 RNG 流被模板轮换污染，种子统计测试漂移] → D3 强制经 `_narrative` 包装（既有 RNG 保存/恢复）
- [变量命名与渲染点脱节] → D2 逐场景 `SCENE_VARS` 契约 + 加载时校验；内嵌默认也参与校验，断裂启动即见错
- [`combat.py` 分片 docstring 的"不在范围"注记落地后过时] → tasks 显式列出同步修正，过时注释视同 bug（AGENTS.md 注释约定）
- [存量配置不含新 key 导致玩家看不到文案] → D4：场景缺失自动回落内嵌默认，默认文案即原文逐字，行为不变

## Migration Plan

纯新增场景 + 取数点替换，无 DB/迁移脚本。新部署首次启动由 `_load_config_with_default` 落盘完整 `narrative_config.json`；存量部署靠 D4 回落路径，用户想获得可编辑的新场景 key 可删除 `narrative_config.json` 让其重建（既有运维模式，不需本变更处理）。回滚 = git revert（config 中多出的场景 key 无害）。

## Open Questions

（无——场景归属、变量契约、回落路径均有既有先例可循。）

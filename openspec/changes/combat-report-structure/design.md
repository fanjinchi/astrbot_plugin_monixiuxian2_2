# Design: combat-report-structure

## 背景与现状（已实读核实）

- `managers/combat_manager.py::resolve_combat`（约 :241、:295-310）把 `battle_opening` 与结局场景（`battle_victory`/`battle_draw`/`battle_draw_stalemate`/`battle_mutual_destruction`）的渲染结果**直接** append 进战报——这些场景当前在 config 里是纯文学句（b1ff0c8 导入），战报因此没有结构横幅（bd -r0a）。
- `_resolve_attack`（约 :1220-1228）每次命中后无条件追加 `remaining_hp` 行；config 池 4 条全是濒死语义且 `{remaining_hp}` 裸插（bd -hcn）。
- 内嵌默认 `data/narrative_defaults/combat.py:25-35` 仍保留原始横幅文本（`☆━━━━ 战斗开始 ━━━━☆` 等），:58 为中性数据行 `{defender_name} 剩余气血: {remaining_hp}`——**原始 UX 的事实源**。
- `copy_variants.csv` 现有 remaining_hp 4 行（通用桶）。
- 渲染管线已具备：空池回退内嵌默认、条目 trim、空条目丢弃（flavor-copy-assembly + 067e1f6）。

## 决策

### D1: 横幅文本落代码常量，逐字恢复原始形态

`combat_manager.py` 模块级常量：`_BANNER_OPENING = "☆━━━━ 战斗开始 ━━━━☆"`、`_BANNER_VICTORY = "☆━━━━ {name} 胜利！━━━━☆"`（代码 format 胜者名）、`_BANNER_MUTUAL_DESTRUCTION`、` _BANNER_DRAW_STALEMATE`、`_BANNER_DRAW`，文本逐字取自 `data/narrative_defaults/combat.py` 现存默认值（含全角标点，不"规范化"）。

备选「横幅留在 narrative_config 作单模板场景」——拒绝：那正是 -r0a 的破损形态（内容导入可以把横幅再次替换掉），横幅是战报的结构骨架，必须脱离文案轮换。

**battle_vs 排除说明**：`battle_vs`（`{name1} VS {name2}`）同为原始结构行且同样被文学化，但本变更有意不收归代码——对局双方信息由紧随其后的属性面板行承载，-r0a 的破损只针对起止标志；维持现状，后续若要收归与本次同构即可。

### D2: 框架场景 = 横幅 + 可选文学描述行

`resolve_combat` 改为：

```python
log.append(_BANNER_OPENING)
flavor = self._narrative("battle_opening")
if flavor:
    log.append(flavor)
```

结局分支同构（横幅常量 + 对应场景的 flavor 行）。`render_narrative` 的真实契约（`utils/narrative_text.py:321-343`，有钉测试）：场景缺失/空池 → 回退内嵌默认；format 失败 → 降级返回原始模板字符串；`""` 仅在 config 与内嵌默认**都没有**该场景时返回。D3 落地后五场景永远有内嵌默认，`if flavor:` 几乎恒真——它防的是"双缺失"极端；format 失败路径由加载时变量契约校验保证不可达。渲染层零改动。五个场景的 config 文学池原样保留，继续服役。

### D3: 内嵌默认从横幅改为最小文学描述行

五个框架场景的内嵌默认当前**就是横幅文本**——横幅归代码后若默认不变，回退路径会把横幅再输出一遍。默认值改写为最小中性描述句（内容侧定稿，如 `battle_opening`: "风停了，一战在即。"），保持"空池回退内嵌默认"语义不断裂。这是代码资源里的文案，随本变更直接改（微小文案，走设计文档终审而非 CSV 管线）。

### D4: remaining_hp 阈值分档与场景键

`_resolve_attack` 的追加点改为分档判定：

```python
ratio = defender.hp / max(1, defender.max_hp)
if defender.hp <= 0 or ratio > mid:  # 死亡由结局横幅表达；高血量降噪
    pass
elif ratio > low:
    scene = "remaining_hp_mid"   # 残局
else:
    scene = "remaining_hp_low"   # 濒死
```

- 阈值读 `self._combat_cfg`：`remaining_hp_mid_threshold`（默认 0.6）、`remaining_hp_low_threshold`（默认 0.3），工程性 config 新字段，缺省走代码默认。
- 变量：`{"defender_name": defender.name, "remaining_hp": f"{max(0, defender.hp):,}"}`——千分位在代码侧完成，文案只见到 `1,241`。
- `SCENE_VARS` 登记 `remaining_hp_mid/low = {"defender_name", "remaining_hp"}`；`scene_key_registry.md` 重生成。
- 内嵌默认：两场景各一条中性最小句（残局/濒死语义各自相符）。

备选「单场景 + HP 档桶键」——拒绝：分桶键已被境界段占用（`NARRATIVE_BUCKET_KEYS`），加第二轴会污染 `select_narrative_pool` 的通用语义；两个场景键零机制成本。

### D5: 旧 remaining_hp 场景退役路径与新键入库缺口

- 代码不再引用 `remaining_hp`；`data/narrative_defaults/combat.py` 删除该场景与 SCENE_VARS 条目。
- `config/narrative_config.json` 的 `remaining_hp` 键随导入运行移除（sync_copy_variants_to_config.py 只写不删，此处为一次性内容退役，在导入任务里显式删键并说明）。
- CSV：4 条现有变体改写（修复裸数字、收紧濒死语义）并将 scene 改为 `remaining_hp_low`；`remaining_hp_mid` 新写残局档（数量与 tone 按季度文案规范，内容阶段定）。
- 加载校验对"config 有键但无声明集"的行为：`_validate_narrative_config` 两个循环均由 `NARRATIVE_SCENE_VARS` 声明集驱动，无声明集的 config 键**不参与校验、静默忽略**（不告警也不拒绝），过渡期脏键无害——但这是比"只告警"更强的静默，故 tasks 组 4 的显式删键不可省。
- **新键入库缺口（评审 C1）**：导入器 `_apply_short_text` 对 config 中不存在的场景键归入 unknown 直接跳过；ConfigManager 只在**文件不存在**时物化默认配置，已有文件不会把内嵌默认的新键合并进去——`remaining_hp_mid/low` 若无配套改动将永远停在"未知场景键未写入"。决策：导入器放行"config 缺失但已在 `NARRATIVE_SCENE_VARS` 声明（且有内嵌默认）"的新场景键，直接创建分桶池；unknown 仅保留给完全未声明的键。脚本 docstring 同步更新。

### D6: 内容管线与用户确认

残局档新稿 + 濒死档 4 条改写 + 框架场景 5 条内嵌默认句，先在 `copy_variants.csv`（remaining_hp_* 行）与 design_docs 侧成稿，lint_narrative 过后**等用户确认**再导入（AGENTS §15）。文案规范：千分位变量织入成句（"气血只剩 1,241 点"式），残局档不得出现濒死语义，濒死档不得描述已死者。

### D7: 测试与功能测试

- 单测：五横幅恒定在场（含 config 池清空/回退极端）；横幅+flavor 拼装顺序；描述行场景"双缺失"时只出横幅（format 失败按真实契约降级为原始模板文本，不做"异常只出横幅"断言）；分档边界（ratio 恰等 mid/low/0 四格）；千分位断言；旧 `remaining_hp` 键不再被引用（grep 钉）。
- functional_tests：pvp-basic-duel/spar 断言改回锚 `☆━━━━ 战斗开始` / `☆━━━━ .* 胜利`（代码横幅是最稳锚点，撤销 7.5 的绕行锚）；新增或调整一例覆盖濒死档出现（pvp fixture 双方 8000 血长局必到低血）；`expect_not` 哨兵照旧。
- webtest 回归由用户手动发起（项目约定）。

### D8: 文档同步

- spec delta：`narrative-text-config` 增两个 Requirement（见 specs/）。
- `design_docs/current-design-report.md` 战报结构段同步（§14）；`design_docs/README.md` 无新资料不登记。
- README 更新日志 + metadata 版本号（§7）；`/修仙帮助` 无指令变化不动。

## 风险

- [框架场景内嵌默认改写后文风与 config 池不一致] → 默认句按 world-bible 正档写，仅在池空时出现，频率极低。
- [阈值 0.6/0.3 感受不佳] → 配置键可调，上线后按真机观感微调，不阻塞。
- [remaining_hp 行消失降低战报信息密度] → 有意取舍：高血量的数据行本是噪声；濒死/残局档保留信息量。
- [PvE 共用 `_resolve_attack`] → 敌人 FighterState 同样有 hp/max_hp，分档逻辑无差别适用；Boss 战报同样受益（高血量不再出"气血将尽"）。

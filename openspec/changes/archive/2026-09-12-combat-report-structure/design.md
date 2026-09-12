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

**对阵行一并收归（评审 Q1 再决策 → 方案 B）**：`battle_vs`（原始形态 `{name1} VS {name2}`，b1ff0c8 后已为文学变体池，如「{name1} 与 {name2} 相对而立，互道一声名号……」）同为结构行，Q1 复核时确认一并代码化——结构行（横幅 + 对阵行）全部脱离文案轮换，开局区块收敛为「横幅 / 结构对阵行 / 单条文学描述行 / 双面板」，避免"横幅 + 双文学句"三行连读。代价：2 条 VS 文学变体随场景退役弃用（不改写复用，如日后需要另立内容提案）。模块级常量 `_VERSUS_LINE = "{name1} VS {name2}"`（与横幅常量同组，half-width `VS` 与空格逐字复原）。

### D2: 框架场景 = 横幅 + 可选文学描述行

`resolve_combat` 开局改为（对阵行与横幅同为代码结构行，`battle_vs` 场景不再参与渲染）：

```python
log.append(_BANNER_OPENING)
log.append(_VERSUS_LINE.format(name1=fighter1.name, name2=fighter2.name))
flavor = self._narrative("battle_opening")
if flavor:
    log.append(flavor)
```

开局最终顺序：横幅 → 结构对阵行 → 开局描述行 → 双属性面板 → 空行（开局区块只剩一条文学句）。结局分支同构（横幅常量 + 对应场景的 flavor 行，横幅与描述行直接相邻）。`render_narrative` 的真实契约（`utils/narrative_text.py:321-343`，有钉测试）：场景缺失/空池 → 回退内嵌默认；format 失败 → 降级返回原始模板字符串；`""` 仅在 config 与内嵌默认**都没有**该场景时返回。D3 落地后五场景永远有内嵌默认，`if flavor:` 几乎恒真——它防的是"双缺失"极端；format 失败路径由加载时变量契约校验保证不可达。渲染层零改动。五个场景的 config 文学池原样保留，继续服役。

### D3: 内嵌默认从横幅改为最小文学描述行

五个框架场景的内嵌默认当前**就是横幅文本**——横幅归代码后若默认不变，回退路径会把横幅再输出一遍。默认值改写为最小中性描述句（内容侧定稿，如 `battle_opening`: "风停了，一战在即。"），保持"空池回退内嵌默认"语义不断裂。这是代码资源里的文案，随本变更直接改（微小文案，走设计文档终审而非 CSV 管线）。默认句受各场景声明集约束（内嵌默认同样过 load-time 校验，`config_manager.py:531-534`，违例即加载报错）：`battle_opening`/`battle_draw`/`battle_draw_stalemate`/`battle_mutual_destruction` 声明集为空 → 默认句不得含任何插值变量；`battle_victory` 声明集 `{name}` → 可含 `{name}`。成稿时（任务 3.2）按此约束终审。

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
- `SCENE_VARS` 登记 `remaining_hp_mid/low = {"defender_name", "remaining_hp"}`；`scene_key_registry.md` 手工同步更新（无生成器，见任务 2.4）。
- 内嵌默认：两场景各一条中性最小句（残局/濒死语义各自相符）。

备选「单场景 + HP 档桶键」——拒绝：分桶键已被境界段占用（`NARRATIVE_BUCKET_KEYS`），加第二轴会污染 `select_narrative_pool` 的通用语义；两个场景键零机制成本。

### D5: 旧 remaining_hp 场景退役路径与新键入库缺口

- 代码不再引用 `remaining_hp`；`data/narrative_defaults/combat.py` 删除该场景与 SCENE_VARS 条目。
- `config/narrative_config.json` 的 `remaining_hp` 键随导入运行移除（sync_copy_variants_to_config.py 只写不删，此处为一次性内容退役，在导入任务里显式删键并说明）。
- CSV：4 条现有变体改写（修复裸数字、收紧濒死语义）并将 scene 改为 `remaining_hp_low`；`remaining_hp_mid` 新写残局档（数量与 tone 按季度文案规范，内容阶段定）。
- 加载校验对"config 有键但无声明集"的行为：`_validate_narrative_config` 两个循环均由 `NARRATIVE_SCENE_VARS` 声明集驱动，无声明集的 config 键**不参与校验、静默忽略**（不告警也不拒绝），过渡期脏键无害——但这是比"只告警"更强的静默，故 tasks 组 4 的显式删键不可省。
- **`battle_vs` 同批退役（评审 Q1 再决策·方案 B）**：对阵行收归代码后该场景无消费者——`data/narrative_defaults/combat.py` 删场景与 SCENE_VARS 条目；`config/narrative_config.json` 显式删键；`copy_variants.csv` 2 行删除；`scene_key_registry.md` 与剧情文档同步（任务 3.4）。清理是**基线整洁**要求而非硬门禁：CSV 残留行只触发 lint 的「scene 未在运行时模板登记」WARN（`design_docs/content-design/lint_narrative.py::_check_copy_variants` 未知 scene → WARN 非 FAIL）。
- **新键入库缺口（评审 C1→修订）**：导入器 `_apply_short_text` 对 config 中不存在的场景键归入 unknown 直接跳过；ConfigManager 只在**文件不存在**时物化默认配置，已有文件不会把内嵌默认的新键合并进去——`remaining_hp_mid/low` 若无配套改动将永远停在"未知场景键未写入"。决策：导入器放行"config 缺失但已在 `NARRATIVE_SCENE_VARS` 声明（且有内嵌默认）"的新场景键，直接创建分桶池；unknown 仅保留给完全未声明的键。脚本 docstring 同步更新。
- **放行规则的全局语义（评审 Q3 确认）**：上述放行是导入器的**永久性全局新语义**——此后任何「SCENE_VARS 已声明 + 有内嵌默认 + config 暂缺」的场景键都会被 CSV 行直接建池落库，不限于本变更两档。已知副作用并接受：故意从 config 移除某声明键以走默认回退的行为，会被一次 CSV 导入重新写回。退役键（旧 `remaining_hp`）已从 SCENE_VARS 删除，不受放行影响——4.2 的 dry-run 以「旧键归 unknown」作为退役链路闭合的显式断言（见任务 4.2）。

### D6: 内容管线与用户确认

残局档新稿 + 濒死档 4 条改写 + 框架场景 5 条内嵌默认句，先在 `copy_variants.csv`（remaining_hp_* 行）与 design_docs 侧成稿，lint_narrative 过后**等用户确认**再导入（AGENTS §15）。文案规范：千分位变量织入成句（"气血只剩 1,241 点"式），残局档不得出现濒死语义，濒死档不得描述已死者。**变量契约按"恰好集"执行（评审 Q4 修订）**：两档每条变体变量集**恰好等于**声明集 `{defender_name, remaining_hp}`，不多不少——导入器只检查 `⊇ 内嵌默认变量集`（`sync_copy_variants_to_config.py:291`，无上界检查），多出变量的变体要到 load-time 校验（`_check_narrative_scene`）才被整场景替换为内嵌默认，故成稿/自检直接按恰好集写。

### D7: 测试与功能测试

- 单测：五横幅**与对阵行**恒定在场（含 config 池清空/回退极端、config 残留 `battle_vs` 键被静默忽略且不影响对阵行输出）；对阵行逐字断言（`测试玩家1 VS 测试玩家2`，half-width `VS` 与空格逐字）；拼装顺序（开局「横幅→结构对阵行→描述行→面板」、结局「横幅→描述行」）；描述行场景"双缺失"时只出横幅（format 失败按真实契约降级为原始模板文本，不做"异常只出横幅"断言）；分档边界（ratio 恰等 mid/low/0 四格）；千分位断言；两个退役键（`remaining_hp`/`battle_vs`）不再被代码引用（grep 钉）。
- functional_tests：pvp-basic-duel/spar 断言改回锚 `☆━━━━ 战斗开始` / `☆━━━━ .* 胜利`（代码横幅是最稳锚点，撤销 7.5 的绕行锚）；分档覆盖改**确定性设血**口径（评审 Q2，见任务 5.2）：GM 将防守方气血设入残局/濒死区间后一击断言，不再依赖 8000 血长局自然打低；`expect_not` 哨兵照旧。
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
- [PvE 玩家侧可见变化（评审确认接受）] → 玩家血 >60% 时战报不再输出自身剩余气血行（此前每击都有）——玩家仍可从伤害行推算，接受。
- [低血区间每击一行] → 仅高血档降噪，残局/濒死档仍每击一行（8000 血镜像战低血段约 5-8 行）——评审确认不做间隔节流，接受。
- [battle_vs 2 条文学变体弃用（评审确认接受）] → 文案不改写复用：该场景行含 `{name1}`/`{name2}`，而开局描述场景 `battle_opening` 声明集为空，不能直接并入其池；日后若要保留对峙画面，另立内容提案改写（去名或改声明集）。

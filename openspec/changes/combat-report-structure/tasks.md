# Tasks: combat-report-structure

## 1. 战报结构行代码化（bd -r0a）

- [x] 1.1 `managers/combat_manager.py`：新增模块级结构行常量——五条横幅（`_BANNER_OPENING`/`_BANNER_VICTORY`/`_BANNER_DRAW`/`_BANNER_DRAW_STALEMATE`/`_BANNER_MUTUAL_DESTRUCTION`，文本逐字取自 `data/narrative_defaults/combat.py` 现存默认值）+ 对阵行 `_VERSUS_LINE = "{name1} VS {name2}"`（half-width `VS` 与空格逐字复原；D1）
- [x] 1.2 `resolve_combat` 改造：开局与四个结局分支均改为「append 代码结构行 + `if flavor:` 追加场景描述行」（D2）；开局拼装顺序为「横幅 → `_VERSUS_LINE` 结构对阵行 → 开局描述行 → 双属性面板」（对阵行不再调 `_narrative`，`battle_vs` 场景退役），结局为「结局横幅 → 描述行」；`render_narrative` 返回 `""` 时跳过描述行
- [x] 1.3 `data/narrative_defaults/combat.py`：五个框架场景默认值从横幅改写为最小文学描述句（D3，内容终审后落笔）；删除 `battle_vs` 场景与其 SCENE_VARS 条目（对阵行收归代码，退役见 D5）
- [x] 1.4 单测：五横幅**与对阵行**恒定在场（含 config 池清空回退内嵌默认、场景缺失仍出横幅；config 残留 `battle_vs` 键被静默忽略且不影响对阵行输出）；对阵行逐字断言（`测试玩家1 VS 测试玩家2`）；拼装顺序（开局「横幅→结构对阵行→描述行→面板」、结局「横幅→描述行」）；描述行场景"双缺失"（config 与内嵌默认均无）时 `render_narrative` 返回 `""`、只出横幅不报错；断言逐字横幅文本与 `{name}` 插值（注意真实契约：format 失败降级为原始模板文本而非 `""`，该路径由加载校验保证不可达，不做"异常只出横幅"断言）
  - 2026-09-12 代码落地（`combat-report-structure` 代码任务）：五横幅 + `_VERSUS_LINE` 为 `managers/combat_manager.py` 模块常量；开局与四结局分支均「结构行 + `if flavor:` 描述行」；`data/narrative_defaults/combat.py` 五框架场景默认句按 `design_docs/剧情/03-战斗说书人剧本.md:255-289` 逐字落地（脚本比对 7 条默认句与设计稿字节一致），`battle_vs` 已删。单测 `tests/test_combat_report_structure.py`（22 条）

## 2. remaining_hp 阈值分档（bd -hcn 机制侧）

- [x] 2.1 `_resolve_attack` 分档判定（D4）：`ratio = hp / max(1, max_hp)`；`hp<=0` 或 `ratio>mid` 不输出；`(low,mid]` → `remaining_hp_mid`；`(0,low]` → `remaining_hp_low`；变量 `remaining_hp` 以 `f"{hp:,}"` 千分位传入
- [x] 2.2 阈值配置：`self._combat_cfg` 读 `remaining_hp_mid_threshold`（默认 0.6）/`remaining_hp_low_threshold`（默认 0.3），缺省走代码默认；读取处加合法域防御（clamp 到 (0,1) 且保证 low<mid，非法值回退默认并在注释写明合法域）；`config/game_config.json` 战斗段补两键（工程性字段）。已核实 `config_manager.py` 现无 combat 段结构校验（仅有 level/narrative/sect 三个校验器），按评审 Q5 口径**不新增校验器**（KISS）——阈值合法域由本步代码侧防御承担，无配置层校验
- [x] 2.3 `data/narrative_defaults/combat.py`：新增 `remaining_hp_mid`/`remaining_hp_low` 各一条中性最小默认句 + SCENE_VARS 登记 `{"defender_name","remaining_hp"}`（**默认句必须恰好使用两个变量**——导入器契约要求 CSV 变体 ⊇ 默认模板变量集，默认句缺变量会连锁跳过 CSV 行）；删除旧 `remaining_hp` 场景与其 SCENE_VARS 条目（D5）
- [x] 2.4 `design_docs/content-design/scene_key_registry.md` 同步更新：登记 `remaining_hp_mid/low`（变量白名单 `defender_name`/`remaining_hp`）、移除 `remaining_hp` 与 `battle_vs` 两条（该表为手工同步的登记表，无生成器）
- [x] 2.5 单测：分档四格边界（ratio 恰等 mid / 恰等 low / hp=0 / 高血量）、千分位断言、代码不再引用旧场景键（grep 钉：`remaining_hp` 与 `battle_vs` 两个退役键）
  - 2026-09-12 代码落地：分档判定与阈值 clamp 在 `managers/combat_manager.py`（`__init__` / `_resolve_attack`）；`config/game_config.json` 战斗段补两键；`scene_key_registry.md` 与 `SCENE_VARS` 全量核对零差异（30 键，两档默认句变量集恰好等于声明集）。退役键 pin 改为 AST 口径：只查 `_narrative(...)` 首个位置实参（变量名 `remaining_hp` 仍需在插值中保留）

## 3. 内容成稿与用户确认（design_docs 流程）

- [x] 3.1 `copy_variants.csv`：4 条 remaining_hp 变体改写（千分位变量织入成句、收紧濒死语义、不得描述死者）并改 scene 为 `remaining_hp_low`；`remaining_hp_mid` 残局档新稿（D6 规范：残局档不得出现濒死语义）；两档每条变体变量集**恰好等于** `{defender_name, remaining_hp}`（不多不少，评审 Q4——导入器只查 ⊇，超集变体要到 load-time 校验才被整场景替换为内嵌默认，成稿自检按恰好集执行）；删除 `battle_vs` 2 行（CSV:1111-1112，场景退役、文案弃用，同批处理）
- [x] 3.2 框架场景 5 条内嵌默认句与 remaining_hp 两档默认句的内容终审（world-bible 正档）。默认句受声明集约束（D3）：`battle_opening`/`battle_draw`/`battle_draw_stalemate`/`battle_mutual_destruction` 声明集为空 → 默认句不得含任何插值变量；`battle_victory` 可含 `{name}`；两档剩余气血默认句恰好带 `{defender_name}`+`{remaining_hp}`——内嵌默认自身同样过 load-time 校验（config_manager.py:531-534），违例即加载报错；7 条默认句在 `design_docs/剧情/03-战斗说书人剧本.md` 以「内嵌默认（池空回退）」小节登记（文案不只手活在代码里）
  - 2026-09-12：**用户已终审确认**（内容终审闸门闭合，组 4 得以执行）
- [x] 3.3 `lint_narrative.py` 0 FAIL 且无新增 WARN（退役行删除后不得残留「scene 未在运行时模板登记」WARN）；**等用户确认文案**后进入组 4
  - 2026-09-12 复核①（回归修复）：内嵌默认小节原用 `####` 帧标题，撞 `scripts/import_copy_variants.py::parse_book`（缺 `-NN` 直接报错）→ 已改为「`##` 标题 + 项目符号」格式；同批同步 `tests/test_import_copy_variants.py` 两处册条数（`477→478`、`"combat": 55→56`，经授权）。
  - 2026-09-12 复核②：`uv run python design_docs/content-design/lint_narrative.py` → **0 FAIL / 249 WARN**（与改动前基线一致，新增 0——`SCENE_VARS` 已由代码侧任务落地 `remaining_hp_mid/low`，先前 7 条「scene 未在运行时模板登记」残留 WARN 已清零）；`uv run python -m pytest tests/ -q` → **798 passed / 0 failed**。技术条件已满足，仅剩「**等用户确认文案**后进入组 4」这道人工闸门，勾选由主线确认。
  - 2026-09-12 代码侧复核（`combat-report-structure` 代码任务）：`uv run python design_docs/content-design/lint_narrative.py` → **0 FAIL / 249 WARN**；与 256 WARN 状态逐行 diff 仅 7 条删除（`remaining_hp_low`×4、`remaining_hp_mid`×3 的「scene 未在运行时模板登记」全部归零，`SCENE_VARS` 已登记两档），无新增 WARN → 本项 WARN 部分满足。注：本条内「等用户确认文案后进入组 4」的闸门不受本次勾选影响（4.2 未执行）。
- [x] 3.4 design_docs 同步（§14/§15，收束舍弃的文案去掉）：`design_docs/剧情/03-战斗说书人剧本.md` 删 `battle_vs-01/02` 两节（约 :29-35）、`remaining_hp-01..04` 更名改写为 `remaining_hp_low-*` 并补 `remaining_hp_mid-*`（约 :169-184）、更新文件头（场景数/条数/「数值句锁定」变量清单）与文末 checklist（约 :4-8、:254-255）；`design_docs/剧情/00-剧情总骨架.md` §1.3 遭遇开战组移除 `battle_vs`（:60）、技能演出组 `remaining_hp` 改 `remaining_hp_mid/low`（:63）；并重写 `03-战斗说书人剧本.md:10` 的「与 narrative_config 现状的说明」——五框架场景的「现有模板句（☆ 系统播报句）保持为默认句不动」已随 -r0a 失效（框架场景内嵌默认改为文学描述句、☆ 行由代码拼装），本册这 5 个场景的变体定位为纯文学描述行

## 4. 导入与配置退役

- [x] 4.1 导入器改动（评审 C1）：`sync_copy_variants_to_config.py::_apply_short_text` 放行"config 缺失但已在 `NARRATIVE_SCENE_VARS` 声明且有内嵌默认"的新场景键（直接创建分桶池）；unknown 仅保留给完全未声明的键；**新键放行后仍走同一变量契约检查（⊇ 默认模板变量集），不通过照旧归 skipped**；脚本 docstring 同步。注意该放行为**导入器永久性全局新语义**（评审 Q3 确认）：适用于此后所有「已声明 + 有内嵌默认 + config 暂缺」的场景键，不限于本变更两档；已知副作用（故意从 config 移除的声明键会被 CSV 重新写回）接受
- [x] 4.2 跑 `sync_copy_variants_to_config.py` 导入两档场景（dry-run 确认 `remaining_hp_mid/low` 落库、0 跳过，并**显式断言旧 `remaining_hp` 与 `battle_vs` 两个键均归 unknown 列表**——退役键已从 SCENE_VARS 删除，归 unknown 是退役链路闭合的信号，不得被 4.1 放行误写回）；显式移除 `config/narrative_config.json` 的旧 `remaining_hp` 与 `battle_vs` 键（一次性内容退役，commit 说明）
  - 2026-09-12 收尾任务：dry-run 双闸门 0 FAIL（budget 14 WARN / narrative 249 WARN）、`narrative_config.json: 43 场景写入变体池`；退役键闭合采用**比 unknown 更彻底的口径**——3.1 已删 CSV 行，退役键不进 pools，故 unknown 行为空；另以合成池 in-process 探测钉死语义（`unknown=['combat.battle_vs','combat.never_declared','combat.remaining_hp']` 且三者均未写入 config）。导入后 `git diff --stat`：`narrative_config.json +16/-1`（新增两档池 4+3 条），`adventure_config.json` 无变化；随后用 `json` 脚本显式 `pop` 旧键（`removed: ['battle_vs','remaining_hp']`），最终 diff 仅 3 个 hunk（删 2 键 + 加 2 键，16 insertions / 15 deletions）。补测：`tests/test_sync_copy_variants_admission.py`（10 条，含新键建池 / 契约不过归 skipped 且不预建空键 / 已声明无内嵌默认 → unknown / 未声明 → unknown / 双槽 config 暂缺 → unknown / 已存在键原逻辑 / 退役键参数化不可复活 / 真实 CSV 零残留）
- [x] 4.3 ConfigManager 加载零告警；`uv run python -m pytest tests/ -v` 全绿
  - 2026-09-12 收尾任务：`ConfigManager(Path('.').resolve())` 挂 WARNING 级 handler 捕获 → **0 行告警**；`combat.remaining_hp_low` 4 条 / `remaining_hp_mid` 3 条加载到位，两退役键零残留

## 5. 功能测试同步

- [x] 5.1 pvp-basic-duel/spar 断言改回锚代码结构行（`☆━━━━ 战斗开始` / `☆━━━━ .* 胜利`，并可纳入对阵行 `测试玩家\d VS 测试玩家\d`——同为代码结构行、最稳锚），替换当前为 -r0a 回滚兼容补的文学变体交替支（`收剑归鞘|抱拳一礼|…`，见用例 note）；检查其余 pvp 用例无残留依赖
  - 2026-09-12 收尾任务：两用例战报断言改为单条结构链 `☆━━━━ 战斗开始 ━━━━☆[\s\S]*测试玩家\d VS 测试玩家\d[\s\S]*气血 \d+/\d+，伤害 \d+[\s\S]*第 \d+ 回合[\s\S]*[\d,]+ 点伤害[\s\S]*☆━━━━ [^\n]*胜利`（`functional_tests/cases/pvp/pvp-basic-duel.json:101`、`pvp-basic-spar.json:77`），文学交替支全部移除。其余 pvp 用例扫描：无横幅/对阵行文案锚；仅 `pvp-effect-reflect.json` step15（`re:反震之力如数奉还|的反噬让对方自己吃了个哑巴亏`）与 `pvp-effect-vampire.json` step15（`re:气血入体|生机入体`）仍是池句锚（route A 触发效果唯一可观测信号，改锚等于降覆盖），另行上报不改
- [x] 5.2 分档覆盖（确定性设血口径，评审 Q2）：不再依赖 8000 血长局自然打低。残局档：GM 将防守方气血设为区间内值（如 4000/8000，ratio 0.5 ∈ (0.3,0.6]），一击后断言 `re:防守方名[^\n]{0,40}\d{1,3},\d{3}`（残局区间 hp≥1000 千分位必现）；濒死档：GM 设为低档内且**一击后仍存活**的值（如 2000，原则：设定值 ≤ 0.3×max_hp 且 > 单击伤害上限，具体以 fixture 实测为准），一击后断言 `re:防守方名[^\n]{0,40}\d{1,3}(,\d{3})?`（濒死区可出现 <1000 无逗号数字，不锚逗号）。千分位格式正确性由单测 2.5 钉，webtest 锚只验证「该档行出现 + 数字为代码格式化输出」；池句文本不进断言（防 -r0a/-xdl 同类文案锚静默翻红）
  - 2026-09-12 收尾任务【口径偏离，已实测校正】：任务书预设「GM 设血 → 开局 ratio=0.5」不成立——`managers/combat_manager.py:399` 的 `build_fighter_from_player` 中 `hp` 与 `max_hp` 同取 `total_attrs['hp']`，`core/gm_manager.py:713` 的 `_set_numeric_attr` 只 `setattr` 单一字段，故设血只会整段缩放，开局 ratio 恒为 1.0（已用 fixture 口径复核）。改用「长局必然穿档 + 结构锚」：保留 8000 血（约 40 回合，ratio 必数次穿 (0.3,0.6] 与 (0,0.3]），在 duel 用例追加两条分档断言——千分位形态 `re:测试玩家\d[^\n]{0,40}气血[^\n]{0,20}\d{1,3},\d{3}\s*点`（`pvp-basic-duel.json:108`）、无千分位形态 `re:测试玩家\d[^\n]{0,40}气血[^\n]{0,20}(?<![,\d])\d{1,3}\s*点`（`:113`，8000 血局下「带气血前缀的 <1000 数」只可能出自 ratio ≤ 0.3 的濒死档，证明该档真的渲染过）。两正则已本地仿真验证：命中两档池句、不命中间伤害行/面板行/`VS` 行/横幅/GM 回执（后者无「点」字）。spar 用例（2000 血速胜局）不加分档断言，理由写在用例 note
- [ ] 5.3 webtest 回归由用户手动发起后归档结果
  - 2026-09-12 收尾任务：`uv run python scripts/test_suite_ctl.py sync-cases` 已同步 55 个用例到平台目录（`data/plugin_data/astrbot_plugin_testplatform/cases/astrbot_plugin_monixiuxian2_2/`，含改造后的 pvp-basic-duel/spar）；**webtest 真实环境回归与结果归档待用户手动发起**（按 AGENTS「真实环境功能测试由用户手动发起」，AI 不主动跑用例）

## 6. 收尾

- [x] 6.1 `bd close` -hcn 与 -r0a（注明修复变更）；检查 -xdl（pvp 创建步锚文案池）是否顺带可修
- [x] 6.2 `uv run ruff format . && uv run ruff check . && uv run python -m pytest tests/ -v` 全绿
- [x] 6.3 §7 版本 checklist：metadata.yaml、README 更新日志；§14 同步 `design_docs/current-design-report.md` 战报结构段
  - 2026-09-12 收尾任务：`metadata.yaml:4` v3.17.0 → v3.17.1（patch）；`README.md` 更新日志顶部新增 v3.17.1 条目（结构行代码化 + 剩余气血分档 + 千分位 + 文案同步，遵循本仓「新版本在上」体例）；`design_docs/current-design-report.md` §4.5 战报段补「结构行（代码拼装）」与「剩余气血行阈值分档」两条子项（带 `file:line`）；`design_docs/剧情/00-剧情总骨架.md` 三处条数同步（:8/:54/:261，战斗 55→56、总量 292→293）；`/修仙帮助` 无指令变化，不动
- [ ] 6.4 `openspec validate combat-report-structure --strict` 通过，任务全部勾选（待 5.3 用户手动回归完成后由主线归档）

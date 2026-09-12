# narrative-text-config Specification

## Purpose

叙事文案配置化载体的行为契约：高频界面文案（突破/机缘/战斗/修炼结算/传承之地/秘境/历练事件）以模板与变体池形式存于 config，运行时从 config 读取渲染，改文案不需要改代码；模板插值变量有加载时机器校验。

## Requirements

### Requirement: 叙事文案配置化载体

系统 SHALL 将高频叙事文案（突破成功/失败/身死道消/保命分支、战斗说书人句式与战斗框架场景的文学描述行、战斗静态效果处理器句式与回合头、修炼闭关开始与出关结算、突破机缘掉落文案含储物戒已满分支、传承偶遇桥段）从代码迁移至 `config/narrative_config.json`（默认值存 `data/default_configs.py`，按域分片于 `data/narrative_defaults/`），运行时从配置读取渲染。灵根/体质评价大表 SHALL 迁移至独立的条目型配置文件 `config/spirit_root_descriptions.json`。迁移后修改文案 MUST NOT 需要修改代码。**例外**：战报结构行（战斗开始/胜利/平局/胶着/同归于尽的 `☆━━━━ … ━━━━☆` 横幅与 `{name1} VS {name2}` 对阵行）归代码所有，不属配置化文案（见「战报结构行代码所有」）。场景值 SHALL 支持四种形态：单模板（str）、扁平变体池（list）、按境界段分桶的变体池（dict，桶键 `通用/练气/筑基/金丹/元婴`）、双槽形态（dict，含字符串 `panel` 键且不含 `text` 键：分桶 flavor 变体池 + 单源机械面板模板）；池条目 SHALL 支持可选 `route` 标注（灵修/体修），带标注条目仅对对应路线玩家参与轮换。

双槽形态 SHALL 以"字符串类型 `panel` 键存在且场景值不含 `text` 键"为判别；`panel` 承载该场景的全部机械信息；其余桶键下为 flavor 引子变体池。渲染时 SHALL 先从 flavor 合并池（当前境界段桶 + `通用` 桶，含 route 过滤）随机取一条引子（池为空则只出面板），再渲染 panel 模板，按 `flavor + "\n" + panel` 拼装输出。flavor 引子 MUST NOT 承担机械信息表达责任——玩家所需的数值/指令/结算信息 MUST 完整来自 panel。`panel` 键存在但值非字符串、或场景值同含 `text` 键时，系统 MUST 加载告警并将整场景回退内嵌默认文案（防止机械信息静默丢失或半畸形形态）。重面板（双槽）场景的渲染调用点 SHALL 提供玩家的 `route` 与 `level_index`，使分桶与路线标注对该场景实际生效。

#### Scenario: 变体池轮换

- **WHEN** 某场景在配置中是变体池（多条文案）
- **THEN** 运行时从该场景的文案列表中随机取一条渲染；池长为 1 时行为与单模板等价

#### Scenario: 分桶池合并取用

- **WHEN** 某场景配置为按境界段分桶的变体池
- **THEN** 运行时从玩家当前境界段桶与 `通用` 桶的合并池中随机取一条；合并池为空时回退内嵌最小默认文案

#### Scenario: 路线标注过滤

- **WHEN** 某场景变体池中存在 `route` 标注为 `灵修` 的条目
- **THEN** 体修玩家的轮换池中不含该条目；无标注条目对所有路线玩家可取

#### Scenario: 改文案不改代码

- **WHEN** 运营/策划修改 `narrative_config.json` 中某场景的模板文本（不动插值变量名）
- **THEN** 重载后新文案生效，无需修改任何 Python 文件

#### Scenario: 双槽形态拼装渲染

- **WHEN** 某场景配置为双槽形态（含字符串 `panel` 键与 flavor 分桶池），且调用点提供玩家 route 与 level_index
- **THEN** 输出为"随机一条 flavor 引子（当前段桶 + 通用桶合并、route 过滤后）+ 换行 + 渲染后的 panel"，panel 中的机械变量（如属性成长、修为结算数字）完整呈现

#### Scenario: 双槽 flavor 池为空

- **WHEN** 某双槽场景的 flavor 合并池为空（未配置或被 route 过滤清空）
- **THEN** 仅渲染输出 panel 面板，不报错

#### Scenario: 缺 panel 键按普通分桶池处理

- **WHEN** 某场景值为 dict 且含分桶键但不含 `panel` 键
- **THEN** 按普通分桶池形态处理（桶键照旧参与轮换），不产生拼装行为

#### Scenario: 非字符串 panel 回退默认

- **WHEN** 某场景值含 `panel` 键但其值不是字符串（如 list/dict），或场景值同含 `text` 与 `panel` 键
- **THEN** 加载时告警并整场景回退内嵌默认文案，不进入拼装路径

#### Scenario: 双槽场景调用点提供路线与境界

- **WHEN** 双槽场景的渲染调用点执行
- **THEN** 调用点传入当前玩家的 `route` 与 `level_index`，分桶 flavor 池按该玩家境界段与路线实际参与轮换

### Requirement: 模板插值变量契约校验

系统 SHALL 在加载叙事文案配置时校验每个模板引用的插值变量名是该场景代码渲染点声明变量的子集；发现未知变量时 MUST 拒绝加载该场景模板、回退到内嵌最小默认文案，并在日志/启动输出中报错定位（场景 key 与未知变量名）。加载校验失败 MUST NOT 导致插件崩溃。双槽形态场景 SHALL 分别校验：`panel` 模板与每条 flavor 引子各自只允许引用该场景声明变量的子集；`panel` 键 MUST NOT 被当作桶键参与桶校验告警。

#### Scenario: 未知变量拒绝加载

- **WHEN** 某场景模板写了 `{damage}` 而该场景声明的变量集合只有 `{name}`、`{final_damage}`
- **THEN** 加载时报错指出场景 key 与变量名 `damage`，该场景回退默认文案，其余场景不受影响

#### Scenario: 双槽 flavor 越界变量拒绝加载

- **WHEN** 某双槽场景的某条 flavor 引子引用了未声明变量
- **THEN** 加载时报错定位到该 flavor 条目所在桶与变量名，该场景回退内嵌默认文案

#### Scenario: 双槽 panel 校验

- **WHEN** 某双槽场景的 `panel` 模板引用了未声明变量
- **THEN** 加载时报错定位到 `panel` 与变量名，该场景回退内嵌默认文案

### Requirement: 叙事文案换行所有权

面板与消息由「标题行 + 模板 + 若干可选槽位文本」逐段拼装，换行 SHALL 只有一个所有权层：**代码（调用侧或 panel 模板）**。叙事文案（`data/narrative_defaults/*` 内嵌默认、`config/narrative_config.json` 变体、`copy_variants.csv` 稿子）MUST NOT 用首尾空白或换行表达排版意图；文案**内部**换行（多行正文）不受此限。

渲染取用层（`utils/narrative_text.py`）SHALL 剔除文案条目的首尾空白，使旧稿或不合规稿子无法再改变面板行结构；剔除实际发生时 MUST 输出一次 WARN（每场景每进程至多一次，文案渲染位于战斗等高频路径），指出场景 key 与契约位置，且 MUST NOT 回退内嵌默认（与「形态不符回退」既有规则相对：仅 trim 不构成回退）。剔除后为空串的条目 SHALL 被丢弃、不入选池——空白壳不携带任何内容，丢弃不算「trim 回退」；若整池因此为空，按既有空池规则处理（普通场景回退内嵌默认，双槽场景只出 panel）。可选槽位的换行 MUST 落在调用侧的条件分支内（槽位为空时不产生空行）。

#### Scenario: 稿子自带前导换行不再拆坏面板

- **WHEN** 某场景的变体文案写成以 `\n\n` 起头，渲染点为 `标题 + 槽位`
- **THEN** 渲染结果等于剔除边缘空白后的正文，与不带换行的稿子完全一致；日志出现一条指出该场景 key 的 WARN

#### Scenario: 纯空白条目不渲染空消息

- **WHEN** 某场景的池条目剔除首尾空白后为空串
- **THEN** 该条目不入选池；若整池因此为空，普通场景回退内嵌默认、双槽场景只出 panel——任何路径都不渲染空消息

#### Scenario: 空槽位不留空行

- **WHEN** 可选槽位对应场景未命中（值为空串）
- **THEN** 渲染输出不含该槽位带来的空行，面板标题与后续段落之间恰一个分隔换行

#### Scenario: 内嵌默认全量符合契约

- **WHEN** 遍历 `DEFAULT_NARRATIVE_CONFIG` 全部叶子 `text`
- **THEN** 每条均满足 `text == text.strip()`（panel 模板除外——它就是换行的拥有者）

### Requirement: 传承之地文案单源

传承之地桥段的文案 SHALL 在 `narrative_config.json` 中只有一个模板簇（按触发方式×结果拆分为偶遇胜/负、领取胜/负四个场景模板——载体池语义为随机轮换而非结果选择，胜负文案必须分场景），历练/秘境/宗门三处触发点 MUST 引用同一配置来源。

#### Scenario: 三处触发同一模板簇

- **WHEN** 玩家分别从历练、秘境（偶遇制）与宗门（领取制）场景触发传承之地桥段
- **THEN** 三处文案来自同一配置模板簇下各自场景的模板（允许各自插值不同变量、领取制含宗门机制行），修改簇内模板即对应场景同时生效

### Requirement: 秘境描述与探索事件配置化

`rift_config.json` 的每个秘境条目 SHALL 支持可选 `description` 字段（入口叙事）与结算叙事位；秘境探索事件的文案变体池 SHALL 存于 rift 配置而非代码。存量配置缺少新字段时 MUST 正常加载（description 视为空），不得报错。

#### Scenario: 秘境入口展示描述

- **WHEN** 某秘境配置了 `description`
- **THEN** 秘境列表/入口界面展示该描述文本

#### Scenario: 存量配置兼容

- **WHEN** `rift_config.json` 中存在无 `description` 字段的旧条目
- **THEN** 加载正常进行，该秘境描述按空处理

#### Scenario: 探索事件池外移

- **WHEN** 修改 rift 配置中的探索事件变体池
- **THEN** 重载后秘境探索事件文案按新配置出，无需修改代码

### Requirement: 历练事件文案分桶载体

`adventure_config.json` 的事件条目 SHALL 支持可选 `tags`（题材标签位）与 `desc_variants`（按境界段分桶的文案变体池，桶键含 `通用` 与境界段名）。运行时 MUST 按玩家当前境界段从对应段桶与 `通用` 桶的合并池中随机取一条文案渲染；当前段无桶或合并池为空时 MUST 回落该事件的 `desc` 字段。存量缺少新字段的事件条目 MUST 正常加载（`tags` 视为空、直接使用 `desc`）。事件数值字段（`exp_mult`/`gold_mult`/`item_chance`/`bonus_progress` 等）MUST NOT 因文案分桶而改变。

#### Scenario: 按境界段出文案

- **WHEN** 玩家触发某历练事件且该事件配置了 `desc_variants`
- **THEN** 文案从玩家当前境界段桶与 `通用` 桶的合并池中随机取一条；合并池为空时回落 `desc`

#### Scenario: 存量事件兼容

- **WHEN** `adventure_config.json` 中存在无 `tags`/`desc_variants` 字段的旧事件条目
- **THEN** 加载正常进行，该事件按原 `desc` 单条文案出，数值行为不变

#### Scenario: 改事件文案不改代码

- **WHEN** 策划在某事件的 `desc_variants` 桶中增删文案（不动数值字段）
- **THEN** 重载后对应境界段玩家看到新文案池轮换，无需修改任何 Python 文件

### Requirement: 战报结构行代码所有

战报的结构行——五条横幅（战斗开始、胜利、平局、战斗胶着平局、同归于尽，恢复 `☆━━━━ … ━━━━☆` 形态）与对阵行（`{name1} VS {name2}` 原始形态）——SHALL 由战斗引擎代码拼装，胜者名与对阵双方名由代码插值。结构行 MUST NOT 依赖叙事配置——配置缺失/回退/文案迭代均不得让战报失去起止标志与对阵信息。`battle_opening`/`battle_victory`/`battle_draw`/`battle_draw_stalemate`/`battle_mutual_destruction` 五个叙事场景 SHALL 降级为文学描述行：开局场景的描述行拼装在「横幅 + 对阵行」之后、属性面板之前；结局场景的描述行追加在结局横幅之后；配置池非空时随机取一条，配置池缺失或为空时按既有空池规则回退内嵌最小默认描述行。`battle_vs` 场景随对阵行代码化退役（代码不再引用，配置键与内嵌默认移除）。描述行渲染 MUST NOT 抛错或阻断战报（沿用叙事渲染既有降级契约：format 失败时降级输出原始模板文本；该路径由加载时变量契约校验保证不可达）。

#### Scenario: 结构行恒定在场

- **WHEN** 任意一场战斗结算产出战报（含 config 中五个框架场景被清空或回退的极端情况）
- **THEN** 战报首行附近存在 `☆━━━━ 战斗开始 ━━━━☆` 与紧随的 `{name1} VS {name2}` 对阵行，结尾存在与结局对应的 `☆━━━━ … ━━━━☆` 横幅（胜利横幅含胜者名），无论叙事配置如何变化

#### Scenario: 文学描述行可选

- **WHEN** 某框架场景的文案池非空
- **THEN** 战报追加一条随机文学描述行（开局场景位于「横幅 + 对阵行」之后、属性面板之前，结局场景位于结局横幅之后）；配置池缺失/为空时回退内嵌最小默认描述行；描述行渲染异常不抛错、不阻断战报，横幅始终在场

### Requirement: 剩余气血行阈值分档

命中后的剩余气血描述行 SHALL 按防守方气血比例（`hp / max_hp`）分档：比例高于 mid 阈值时 MUST NOT 输出该行（降噪）；比例在 `(low, mid]` 区间时输出 `remaining_hp_mid`（残局）场景文案；比例在 `(0, low]` 区间时输出 `remaining_hp_low`（濒死）场景文案；防守方气血归零时 MUST NOT 输出该行（死亡由结局横幅表达，濒死文案不描述死者）。两个阈值 SHALL 可在战斗配置中调整（默认 mid=0.6、low=0.3）。`{remaining_hp}` 插值 SHALL 由代码格式化为千分位字符串（如 `1,241`），文案 MUST NOT 收到裸数字。旧 `remaining_hp` 场景退役：代码不再引用，配置与内嵌默认中的该场景键随本变更移除。

#### Scenario: 高血量不输出

- **WHEN** 防守方受击后气血比例高于 mid 阈值
- **THEN** 战报不追加任何剩余气血描述行

#### Scenario: 残局与濒死分档

- **WHEN** 防守方气血比例落入 `(low, mid]` 区间
- **THEN** 从 `remaining_hp_mid` 池取文案；落入 `(0, low]` 时从 `remaining_hp_low` 池取文案；两档文案语义与各自信血量区间一致

#### Scenario: 千分位格式

- **WHEN** 防守方剩余气血为 1241
- **THEN** 文案收到的 `{remaining_hp}` 为 `1,241`，渲染结果中不出现裸 `1241`

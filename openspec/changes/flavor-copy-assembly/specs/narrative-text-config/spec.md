## MODIFIED Requirements

### Requirement: 叙事文案配置化载体

系统 SHALL 将高频叙事文案（突破成功/失败/身死道消/保命分支、战斗说书人句式与战斗框架收束语、战斗静态效果处理器句式与回合头、修炼闭关开始与出关结算、突破机缘掉落文案含储物戒已满分支、传承偶遇桥段）从代码迁移至 `config/narrative_config.json`（默认值存 `data/default_configs.py`，按域分片于 `data/narrative_defaults/`），运行时从配置读取渲染。灵根/体质评价大表 SHALL 迁移至独立的条目型配置文件 `config/spirit_root_descriptions.json`。迁移后修改文案 MUST NOT 需要修改代码。场景值 SHALL 支持四种形态：单模板（str）、扁平变体池（list）、按境界段分桶的变体池（dict，桶键 `通用/练气/筑基/金丹/元婴`）、双槽形态（dict，含字符串 `panel` 键且不含 `text` 键：分桶 flavor 变体池 + 单源机械面板模板）；池条目 SHALL 支持可选 `route` 标注（灵修/体修），带标注条目仅对对应路线玩家参与轮换。

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

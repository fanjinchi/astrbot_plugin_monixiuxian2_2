# narrative-text-config Specification

## Purpose

叙事文案配置化载体的行为契约：高频界面文案（突破/机缘/战斗/修炼结算/传承之地/秘境/历练事件）以模板与变体池形式存于 config，运行时从 config 读取渲染，改文案不需要改代码；模板插值变量有加载时机器校验。

## Requirements

### Requirement: 叙事文案配置化载体

系统 SHALL 将高频叙事文案（突破成功/失败/身死道消/保命分支、战斗说书人句式与战斗框架收束语、战斗静态效果处理器句式与回合头、修炼闭关开始与出关结算、突破机缘掉落文案含储物戒已满分支、传承偶遇桥段）从代码迁移至 `config/narrative_config.json`（默认值存 `data/default_configs.py`，按域分片于 `data/narrative_defaults/`），运行时从配置读取渲染。灵根/体质评价大表 SHALL 迁移至独立的条目型配置文件 `config/spirit_root_descriptions.json`。迁移后修改文案 MUST NOT 需要修改代码。场景值 SHALL 支持三种形态：单模板（str）、扁平变体池（list）、按境界段分桶的变体池（dict，桶键 `通用/练气/筑基/金丹/元婴`）；池条目 SHALL 支持可选 `route` 标注（灵修/体修），带标注条目仅对对应路线玩家参与轮换。

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

### Requirement: 模板插值变量契约校验

系统 SHALL 在加载叙事文案配置时校验每个模板引用的插值变量名是该场景代码渲染点声明变量的子集；发现未知变量时 MUST 拒绝加载该场景模板、回退到内嵌最小默认文案，并在日志/启动输出中报错定位（场景 key 与未知变量名）。加载校验失败 MUST NOT 导致插件崩溃。

#### Scenario: 未知变量拒绝加载

- **WHEN** 某场景模板写了 `{damage}` 而该场景声明的变量集合只有 `{name}`、`{final_damage}`
- **THEN** 加载时报错指出场景 key 与变量名 `damage`，该场景回退默认文案，其余场景不受影响

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

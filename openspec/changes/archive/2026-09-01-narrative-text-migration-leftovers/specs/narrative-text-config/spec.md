## MODIFIED Requirements

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

#### Scenario: 遗留句式外移后行为不变

- **WHEN** 突破机缘掉落遇储物戒已满，或战斗流程出现回合头与静态效果句式（dot 侵蚀结算/反击结算/治疗结算/dot 附着/叠加上限拒绝/免死庇护授予）
- **THEN** 文案从 `narrative_config.json` 对应场景读取渲染，输出与外移前逐字一致，数值与流程逻辑不变

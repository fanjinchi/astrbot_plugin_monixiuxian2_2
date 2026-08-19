# Design: add-sect-functional-tests

## Context

- 被测功能由配套 change `add-default-sects-and-sect-growth` 交付（默认宗门/建设/师承/职阶晋升/联动过滤/绑定物回收），其行为契约见该 change 的 `specs/sect-system/spec.md` 与 `specs/skill-system/spec.md`，本 design 不复述。
- 测试资产规范与流程已定：`functional_tests/README.md`（用例源文件在 `cases/<domain>/`，`name` 全局唯一等于文件名，`test_suite_ctl.py sync-cases/run/export` 闭环）。
- 平台能力边界：`functional_tests/platform-gap-report.md`——RNG seed、DB 直断、时间加速为 Unsupported/Partially；指令链路 + 消息断言 + GM 指令 + fixture 写库为可用铺底手段。
- 现有 fixture：`scripts/test_suite_ctl.py fixture --profile pvp` 向专用测试实例写固定测试 ID（900000001-3）的玩家数据。

## Goals / Non-Goals

**Goals:** 宗门新玩法全链路用例在真实管线可跑、可归因（失败能定位到具体契约条款）、可回归（`--tag sect`）。
**Non-Goals:** 不修玩法 Bug（bd 登记）；不为毁灭/重建（二期）写用例；不扩展测试平台本身（缺口登记到 gap report）。

## Decisions

### D1: 用例按"契约条款 → 用例"映射编写

每条 sect-system spec Requirement 至少一个用例，用例 `description` 标注对应 Requirement 名，失败时可直接回查契约。用例清单（初拟，实施时以最终指令名为准）：

| 用例（`cases/sect/*.json`） | 覆盖契约 |
|---|---|
| `sect-default-visible` | 默认宗门播种可见 + 同名建宗拒绝 |
| `sect-join-level-gate` | 拜入境界区间校验（区间内成功/超区间拒绝） |
| `sect-master-task-chain` | 师承链阶段顺序推进与奖励文案 |
| `sect-construction` | 建设任务结算 + 建筑升级 + 加成提示 |
| `sect-promotion` | 晋升双门槛（达标成功/缺一项拒绝）+ 签到福利加发 |
| `sect-leave-reclaim` | 出师：宝物回收、贡献清零、已习得功法保留可用 |
| `sect-rejoin-retain` | 改换门庭后原宗门功法仍可使用、不可赠予他人 |
| `sect-content-filter` | 宗门悬赏/秘境的成员过滤 |
| `sect-shop-discount` | 职阶折扣结算 |

### D2: 状态铺底用 fixture profile，不用时间加速

晋升门槛需要的贡献/境界不靠真实刷取：扩展 `test_suite_ctl.py fixture` 增加 `sect` profile（固定测试 ID 预置贡献点、境界、宗门归属、绑定物），沿用 pvp profile 的"仅专用测试实例 + 执行前确认"安全约束。无 fixture 的路径（如建设任务）用真实指令循环最小次数验证。

### D3: 随机性断言降级为消息模式

师承奖励含随机领悟机会：不断言"必然领悟"，断言奖励结算消息出现且贡献数值正确；概率性结果按 gap report 惯例标注 sampled/deterministic。

### D4: 与实施 change 的协作时序

用例 JSON 可与实施并行起草（依据 spec 契约），但必须待 `add-default-sects-and-sect-growth` 实施完成、插件热重载后再执行与归档；指令名以实施最终代码为准，起草时按 design_docs/sect-system-design.md §4 的指令约定填写。

## Risks / Trade-offs

- [指令名在实施中调整导致用例失配] → 用例集中在 `cases/sect/` 单目录，执行前统一核对 main.py 命令常量。
- [fixture 误伤正式数据] → 复用现有 fixture 脚本的确认与实例隔离约束，不新开写入路径。
- [宗门冷却（任务 1h CD）阻塞用例] → 用例间使用不同测试玩家分摊；确需绕过的走 fixture 清 CD（现有 pvp profile 已有清冷却先例）。

# Tasks: add-sect-functional-tests

## 1. 准备（依赖确认）

- [ ] 1.1 确认配套 change `add-default-sects-and-sect-growth` 已实施完成；核对 `main.py` 最终指令常量与 design_docs/sect-system-design.md §4 约定是否一致，不一致以代码为准
- [ ] 1.2 通读 `functional_tests/README.md`、`functional_tests/platform-gap-report.md` 与测试平台 SKILL.md（`.agents/skills/testing-astrbot-plugins-via-webtest`），确认平台 `/api/status` 可用

## 2. Fixture 扩展

- [ ] 2.1 `scripts/test_suite_ctl.py fixture` 新增 `sect` profile：固定测试 ID 预置宗门归属、贡献点、境界、宗门绑定功法/宝物，保留"仅专用测试实例 + 执行前确认"安全约束
- [ ] 2.2 用 fixture 在测试实例验证写库生效（玩家属性/储物戒/绑定标记/冷却清除）

## 3. 用例编写（`functional_tests/cases/sect/`，JSON 兼容 `loader.validate_case`，name=文件名全局唯一）

- [ ] 3.1 `sect-default-visible`：默认宗门在宗门列表可见、同名建宗被拒绝
- [ ] 3.2 `sect-join-level-gate`：境界区间内拜入成功、超区间拒绝
- [ ] 3.3 `sect-master-task-chain`：师承任务链阶段顺序推进、奖励结算消息、长老署名文案
- [ ] 3.4 `sect-construction`：建设任务结算贡献/资材、建筑升级、成员加成提示
- [ ] 3.5 `sect-promotion`：晋升双门槛（达标/缺贡献/缺境界）+ 签到职阶灵石加发
- [ ] 3.6 `sect-leave-reclaim`：出师时宗门之宝回收、贡献清零、已习得绑定功法保留可用
- [ ] 3.7 `sect-rejoin-retain`：改换门庭成功，原宗门功法仍可使用且不可赠予他人
- [ ] 3.8 `sect-content-filter`：宗门悬赏/秘境仅本宗成员可见可入，全局内容不受影响
- [ ] 3.9 `sect-shop-discount`：职阶折扣结算消息与价格校验
- [ ] 3.10 全部用例打 `sect` 标签，`description` 标注对应 spec Requirement 名

## 4. 执行与归档

- [ ] 4.1 `uv run python scripts/test_suite_ctl.py sync-cases` 同步并校验通过
- [ ] 4.2 热重载插件后 `uv run python scripts/test_suite_ctl.py run --tag sect` 全量执行
- [ ] 4.3 失败用例归因：玩法 Bug 用 `bd` 登记（不在本 change 修代码）；用例自身问题修正后重跑
- [ ] 4.4 `uv run python scripts/test_suite_ctl.py export --target sect` 归档结果到 `functional_tests/results/<date>_sect/`
- [ ] 4.5 触及的平台能力缺口登记到 `functional_tests/platform-gap-report.md`

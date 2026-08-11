# Tasks: 读修仙小说原文提取内容素材

参考 spec（novel-reading-extraction）的验收标准与 design.md 的决策（源策略 D1、采样策略 D2、压缩协议 D3、映射约定 D5）。

## 1. 准备：源探测与工具链验证

- [x] 1.1 探测 10 本小说（凡人修仙传、仙逆、遮天、诛仙、一念永恒、我师兄实在太稳健了、大奉打更人、诡秘之主、道诡异仙、佛本是道）的免费文本源，建立"书名 → 主源/备用源 URL"清单并验证可用性
- [x] 1.2 验证抓取工具链：`bash` curl 整本下载（GitHub txt 仓库）与 `fetch_content` 逐章正文抓取（笔趣阁镜像），确认反爬对策（UA、多镜像）

## 2. 全本档持续阅读（3 本；每本：获取全文 → 分批阅读（每批 50-150 章）→ 增量写入 extract 并更新进度头 → compress 原文 → 跨会话续读直至全书读完）

- [x] 2.1 《凡人修仙传》→ `extract-fanren.md`（**全本 2446 章已读完**，进度头 2446/2446，无未读章节）
- [x] 2.2 《仙逆》→ `extract-xianni.md`（**全本 2088 章+后记已读完**，进度头 2088+后记，quanben URL 2031 为上限）
- [x] 2.3 《遮天》→ `extract-zhetian.md`（**全本 1822 章+大结局已读完**，进度头 1822+大结局，quanben URL 1818 为上限）

## 3. 部分档（7 本；每本：关键章节精读 + 网络搜索总结各维度设定 → 写 extract-<slug>.md → 登记 README，条目标注来源：原文章节/网络调研）

- [x] 3.1 《诛仙》→ `extract-zhuxian.md`
- [x] 3.2 《一念永恒》→ `extract-yinian.md`
- [x] 3.3 《我师兄实在太稳健了》→ `extract-wenjian.md`
- [x] 3.4 《大奉打更人》→ `extract-dafeng.md`
- [x] 3.5 《诡秘之主》→ `extract-guimi.md`
- [x] 3.6 《道诡异仙》→ `extract-daogui.md`
- [x] 3.7 《佛本是道》→ `extract-foben.md`

## 4. 收尾：质量检查与汇总

- [x] 4.1 全量验收：10 份 extract 文件均满足 spec 要求（全本档 3 本无未读 gap、部分档 7 本条目带来源标注；命名素材带章节与原文引用、玩法映射标签），design_docs/README.md 资料清单登记完整
- [x] 4.2 提炼汇总：从 10 本素材中归纳"可复用内容/文本模板清单"（突破、渡劫、奇遇、宗门事件等），写入 novel-research/README.md 设计要点，供后续 content-design 使用

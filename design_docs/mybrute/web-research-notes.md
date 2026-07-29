# Research: My Brute 游戏设计分析

## Summary
My Brute（Motion-Twin 于 2008 年推出的 Flash 页游，区域版称 La Brute、El Bruto）是一款以"完全自动战斗 + 随机 Build"为核心的浏览器格斗模拟游戏。玩家仅能创建角色、选择对手、围观 30 秒左右的自动战斗；所有属性、武器、技能、宠物均由升级随机掉落。其设计亮点在于把"无法操作"转化为低门槛的观赏性体验，用每日战斗次数上限、师徒邀请链和锦标赛制造留存与传播，是后世 auto-battler / idle RPG 设计中常被提及的前身之一。

## Findings

### 1. 核心机制解析

1. **四主属性体系** — 战斗结果由 Strength（物伤/大部分武器伤害）、Agility（闪避/格挡/投掷武器伤害）、Speed（攻击间隔/多动概率/先手倾向）、Endurance（HP）决定。升级时通常提供 +3 单一主属性或 +2/+1 组合选项；部分技能（Herculean Strength、Feline Agility、Lightning Bolt 等）还会百分比放大对应属性成长。 [Source](https://mybrutemuxxu.fandom.com/wiki/Stats)
2. **武器与隐藏伤害** — 游戏共有约 26 种武器，分为 fast / heavy / long / thrown / sharp 等类别。武器在战斗中可被掏出、投掷、击落或丢弃；非投掷武器被投出后本场不可再用。Damage 是一个隐藏属性，所有武器与空手攻击的伤害均随 Strength 提升；投掷武器主要受 Agility 加成，Strength 影响较小。 [Source](https://mybrutemuxxu.fandom.com/wiki/Weapons)
3. **战斗完全自动化** — 玩家唯一可做的战前决策是挑选对手；进入战斗后角色自动进行攻防、换武器、放技能、宠物协同。Speed 决定攻击间隔与连击频率，Agility 影响闪避/格挡概率，但具体数值公式并未被官方披露。 [Source](https://mybruteguide.wordpress.com/)
4. **技能与宠物池** — 技能共 42 种，涵盖直接伤害、Debuff（Sabotage 摧毁武器、Thief 窃取武器）、控制（Hypnosis 策反宠物）、被动加成等。宠物（Dog / Wolf / Bear）独立攻击并拥有独立 HP，稀有度与 HP 惩罚不同：Dog 最常见、减 10 HP，Wolf/Panther 与 Bear 稀有度低于 1% 且分别减 23 HP 与更多 HP。 [Source](https://mybrute.fandom.com/wiki/Pets)
5. **角色生成基于用户名 seed** — 角色外观、初始属性、潜在武器/技能/宠物由玩家输入的用户名字符决定，可视为一种伪随机种子；创建后成长路径即"固定"，无法重置。社区普遍称之为"roll of the dice"，没有通过拜师锁定特定奖励的捷径。 [Source](https://www.mobygames.com/game/40183/my-brute/)

### 2. 设计哲学

6. **"非游戏"体验作为卖点** — 2009 年的设计评论《The Future of Non-Interactivity》指出，My Brute 的魅力恰恰在于"它不是一款游戏"：玩家输入名字、选个发型，然后看 30 秒戏剧化战斗。这种极低交互门槛让它更像"可观看的随机生成器"或"数字斗兽场"，适合社交分享与碎片时间。 [Source](https://www.popten.net/2009/05/the-future-of-non-interactivity/)
7. **随机 Build 驱动收集与重 roll** — 每级升级随机奖励武器/技能/宠物/属性，加上角色创建时的随机种子，形成强烈的"再开一个号"冲动。玩家社群把这种追求极品初始配置的行为称为 rerolling / brute hunting。 [Source](https://mybruteguide.wordpress.com/)
8. **"不能操作"降低负罪感、提升叙事空间** — 自动战斗把失败归因于 RNG 与 Build，而非玩家操作；同时动画演出（格挡、连击、武器被击飞、宠物突袭）为每场战斗提供了小型叙事。 [Source](https://news.macgasm.net/miscellaneous-news/my-brute-fighting-without-fighting/)
9. **Bulkypix CEO 的评价** — iPhone 版移植负责人 Vincent Dondaine 将 La Brute 描述为"à la fois casual et hardcore, une espèce d'alchimie magique avec toutes les typologies de joueurs"（同时休闲与硬核，对所有玩家类型都有一种神奇的炼金效应），并认为它是完美的移动端每天 10–15 分钟体验。 [Source](https://www.pocketgamer.fr/articles/001095/interview-bulkypix-nous-parle-de-la-brute-iphone/)

### 3. 留存与传播设计

10. **每日战斗上限** — 原版 Web 通常每日 3 场（部分版本 5 场），创建角色当天可打 6 场。iPhone 免费 Lite 版限制为每日 3 场，完整版 5 场。该限制强制玩家次日回流，同时把单局战斗仪式化。 [Source](https://en.wikipedia.org/wiki/My_Brute)
11. **师徒（Pupil/Master）邀请裂变** — 玩家通过分享 `brutename.mybrute.com` 链接邀请新用户，对方创建首个 Brute 后成为其 pupil。早期版本中 master 可获得 +1 XP，并在 pupil 每次升级时再获 +1 XP；后期版本改为 pupil 主要提升 dojo rank 而非直接给 XP。社群攻略明确把"广收门徒"列为主要升级路径之一。 [Source](https://bestbrute.fandom.com/wiki/Master)
12. **锦标赛结构** — 存在 Daily tournament（手动报名）与 Global tournament（前一日报名者可自动参加）。每场锦标采用单败淘汰，每轮多为 4 局 3 胜或 7 局 4 胜；16/32 人规模常见。获胜每场次日结算 1 XP，可与日常 Arena 经验叠加。 [Source](https://mybrute.eternaltwin.org/wiki)
13. **社群举办的锦标赛形式** — 官方/半官方之外，玩家社区也组织 round-robin + single-elimination 混合赛、分组循环赛等，规则包括等级限制、属性主题限制、随机 seed 等，说明锦标赛机制天然适配 UGC 赛事。 [Source](https://mybrute.forumotion.com/t9902-tournament-structure)

### 4. 同类与衍生

14. **区域版本差异** — La Brute（法语版）、El Bruto（西班牙语版）与 My Brute（英语/国际版）本质为同一套玩法与资产的不同语言部署，角色数据不互通。iPhone 移植版也选择与 Web 完全隔离的新服务器，让所有移动端玩家从零开始竞争。 [Source](https://vgtimes.com/games/my-brute/)
15. **官方后续与停运** — Flash 版持续运营至 2020 年官方停止支持，服务器最终于 2023 年 11 月关闭。Motion Twin 后将重心转向 Dead Cells 等买断制作品，并在 GitHub 上以非商业授权开源了部分 Web 游戏资料（含 Muxxu La Brute 2010 相关数据）。 [Source](https://github.com/motion-twin/WebGamesArchives)
16. **粉丝复刻与致敬作** — 直接受 My Brute 启发的项目包括：
    - **Eternaltwin / MyBrute**：非商业民间私服与 preservation 项目，复刻原版机制并维护 wiki。 [Source](https://eternaltwin.org/)
    - **La Brute Legacy**：基于 Three.js 的 3D voxel 浏览器重制版，保留自动战斗核心。 [Source](https://discourse.threejs.org/t/la-brute-legacy-a-browser-fighting-game-with-3d-voxel-combat-all-on-a-single-webgl-canvas/92897)
    - **Brutal Arena**：itch.io 上的 idle-fighter，强调异步 PvP、段位天梯与无尽 Gauntlet。 [Source](https://screwedviasonic.itch.io/brutal-arena)
    - **MyBrute Arena（Vibe30-day15）**：现代 vibe-coding 重制 demo，用于展示角色创建 + 自动战斗 + 锦标赛模板。 [Source](https://github.com/nunocoracao/Vibe30-day15-mybrute)
    - **TuiTui8**：早期中文像素/动漫风仿作（社区普遍视为 rip-off）。 [Source](https://www.elitepvpers.com/forum/browsergames/282828-tuitui8-chinese-mybrute-ripoff-has-everything.html)
17. **对 auto-battler 品类的历史位置** — 多个来源将 My Brute 视为 2009 年前后"自动战斗 + Build"模式的代表，早于 Dota Auto Chess（2019）与 TFT 带火的 auto battler 概念。其设计遗产更多体现在"战前构筑 / 战中旁观"的混合体验，而非棋盘站位。 [Source](https://brutoria.com/post-elbruto-en)

## Sources

### Kept
- **Mybrute Muxxu Wiki – Stats** (https://mybrutemuxxu.fandom.com/wiki/Stats) — 主属性与技能加成的最系统整理。
- **Mybrute Muxxu Wiki – Weapons** (https://mybrutemuxxu.fandom.com/wiki/Weapons) — 武器机制（掏出/投掷/丢弃/击落）与分类。
- **My Brute Wiki – Pets** (https://mybrute.fandom.com/wiki/Pets) — 宠物属性、稀有度与 HP 惩罚。
- **My Complete Guide to Mybrute** (https://mybruteguide.wordpress.com/) — 四属性定义与随机 Build 心理说明。
- **Smashboards – MyBrute Comprehensive Guide** (https://smashboards.com/threads/mybrute-a-comprehensive-guide-explanation.267956/) — 日常战斗上限、师徒经验、升级机制。
- **MobyGames – My Brute (2008)** (https://www.mobygames.com/game/40183/my-brute/) — 用户名决定随机生成、自动战斗的核心描述。
- **Wikipedia – My Brute** (https://en.wikipedia.org/wiki/My_Brute) — 版本差异、每日战斗次数、发布时间线。
- **Popten – The Future of Non-Interactivity** (https://www.popten.net/2009/05/the-future-of-non-interactivity/) — "非游戏"设计观点的经典评论。
- **Pocket Gamer France – Bulkypix 采访** (https://www.pocketgamer.fr/articles/001095/interview-bulkypix-nous-parle-de-la-brute-iphone/) — 官方对"休闲+硬核"定位与 iPhone 版隔离新服的解释。
- **Pocket Gamer – My Brute iPhone 3 天 26 万场战斗** (https://www.pocketgamer.com/my-brute/my-brute-sees-260-000-fights-in-three-days-on-iphone/) — iPhone 版数据与排行榜上线。
- **Eternaltwin – MyBrute Wiki** (https://mybrute.eternaltwin.org/wiki) — 锦标赛、段位、日常战斗奖励机制（民间复刻但尽量忠实原版）。
- **Forumotion – Tournament Structure** (https://mybrute.forumotion.com/t9902-tournament-structure) — 玩家锦标赛赛制细节。
- **Brutoria – What happened to My Brute?** (https://brutoria.com/post-elbruto-en) — 历史影响与克隆生态。
- **Motion Twin Web Games Archives GitHub** (https://github.com/motion-twin/WebGamesArchives) — 官方 Web 游戏资料存档列表（含 Muxxu La Brute 2010）。
- **Three.js Forum – La Brute Legacy** (https://discourse.threejs.org/t/la-brute-legacy-a-browser-fighting-game-with-3d-voxel-combat-all-on-a-single-webgl-canvas/92897) — 现代 3D 重制说明。
- **itch.io – Brutal Arena** (https://screwedviasonic.itch.io/brutal-arena) — 当代 brute-like 设计变体。

### Dropped
- **多数 forumotion 技能讨论帖** — 多为玩家猜测与 anecdotal，未经过官方验证，作为未证实传言仅少量引用。
- **bestbrute.fandom.com 部分页面** — 信息较零散且与主 wiki 重复。
- **YouTube / 攻略视频** — 时间成本高、可验证性差，未采用。
- **Grokipedia / 自动生成的游戏百科** — 内容多为 Wikipedia 改写，可信度低。

## Gaps

1. **精确战斗公式未公开**：Strength→Damage 的系数、Agility→闪避率、Speed→多动概率等均为社区推测，未见官方公式或源代码证实。官方开源仓库仅提供资料/数据，未提供核心战斗源码（未证实）。
2. **技能触发概率与武器掉落概率**：42 种技能、26 种武器的稀有度/权重表未见官方披露，社区 tier list 多为经验统计。
3. **早期与后期版本差异**：师徒经验、每日场次、锦标赛规则在不同时期/不同语言区存在调整，但具体版本日志难以获取。
4. **经济系统细节**：原版是否存在内购、广告或道具商城，公开资料说法不一，本简报未深入涉及。

### 建议下一步
- 若需验证机制，可尝试对 Motion-Twin Web Games Archives 中 Muxxu La Brute 2010 数据做静态分析（仓库 1.25 GB，需下载后筛选 Haxe/ActionScript 战斗逻辑）。
- 可进一步研究 Eternaltwin 服务端实现（GitLab），其复刻代码可能包含对原版公式的最佳推断。

## 未证实传言标注
- "Wolf 与 Bear 获得概率低于 1%"：来源为玩家 wiki，未经验证。
- "用户名字符直接 seed 角色属性"：官方描述为"基于用户名随机生成"，但是否为纯 deterministic seed 未见源码证实。
- "防御技能（Armure / Extra-thick Skin）为固定减伤或按武器类型减伤"：社区存在多种互相矛盾的公式假设，均未证实。

---

## Supervisor coordination
无需额外决策，研究任务已完成，结果已写入指定路径。

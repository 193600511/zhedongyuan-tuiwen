<div align="center">
  <img src="_icon.png" width="96" height="96" alt="zhedongyuan-tuiwen">
  <h1>浙东院推文 skill（zhedongyuan-tuiwen）</h1>
  <p>浙江东方职业技术学院公众号推文<br><b>排版体检 · 五维评分 · 读稿点评 · 自动优化 · 标准出稿</b></p>
  <p>
    <img alt="license" src="https://img.shields.io/badge/license-MIT-2f6fed">
    <img alt="python" src="https://img.shields.io/badge/python-3.8%2B-3776ab">
    <img alt="deps" src="https://img.shields.io/badge/dependencies-0-1f9d55">
    <img alt="skill" src="https://img.shields.io/badge/agent--skill-compatible-2870a8">
    <img alt="baseline" src="https://img.shields.io/badge/calibrated%20on-342%20articles-e08a2d">
  </p>
</div>

---

> 一个开箱即用的 Agent Skill（WorkBuddy / [Agent Skills 规范](https://agentskills.io)）。规范出处：《采编部教程》+ **342 篇历史已发布推文实证**（评分基线、样式库、组件库全部从真实存档中挖掘标定）。

---

## ✨ 功能总览

| 模式 | 回答的问题 | 入口 |
|---|---|---|
| ① 排版体检 | 这篇有没有违规？ | `check_article.py` |
| ② 五维评分 | 这篇好不好、差在哪？ | `score_article.py` |
| ③ 读稿点评 | 按读者视角看，观感如何？ | `render_preview.py` + 评分 |
| ④ 自动优化 | 不合规的地方帮我修掉 | `auto_fix.py` |
| ⑤ 标准出稿 | 直接产出一篇合规推文 | SKILL.md 模式三 |

**特色：**

- 🎯 **稿型自适应评分**：新闻 / 预告 / 通知 / 风景 / 人物五类各用各的尺子（散文不查信息密度、预告不查导语长度），342 篇标定识别准确率抽检一致
- 👁 **真机读稿点评**：先把文章按手机宽度（375px / 812px 一屏）渲染成公众号文章页，逐屏看完再说话——点评全部是"这一屏只有一句话""字突然大了一圈"这样的观感语言，代码属性只作佐证
- 🔧 **自动优化闭环**：修完自动重跑体检 + 评分，输出前后对比；满分稿过一遍保证零改动零降分
- 🚫 **不越界**：只动可客观判定的事实（字号/行距/缺项/占位符），不碰文风；照片取舍、署名、病句留给编辑，姓名绝不臆造

## 📦 安装

### 方式一：WorkBuddy 技能目录（推荐）

```bash
# 克隆到用户级技能目录
git clone https://github.com/193600511/zhedongyuan-tuiwen.git ~/.workbuddy/skills/zhedongyuan-tuiwen
```

重新加载技能列表即可看到「浙东院推文skill」（带图标）。

### 方式二：任意 Agent Skills 运行时

本 skill 遵循 [Agent Skills 规范](https://agentskills.io)：一个文件夹 + `SKILL.md`（YAML frontmatter）。把 `zhedongyuan-tuiwen/` 整个目录放进你的运行时技能路径，或直接把 `SKILL.md` 提供给支持技能上传的 Agent 即可。

依赖：Python 3.8+（仅标准库，零第三方依赖）；读稿渲染需要本机装有 Chrome（无头模式）。

## 🚀 快速开始

```bash
# 1) 体检：有没有违规
python scripts/check_article.py 文章.html

# 2) 评分：好不好、差在哪（一行结论）
python scripts/score_article.py 文章.html --brief
# → A  87/100  小修即可发布  [预告/赛事类]

# 3) 读稿点评：渲染逐屏 + 观感点评
python scripts/render_preview.py 文章.html 输出目录 "文章标题"
python scripts/score_article.py 文章.html            # 完整评分卡 + 编辑点评

# 4) 自动优化：修完自动复检
python scripts/auto_fix.py 文章.html                 # → 文章-fixed.html + 前后对比
python scripts/auto_fix.py 文章.html --flatten       # 深度：剥背景图/旋转/flex，防粘贴散架
```

## 💬 在对话里怎么用

装好之后不用记命令，直接说人话，技能会自己选模式：

| 你说 | 走哪条 |
|---|---|
| 「这篇推文符合规范吗」→ 丢 HTML 或文件路径 | ① 体检 |
| 「给这篇打个分」「哪篇写得好」 | ② 评分 |
| 「点评这篇」「读者看着怎么样」 | ③ 读稿点评（渲染逐屏 + 文字点评） |
| 「帮我按规范改一遍」「能自动修的都修了」 | ④ 自动优化（修完自动复检） |
| 「写一篇迎新晚会的推文」+ 文字和图片 | ⑤ 标准出稿 |

**交付约定**：点评一律是**文字**，按屏分段说观感，不给你发截图；只有你明确说"出个点评页/做张评分图"才会产出图片。推文 HTML、手机预览页属于正常交付物。

## 📖 模式教程

### ① 排版体检

对推文 HTML 逐项检查学院硬规范，输出 **致命 / 建议 / 提示** 三级清单，致命项附具体修法：

```bash
python scripts/check_article.py article.html          # 终端报告
python scripts/check_article.py article.html --json   # 机器可读（退出码 0=通过 1=有致命）
```

检查覆盖：主字号 17px、禁 font-family、行距 1.75、字距 0、首行缩进 2em、两端对齐、图片段前后 8px、照片 ≤10 张（模板装饰图/gif 不计入）、落款五件套、纯黑文字色、!important 过多、编辑器残留 class、外链/本地图发布提醒。

### ② 五维评分

体检回答"有没有违规"，评分回答"这篇好不好"：

| 维度 | 权重 | 考察 |
|---|---|---|
| 格式规范 | 30 | 学院硬规范 |
| 结构完整 | 20 | 头图/导语/分节/落款/底图 |
| 内容质量 | 25 | 长段、信息密度、绝对化、占位符 |
| 阅读体验 | 17 | 图文比、句长、首屏 |
| 合规风险 | 8 | 敏感表述、纯黑文字 |

- **等级**：A+ ≥90 直发 · A ≥84 小修 · B ≥76 基本合格 · C ≥68 短板 · D <68 返工
- **A+ 封顶**：有必改项时最高判 A
- **基线**：342 篇已发布稿中位数 80——新稿 ≥85 才算优于历史平均
- 每次评分附带**编辑点评**：扣分项翻译成"现象 → 为什么 → 怎么改"的人话，分 必须改 / 可以更好 / 做得好 三层

```bash
python scripts/score_article.py article.html              # 完整评分卡
python scripts/score_article.py article.html --brief      # 一行结论
python scripts/score_article.py article.html --json       # 机器可读
python scripts/score_article.py article.html --html s.html  # 可视化评分卡
```

### ③ 读稿点评

分数只是尺子，点评必须基于"人眼看到的文章"。流程：**渲染 → 逐屏看 → 观感说话**。

```bash
python scripts/render_preview.py article.html outdir "文章标题" [账号名]
```

产出模拟公众号文章页 + 整页长图 + 每屏 812px 的逐屏截图（自动测算总屏数），然后逐屏阅读、按观感写点评。**点评以文字交付，渲染截图只是看稿依据**——这是本 skill 的交付铁律。

### ④ 自动优化

```bash
python scripts/auto_fix.py article.html                  # 修复 → article-fixed.html + 前后对比
python scripts/auto_fix.py article.html --flatten        # 深度：模板降级
python scripts/auto_fix.py article.html --strip-head     # 删开头超大标题装饰块
python scripts/auto_fix.py article.html --json
```

自动修：字号归一 17px（金句 18 / 标题 / 图注 12 不动）、行距 1.75、字距 0、缩进 2em、**成段文字一律两端对齐**、纯黑→#3e3e3e、删 font-family、图片容器 margin:8px、落款纠错补行、剥 !important、清编辑器残留；`--flatten` 再剥 background-image / rotate / flex（公众号编辑器会过滤这些，信纸底消失、斜相框被掰正就是它们干的）。

刻意**不**自动修：照片超限（删照片是编辑决策）、来源/编辑姓名缺失（不臆造）、病句与题文不符（提示但不代写）。

修完自动复检，输出体检致命数与评分的前后对比。验收纪律：已满分稿过一遍必须零修改零降分。

### ⑤ 标准出稿

给文字和图片 → 判稿型 → 从 403 个历史样式组件库挑结构 → 套学院规范模板 → 体检修到零致命 → 评分 ≥85 才交付。组件库（`assets/components/gallery/`）从 356 篇真实存档做组件级挖掘，每篇都换主题色使用。

## 📐 排版硬规范速查

| 项 | 要求 |
|---|---|
| 正文字号 | 17px（小注 12–15，金句 18，标题 20–32） |
| 字体 | 系统默认，禁写 font-family |
| 行距 / 字距 | 1.75 / 0 |
| 首行缩进 | 2em |
| 对齐 | **成段文字一律两端对齐 justify**（右对齐/居中正文是硬伤） |
| 图片 | 段前后 8px，真实照片 ≤10 张 |
| 落款 | 来 源 → 编 辑 → 责 编（一审）孙舒 → 责 审（二审）吴昕灿 → 终 核（三审）武德力 |
| 开头 | **不放**胶囊标签/大标题/副标题/装饰线，标题入公众号标题栏 |
| 粘贴安全 | 只用 section/p/img + 内联样式，不依赖 background-image / rotate / flex |

## 📁 目录结构

```
zhedongyuan-tuiwen/
├── SKILL.md                      # 技能主文档（四模式 + 交付铁律）
├── _icon.png                     # 技能图标
├── scripts/
│   ├── check_article.py          # 排版体检
│   ├── score_article.py          # 五维评分 v1.4 + 编辑点评
│   ├── render_preview.py         # 读稿渲染（逐屏截图）
│   └── auto_fix.py               # 自动优化
├── references/
│   ├── standards.md              # 规范速查（格式/落款/五类文风/标题）
│   ├── style-library.md          # 342 篇实证样式库（风格画像/色板/字号）
│   └── scoring-rubric.md         # 评分标准（权重/稿型/等级/版本记录）
└── assets/
    ├── template.html             # 标准出稿模板
    └── components/
        ├── *.html                # 基础组件（段落/双图/落款/头尾图）
        └── gallery/              # 403 个历史样式组件 + index.json
```

## 🧭 设计原则

1. **只扣可客观判定的事实**——审美与文风偏好不入分
2. **宁漏不误杀**——位置定位失败不扣分
3. **同一问题只扣一次**——体检与评分口径一致，不重复叠加
4. **阈值有数据支撑**——任何调整后重跑 342 篇标定，中位数偏离 80±3 就是尺子歪了
5. **点评用文字、按屏说话**——渲染是分析手段，不是交付物

## 📜 版本记录

| 版本 | 改动 |
|---|---|
| v1.1 | 稿型自适应评分 |
| v1.2 | 编辑点评（人话三层） |
| v1.3 | 外链移出评分；A+ 封顶；解析盲区修复 |
| v1.4 | 装饰图不计图数；右对齐单列硬伤；缩进精确报值；识别模板封面卡 |
| — | 自动优化模式（auto_fix）；读稿点评流程（渲染逐屏）；对齐铁律收紧 |

## License

MIT

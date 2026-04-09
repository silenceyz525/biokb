# 🧬 BioKB - 生物医药知识库

## 快速开始

### 系统已配置完毕，包括：

✅ **本地知识库网站** — 可搜索、可分类浏览、可 AI 问答  
✅ **144 篇初始论文** — 创新药 70 篇 | 生物制造 43 篇 | 大健康 31 篇  
✅ **每日自动采集** — 早 8 点自动从 PubMed、Nature、bioRxiv、STAT News 等源采集  
✅ **每周自动简报** — 周一 9 点生成周报，总结本周高价值内容  
✅ **AI 问答** — 基于你的知识库内容进行专业问答  

---

## 访问方式

### 方式 1：打开前端网站
```
http://127.0.0.1:8765/index.html
```
在浏览器中打开此链接，即可进入知识库页面。

**功能：**
- 📚 浏览分类文章（创新药 / 生物制造 / 大健康）
- 🔍 按标签、来源、日期范围筛选
- 💬 右侧 AI 问答面板提问
- 📄 查看完整文章详情和原文链接

### 方式 2：API 接口
```
GET http://127.0.0.1:8765/api/articles     # 获取所有文章
GET http://127.0.0.1:8765/api/stats        # 获取统计数据
GET http://127.0.0.1:8765/api/reports      # 获取历史报告
POST http://127.0.0.1:8765/api/chat        # AI 问答
```

### 方式 3：命令行管理
```bash
cd C:\Users\silen\biopharma-kb

# 查看帮助
python server.py

# 执行采集
python server.py collect-fast  # 快速采集（不AI评分）
python server.py collect       # 完整采集（包含AI评分+中文摘要）

# 生成报告
python server.py report        # 周报
python server.py report-m      # 月报

# 启动服务
python server.py serve         # 启动 Web + API

# 导出数据
python server.py export        # 导出 JSON 格式
```

---

## 项目结构

```
C:\Users\silen\biopharma-kb\
├── index.html              # 前端网站（可直接打开或通过服务器访问）
├── server.py               # 后端服务 + 采集脚本 + API
├── data/
│   ├── biokb.db           # SQLite 数据库（所有文章数据）
│   └── articles.json      # JSON 导出（供前端使用）
├── scripts/
│   └── enhanced_collect.py # 增强采集模块（PubMed + 行业新闻）
└── reports/
    └── *.md               # 自动生成的周报/月报
```

---

## 数据源覆盖

### 国际学术
- **PubMed** — 全球最大生物医学数据库（每次采集 75 篇）
- **Nature** — 顶级期刊头条 + 生物技术专栏
- **bioRxiv** — 预印本库（发表前 3-6 个月）

### 行业新闻
- **Genetic Engineering & Biotechnology News (GEN)** — 生物制造专业媒体
- **STAT News** — 生物医药深度报道
- **Fierce Biotech** — 融资、并购、管线跟踪

### 国内资讯
- **生物探索** / **医麦客** — 国内生物医药动态

---

## 自动化配置

已配置 **2 个定时任务**，自动运行：

### 1️⃣ 每日采集 (8:00 AM)
```
python server.py collect-fast
↓
自动采集最新论文和新闻 → 去重 → 导出 JSON
```

### 2️⃣ 每周简报 (周一 9:00 AM)
```
python server.py report
↓
生成本周高价值文章汇总（Markdown 格式）
存放于 C:\Users\silen\biopharma-kb\reports\
```

---

## 知识库功能详解

### 搜索与浏览
- **全文搜索** — 支持标题、摘要、作者、标签、来源关键词
- **分类筛选** — 创新药 / 生物制造 / 大健康三大领域
- **标签体系** — 按技术类型（CAR-T、ADC、基因编辑等）快速定位
- **日期范围** — 支持按发表时间筛选
- **来源过滤** — 只看某个特定期刊/新闻源

### AI 问答（💬 右侧面板）

你可以直接问：
- *"CAR-T 细胞疗法的最新进展是什么？"*
- *"生物制造领域有哪些突破性技术？"*
- *"最近有哪些创新药获批上市？"*
- *"CRISPR 基因编辑的应用现状如何？"*

AI 会基于知识库内容回答，并显示参考来源数量。

### 详情页
点击任意文章卡片，查看：
- 完整标题与分类标签
- 文章摘要
- 作者信息
- 发表日期和期刊
- 相关性评分（如有 AI 评分）
- 原文链接（可直接访问 PubMed、Nature 等）

---

## 下一步扩展建议

### 短期（1-2 周）
1. **学者追踪** — 添加你关注的学者，自动监控其新论文发布
2. **关键词告警** — 设置自定义关键词，有新动态时通知
3. **主题收集** — 按"CAR-T 临床进展"、"ADC 药物设计"等专题组织文章

### 中期（1 个月）
4. **云端同步** — 支持接入云存储（OneDrive / Google Drive）
5. **多渠道推送** — 定期推送到微信、邮件、Telegram
6. **数据分析** — 统计论文发表趋势、学者活跃度等

### 长期
7. **知识图谱** — 构建学者-机构-技术的关系网络
8. **预测引擎** — AI 预测某技术未来发展方向
9. **对标分析** — 跟踪竞争对手和合作伙伴的研发进展

---

## 常见问题

### Q: 如何添加新的 RSS 数据源？
编辑 `server.py` 中的 `RSS_SOURCES` 配置，或在 `scripts/enhanced_collect.py` 中添加爬虫函数。

### Q: 如何自定义 AI 评分标准？
修改 `server.py` 中的 `RELEVANCE_PROMPT`，改变 AI 的评分逻辑。

### Q: 数据会不会丢失？
所有数据存储在本地 SQLite 数据库 (`data/biokb.db`)，完全由你控制，不经过任何云端。

### Q: 能否离线使用？
前端网站可完全离线使用，但采集功能需要网络连接。

### Q: 如何导出为其他格式？
- **JSON** — 已支持（`python server.py export`）
- **CSV** — 可改进后端脚本
- **PDF** — 周报已是 Markdown，可通过 Pandoc 转换为 PDF

---

## 技术栈

- **前端** — 纯 HTML5 + CSS3 + Vanilla JavaScript（无依赖，轻量级）
- **后端** — Python 3.14 + SQLite3
- **API** — 轻量 HTTP 服务器（内置，无需 Flask/Django）
- **采集** — feedparser + requests（RSS 和 Web 爬虫）
- **AI** — 对接 academicapi.com（DeepSeek v3.2）

---

## 许可与免责

这个知识库纯个人使用，数据来自公开学术库和新闻源。所有内容仅供学习参考，不承担任何法律责任。

---

**祝你探索顺利！🚀**

有任何问题或建议，随时告诉我。

# RankingSelect · 产品需求文档 PRD v1

> 产品名称:RankingSelect
> 文档版本:v1.0
> 更新日期:2026-08-09
> 阶段:需求讨论定稿 → 进入设计/开发

---

## 1. 产品定位

面向**硕士申请者**,聚焦**欧陆及其他非中美英澳地区**信息不透明痛点,以**五大权威榜单(QS / THE / ARWU / USNews / CS Rankings)为发现入口**,聚合院校排名与项目级申请情报(投递时间、所需材料、硬性要求 + 官方源链接),并提供轻量的**Like 收藏 + Me 看板**管理机制。

一句话:**用榜单发现院校,一键 Like 收藏,在 Me 看板集中查看目标院校的申请要求与截止倒计时。**

---

## 2. 目标用户与核心场景

| 用户 | 核心场景 |
|------|---------|
| 主:硕士申请者 | 跨榜比对排名定位目标院校 → Like 收藏 → 在 Me 看板集中查看各院校项目的投递时间、所需材料、硬性要求与倒计时,推进申请 |
| 次:规划期学生/家长 | 浏览榜单了解院校层次,Like 感兴趣院校备查 |

### 典型路径(优化后)

**首页搜索/筛选 → 榜单页定位院校 → 院校详情看五榜排名汇总与项目列表 → 点击院校爱心(Like) → 点击 Me → 看到已 Like 院校的 require(材料/硬指标)与 deadline(投递时间/倒计时)**

- 申请管理从"重 Option 流程"简化为"Like + Me 看板":Like 的对象是**院校**,Me 看板聚合展示已 Like 院校下各项目的 require + deadline + 倒计时。
- 用户无需进入项目详情即可在 Me 看板一站式查看关键申请信息,但项目详情页仍提供官方源链接供核对。

---

## 3. 数据源与获取方式

| 数据 | 来源 | 获取方式 | 结构化程度 |
|------|------|---------|-----------|
| 五大榜单排名 | QS / THE / ARWU / USNews / CS Rankings | Python 爬虫脚本(无公开 API;CS Rankings 用 GitHub 开源数据) | 全结构化 |
| 院校基础信息(名称/国家/地区/官网/学科) | 榜单 + 官网 | 爬虫 | 结构化 |
| 学院/项目列表 | 各校官网 | 爬虫 + 人工校对 | 半结构化 |
| 投递时间/所需材料/硬性要求 | 各项目官方页 | **抓取 + 部分结构化解析 + 后续人工校对纠正**,并保留官方源 URL | 部分结构化 + 源链接 |

**关键说明**:
- QS/THE/ARWU/USNews **均无开放排名 API**,只能爬取;仅 CS Rankings 数据开源可程序化获取。
- 申请类信息采用"抓取数据 + 部分结构化 + 后续人工校对纠正"策略:能稳定解析的字段(deadline 日期、语言成绩、材料清单)解析入库,解析困难的仅保留官方源 URL,后续人工校对补全与纠正。
- 抓取脚本为**离线维护工具**,输出静态 JSON,前端运行时加载,无后端。

---

## 4. 学科维度

- **进入 MVP**:榜单支持按学科筛选;院校详情按学科组织项目;项目详情标注所属学科。
- 学科分类参考 QS 学科大类(如 Engineering、Computer Science、Business、Natural Sciences 等),并保留与 CS Rankings 的学科映射。
- 学科筛选为榜单页与院校详情页的一级筛选条件。

---

## 5. 信息架构(页面)

```
首页 Home
├─ 五榜概览 + 热门地区入口 + 学科入口 + 搜索
榜单页 Ranking
├─ 选榜(QS/THE/ARWU/USNews/CS Rankings)
├─ 筛选:地区 / 学科 / 年份 + 搜索
├─ 院校列表(排名 + 国家 + 学科标签 + Like 爱心)
院校详情页 University
├─ 五榜排名汇总(同一院校跨榜对比)
├─ 基础信息(国家/地区/官网/学科)
├─ 项目列表(按学院/学科组织,每个项目含投递时间/材料/硬要求 + 官方源链接)
└─ Like 爱心(顶部固定)
Me 看板
├─ 已 Like 院校列表
├─ 每个院校展开:各项目的 require(材料/硬指标)+ deadline(投递时间/倒计时)
├─ 官方源链接(点开核对)
└─ 取消 Like / 导出
对比页 Compare(P1)
└─ 多院校跨榜对比
关于/数据说明
└─ 数据源、抓取时间、校对说明、版本
```

---

## 6. 功能清单(P0/P1/P2)

| 级别 | 功能 |
|------|------|
| **P0**(MVP) | 五榜排名浏览;地区/学科/年份筛选 + 搜索;院校详情(五榜汇总 + 项目列表);项目详情(投递时间/材料/硬要求 + 官方源链接);Like 收藏;Me 看板(已 Like 院校的 require + deadline + 倒计时);localStorage 持久化;数据更新时间展示 |
| **P1** | 多院校跨榜对比;导出/导入 Like 列表;学科排名子榜;项目级材料勾选进度 |
| **P2** | 浏览器通知(截止日提醒);多语言界面;数据更新提醒;Me 看板分组/排序 |

---

## 7. 交互要点:Like + Me 看板

- **Like 触发点**:院校列表卡片的爱心 + 院校详情页顶部爱心。
- **Like 对象**:院校(院校级收藏)。Me 看板展开后呈现该院校下的项目申请信息。
- **Me 看板**:
  - 顶部:已 Like 院校数 + 总览统计。
  - 列表:按截止日临近程度排序,临近的高亮/置顶。
  - 每个院校可展开查看其项目:投递时间、倒计时天数、所需材料清单、硬性要求、官方源链接。
  - 倒计时基于项目 deadline 实时计算;已过期项目灰显并标记。
- **持久化**:全部存 localStorage,无账号无同步(后续版本再考虑多端同步)。

---

## 8. 数据模型

```jsonc
// frontend/public/data/rankings/qs.json
[{ "rank": 1, "universityId": "u_eth", "score": 100.0, "year": 2025 }]

// frontend/public/data/universities.json
{
  "u_eth": {
    "name": { "en": "ETH Zurich", "zh": "苏黎世联邦理工" },
    "country": "Switzerland",
    "region": "Western Europe",
    "website": "https://ethz.ch",
    "subjects": ["Engineering", "Computer Science", "Natural Sciences"]
  }
}

// frontend/public/data/programs.json
{
  "p_eth_cs_ms": {
    "universityId": "u_eth",
    "subject": "Computer Science",
    "dept": "Computer Science",
    "program": "MSc Computer Science",
    "deadlines": [{ "round": "main", "date": "2025-12-15" }],
    "materials": ["CV", "Transcript", "Motivation Letter", "Language Proof"],
    "requirements": { "gpa": null, "ielts": "7", "toefl": "100" },
    "sourceUrl": "https://inf.ethz.ch/.../master",
    "verified": false,
    "updatedAt": "2026-08-01"
  }
}

// localStorage(用户数据)
{
  "likes": ["u_eth", "u_tum"],
  "checklist": { "p_eth_cs_ms": ["CV"] },
  "settings": { "language": "zh", "sortBy": "deadline" }
}
```

---

## 9. 技术栈

| 层 | 选型 |
|----|------|
| 前端框架 | React + Vite + TypeScript |
| 路由 | React Router |
| 状态 | React Context + localStorage(轻量,无后端) |
| 数据加载 | 静态 JSON(fetch /data/...) |
| 用户数据存储 | localStorage |
| 抓取脚本 | Python(requests / BeautifulSoup / 适当用 Selenium) |
| 部署 | 静态托管(GitHub Pages / Vercel / Netlify) |
| 后端 | 无 |

---

## 10. 仓库结构

```
RankingSelect/
├── docs/PRD-v1.md
├── frontend/                    # React + Vite 应用
│   ├── public/data/             # 爬虫输出的静态 JSON(前端直接加载)
│   │   ├── rankings/{qs,the,arwu,usnews,csrankings}.json
│   │   ├── universities.json
│   │   └── programs.json
│   └── src/{pages,components,store,hooks,types,utils}
├── scraper/                     # Python 爬虫
│   ├── rankings/{qs,the,arwu,usnews,csrankings}.py
│   └── programs/
└── README.md
```

---

## 11. 后续步骤

1. 确认本 PRD → 进入信息架构详细设计与页面原型描述。
2. 搭建前端骨架(RankingSelect 已建目录)。
3. 设计 Python 爬虫脚本结构与数据 schema。
4. 优先实现 CS Rankings 抓取(最易,开源数据)验证流水线。
5. 逐步接入 QS/THE/ARWU/USNews 抓取与人工校对流程。

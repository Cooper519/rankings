# RankingSelect 项目架构与数据约定

版本：1
当前公开申请周期：27fall

## 1. 目标与边界

RankingSelect 是静态优先的个人申请信息站。仓库是数据和版本的唯一来源：

- GitHub Pages 或任意静态 Server 只负责展示生成后的 JSON。
- 本地维护工具负责读取原始包、校验、构建 SQLite 和导出静态 JSON。
- 贡献通过 GitHub Pull Request 完成，不提供在线编辑。
- 原始数据和来源证据必须长期可追溯。
- 前端只显示 current admission cycle；历史周期继续保留。

## 2. 数据流

    院校 TXT / 手工 JSON / 抓取输出       榜单 adapter
                    │                         │
                    └──────── raw/ ───────────┘
                              │
                        Schema 与语义校验
                              │
                   normalized/rankingselect.sqlite
                              │
                         generated/*.json
                              │
                       React 静态前端构建
                              │
                    GitHub Pages / 静态 Server

原始包和转换脚本是主要维护对象。SQLite 与 generated JSON 是可重建、可提交的构建产物，不能作为唯一数据源。

## 3. 目录约定

    raw/
    ├── universities/<university_id>/
    │   ├── manifest.json
    │   ├── projects.json
    │   ├── sources.json
    │   ├── reviews.json
    │   ├── raw/
    │   └── notes.md
    └── rankings/<source>/
        ├── manifest.json
        ├── response-<timestamp>.json
        └── normalized.json

    normalized/
    └── rankingselect.sqlite

    generated/
    ├── universities.json
    ├── projects.json
    ├── admission_cycles.json
    ├── timelines.json
    ├── requirements.json
    ├── fees.json
    ├── sources.json
    ├── data-manifest.json
    └── rankings/<source>.json

    schemas/
    ├── manifest.schema.json
    ├── projects.schema.json
    ├── reviews.schema.json
    └── sources.schema.json

旧版抓取证据位于 scraper/raw，不等同于新的 raw/universities 契约。

## 4. 标识符

所有 ID 都是稳定标识符：

- 只使用小写 ASCII 字母、数字、下划线和短横线。
- ID 发布后不能回收或复用。
- 名称变化不自动改变 ID。
- 实体废弃时使用 inactive 或 archived，不物理删除。

项目 ID：

    project_id = university_id + campus_id + normalized_program_code

例如：

    u_tu_delft_main_cs_msc

同名项目只有在校区、实际学位项目或申请身份发生变化时才拆成不同 project。学年差异通过 admission cycle 表达。

## 5. 原始包文件

manifest.json 描述学校和包版本。projects.json 保存一个数组，每个 project 嵌套多个 admission cycle。sources.json 保存项目包引用的全部来源。reviews.json 保存冲突来源的人工选择。

JSON Schema 是结构级契约：

- schemas/manifest.schema.json
- schemas/projects.schema.json
- schemas/reviews.schema.json
- schemas/sources.schema.json

跨文件引用仍需语义校验，例如 project.university_id 必须等于 manifest.university_id，所有 source_id 必须存在于 sources.json。

## 6. Admission cycle

周期以入学学年为主：

    {
      "cycle_id": "27fall",
      "academic_year": 2027,
      "entry_term": "fall",
      "status": "current"
    }

规则：

- 同一项目可以保留多个周期。
- 网站只展示 current 周期。
- 旧周期改为 historical，不删除。
- timeline、requirements 和 fees 都属于周期。
- 一个项目的不同周期可以有不同学费和要求。

## 7. Timeline

每条 timeline 包含：

- timeline_id
- event
- date_type
- date / date_end
- applicant_group
- round
- source_id
- verification_status

日期类型：

- exact：精确日期 YYYY-MM-DD。
- month：精确到月份 YYYY-MM。
- range：date 与 date_end 都是 YYYY-MM-DD。
- rolling：学校明确表示滚动申请。
- tba：学校明确表示待公布。
- unknown：已检查但无法确认。

rolling、tba 和 unknown 不能附带虚构日期。

## 8. Requirements

第一版只结构化：

- language：考试名称与最低分。
- gre：required、optional、not_required 或 unknown，以及可选最低分。
- gmat：同 GRE。
- academic：状态和成绩/背景文字说明。
- notes：无法可靠归类的补充内容。

考试分数用字符串保存。字段缺失不能解释为“无要求”。

## 9. Fees

第一版只允许：

- tuition
- registration

amount 只能是 unknown 或非负数字字符串。其他信息通过 currency、period、applicant_group 和 condition 表达。费用属于 admission cycle。

## 10. 来源、证据与人工选择

来源类型：

- official_web
- official_api
- official_pdf
- manual_entry
- archive

数据校验状态：

- discovered
- extracted
- needs_review
- verified
- stale
- rejected

verified 只能由人工审核产生。多个来源冲突时保留全部证据，记录人工选择、舍弃来源、决策理由、审核人和时间；不能静默覆盖。

## 11. SQLite 规范化模型

主数据库计划使用以下表：

    universities
    campuses
    projects
    admission_cycles
    timelines
    requirements
    fees
    sources
    source_evidence
    field_source_links
    ranking_editions
    ranking_entries
    data_packages
    schema_metadata

约束：

- 开启 SQLite 外键。
- 不使用级联物理删除。
- 所有表和 JSON 字段统一使用 snake_case。
- 原始包、数据库和生成文件都携带 schema_version。
- Schema 变化必须提供 migration。
- 同一份输入重复构建必须得到相同输出。

## 12. 榜单 Adapter

QS、THE、ARWU、U.S. News 和 CS Rankings 各自实现 adapter，统一提供：

    fetch()
    parse()
    normalize()
    validate()

每个 adapter 声明 source、endpoint、authentication_mode、adapter_version 和 pagination_strategy。

运行规则：

- adapter 只在本地或 GitHub Actions 中运行。
- 每次请求接口当前最新 edition。
- 原始响应快照不能被覆盖。
- 当前 SQLite 和前端只展示每个榜单的最新有效 edition。
- 请求或校验失败时保留上一份有效快照，并标记 fallback。
- 凭证只存放在环境变量或 GitHub Actions Secrets。

## 13. 发布规则

Pull Request 必须检查：

- JSON Schema。
- ID 格式、唯一性和跨文件引用。
- admission cycle 和日期类型。
- fee 类型与金额。
- 官方来源 URL。
- 可重复构建。
- Python 测试。
- TypeScript 和 Vite 构建。

结构、ID、外键或来源引用错误必须阻止合并。timeline、requirements 或 fee 没有证据时可以构建，但前端必须显示 unknown、tba、needs_review 或 stale，不能显示为“无要求”。

GitHub Pages、根域静态 Server 和本地开发共用相同生成数据契约。部署路径差异只由前端 base/basename 配置处理。

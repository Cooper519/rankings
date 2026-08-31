# RankingSelect

面向硕士申请者的全球大学排名与申请情报工具。项目以 QS、THE、ARWU（软科）、U.S. News 和 CS Rankings 为院校发现入口，聚合院校排名、官方硕士项目、申请时间线、语言/GRE/GMAT/学术要求和学费/注册费，并通过 Like 与 Me 看板管理个人申请进度。

项目采用静态优先架构：

- GitHub Pages：公开展示网站。
- 本地：维护原始数据包、运行转换和构建。
- Server：部署构建后的静态文件。
- 第一阶段没有在线编辑、账号、多用户协作或实时后端 API。
- 数据变更通过 GitHub Pull Request 管理。

## 快速开始

启动当前前端：

    cd frontend
    npm install
    npm run dev

浏览器打开 Vite 输出的本地地址，通常是 http://localhost:5173。

构建静态文件：

    cd frontend
    npm run build
    npm run preview

当前前端读取 frontend/public/data/ 下的静态 JSON。新增原始包后，需要使用项目的数据构建流水线将数据导入主库并导出前端 JSON；TXT 转换器本身只负责生成院校原始包。

完整架构和数据库约定见 [docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md)。机器可读的数据结构位于 [schemas/](schemas/)。

## 仓库结构

    RankingSelect/
    ├── raw/                         # 新规范：院校和榜单原始包
    │   └── universities/<id>/
    ├── normalized/                  # 规范化主数据库（SQLite）
    ├── generated/                   # 由主库导出的静态 JSON
    ├── schemas/                    # 原始包 JSON Schema
    ├── tools/
    │   ├── txt_to_package.py       # TXT -> 院校原始包
    │   ├── data_pipeline.py        # raw -> SQLite -> generated/frontend JSON
    │   ├── repair_duplicate_ids.py # 重复 ID 保守治理工具
    │   ├── build_frontend_data.py  # 兼容旧命令的薄包装
    │   └── test_txt_to_package.py  # 转换器测试
    ├── frontend/                   # React + Vite + TypeScript 前端
    │   └── public/data/             # 当前前端使用的静态数据
    ├── scraper/                    # 可重复执行的爬虫和离线维护脚本
    ├── docs/
    └── README.md

新的规范院校包放在根目录 `raw/universities/`。需要长期保留的原始证据放在对应包的 `raw/` 子目录。`scraper/raw/`、浏览器日志、抓取队列、进度文件和一次性修复脚本都是本地运行产物，不应提交。

## TXT 转换为原始包

### 1. 生成模板

在项目根目录执行：

    python -m tools.txt_to_package --template ./u_example_university.txt

这会生成 UTF-8 模板。模板可以复制为新的学校文件，例如：

    Copy-Item ./u_example_university.txt ./u_tu_delft.txt

### 2. 编辑 TXT

TXT 使用简单的 INI 风格：

- 文件编码必须是 UTF-8。
- 空行会被忽略。
- 以 # 或 ; 开头的行是注释。
- 字段格式是 key = value。
- 同一个 section 中不能重复字段。
- 列表使用分号分隔，例如 English; Dutch。
- ID 使用小写字母、数字、下划线或短横线，不能包含空格。
- 所有 URL 必须是 http:// 或 https://。
- language_tests 使用 考试名:最低分数，例如 IELTS:7.0; TOEFL iBT:100。

完整示例：

    [manifest]
    schema_version = 1
    package_version = 2026.08.19.1
    university_id = u_tu_delft
    name = Delft University of Technology
    country = Netherlands
    website = https://www.tudelft.nl
    region = Western Europe
    updated_at = 2026-08-19
    notes = 仅填写学校官方页面能确认的信息。

    [source src_admissions]
    url = https://www.tudelft.nl/en/education/admission-and-application
    source_type = official_web
    title = Admission and application
    retrieved_at = 2026-08-19T00:00:00Z
    verification_status = needs_review
    evidence_text = Official admissions source.

    [project u_tu_delft_main_cs_msc]
    campus_id = main
    normalized_program_code = cs_msc
    name = MSc Computer Science
    degree = MSc
    subject = Computer Science
    study_mode = full_time
    teaching_language = English
    official_url = https://www.tudelft.nl/en/education/programmes/masters/computer-science
    status = active
    notes =

    [cycle u_tu_delft_main_cs_msc 27fall]
    academic_year = 2027
    entry_term = fall
    status = current

    [timeline u_tu_delft_main_cs_msc 27fall deadline_1]
    event = deadline
    date_type = exact
    date = 2026-12-01
    applicant_group = non_eu
    round = round_1
    source_id = src_admissions
    verification_status = needs_review

    [requirements u_tu_delft_main_cs_msc 27fall]
    language_status = required
    language_tests = IELTS:7.0; TOEFL iBT:100
    gre_status = unknown
    gmat_status = not_required
    academic_status = required
    academic_description = Relevant bachelor's degree.
    source_id = src_admissions
    verification_status = needs_review
    notes =

    [fee u_tu_delft_main_cs_msc 27fall tuition_1]
    type = tuition
    amount = unknown
    currency = EUR
    period = per_year
    applicant_group = non_eu
    condition =
    source_id = src_admissions
    verification_status = needs_review

### 3. 转换

输出到规范院校包目录：

    python -m tools.txt_to_package ./u_tu_delft.txt --output ./raw/universities/u_tu_delft

macOS/Linux 使用反斜杠续行，或将命令写成一行：

    python -m tools.txt_to_package u_tu_delft.txt \
      --output raw/universities/u_tu_delft

转换器会：

- 检查 manifest、项目、周期、来源和字段是否完整。
- 检查 ID 是否合法且唯一。
- 检查 timeline 的日期类型和格式。
- 检查 requirements 状态和语言成绩格式。
- 检查 fee 只能是 unknown 或数字字符串。
- 检查 timeline、requirements 和 fee 引用的 source_id 是否存在。
- 检查所有 URL 是否为 HTTP(S)。
- 将原始 TXT 复制到输出目录的 raw/，保留可追溯输入。

输出目录：

    raw/universities/u_tu_delft/
    ├── manifest.json
    ├── projects.json
    ├── sources.json
    ├── reviews.json
    ├── raw/
    │   └── u_tu_delft.txt
    └── notes.md

manifest.json、projects.json、sources.json 和 reviews.json 是机器读取文件。notes.md 由转换器生成；长期有效的判断和说明应写入 TXT 的 notes 或来源的 evidence_text，不要只手改生成的 notes.md。

对应的 JSON Schema：

- schemas/manifest.schema.json
- schemas/projects.schema.json
- schemas/sources.schema.json
- schemas/reviews.schema.json

输出目录非空时，转换器默认拒绝覆盖：

    python -m tools.txt_to_package ./u_tu_delft.txt --output ./raw/universities/u_tu_delft --force

使用 --force 前先检查目录，避免覆盖尚未提交的手工修改。

## 原始包数据约定

### manifest

必填字段：

    {
      "schema_version": 1,
      "package_version": "2026.08.19.1",
      "university_id": "u_tu_delft",
      "name": "Delft University of Technology",
      "country": "Netherlands",
      "updated_at": "2026-08-19"
    }

可选字段包括 website、region 和 notes。

### project

project 表示一个可申请的具体学位项目，不是宽泛的专业分类。稳定身份由以下内容决定：

    project_id = university_id + campus_id + normalized_program_code

项目可以包含多个 admission cycle。项目名称、学位、校区、授课语言、学习方式和官方项目 URL 都保存在 project 层；学年变化的信息不能放在这里。

项目至少需要：

- project_id
- university_id
- campus_id
- normalized_program_code
- name
- official_url
- admission_cycles

### admission cycle

周期以学年为主，例如当前网站展示 27fall：

    {
      "cycle_id": "27fall",
      "academic_year": 2027,
      "entry_term": "fall",
      "status": "current"
    }

前端默认只展示 current 周期；历史周期可以长期保留在原始包和数据库中，并标记为 historical。

### timeline

每个时间事件必须关联申请周期、申请人群组和官方来源：

- event
- date_type
- date / date_end
- applicant_group
- round
- source_id
- verification_status

date_type 可以是：

    exact       date = 2026-12-01
    month       date = 2026-12
    range       date = 2026-12-01, date_end = 2027-01-15
    rolling     不填写 date
    tba         不填写 date
    unknown     不填写 date

未知日期不能写成 0 或随意默认日期。

### requirements

requirements 属于 admission cycle，第一版只结构化四组信息：

- language：required、optional、not_required、unknown，以及考试最低分。
- gre：状态和最低分。
- gmat：状态和最低分。
- academic：状态和文字说明。

分数始终保存为字符串。无法归类的内容写入 notes，不要猜测或伪造结构化值。

### fee

第一版只支持两类：

    tuition
    registration

amount 只能是：

- unknown
- 具体数字字符串，例如 25300 或 1200.50

同时填写 currency、period、applicant_group、condition、source_id 和 verification_status。不能用 0 表示未知，也不能把 varies、区间或自由文本放进 amount。

### sources

每个来源至少包含：

    {
      "source_id": "src_admissions",
      "url": "https://www.tudelft.nl/en/education/admission-and-application",
      "source_type": "official_web",
      "retrieved_at": "2026-08-19T00:00:00Z",
      "verification_status": "needs_review"
    }

source_type 使用以下值之一：

    official_web
    official_api
    official_pdf
    manual_entry
    archive

数据状态：

    discovered
    extracted
    needs_review
    verified
    stale
    rejected

抓取或手工录入的数据默认是 needs_review。只有人工核验后才能设置为 verified。当两个来源冲突时，保留所有来源，并由人工记录最终选择和理由。

### 重复 ID 治理

重复治理工具默认只输出预览，不修改文件：

    python -m tools.repair_duplicate_ids

确认报告后再应用：

    python -m tools.repair_duplicate_ids --apply

工具只自动处理可证明安全的情况：同一 URL/内容的重复来源保留最早记录；完全相同的重复项目合并；同 ID 但名称不同的项目按稳定名称重建 ID；仅院系字段冲突时置为待审核并保留说明。其他冲突会留在 `unresolved` 中，不会猜测修复。治理后必须运行：

    python -m tools.data_pipeline validate --strict

冲突选择使用可选的 review section。例如两个官方页面给出的学费不同：

    [review review_tuition]
    entity_type = fee
    entity_id = u_tu_delft_main_cs_msc/27fall/tuition_1
    field_name = amount
    selected_source_id = src_fees_2027
    rejected_source_ids = src_old_catalog
    decision = 采用明确标注 2027 学年的官方费用页面。
    reviewed_by = maintainer
    reviewed_at = 2026-08-19T12:00:00Z

转换后该记录进入 reviews.json。selected_source_id 和 rejected_source_ids 都必须存在于 sources.json；被舍弃的来源仍然保留。

review 的 entity_id 使用稳定路径：project 使用 project_id；cycle 和 requirements 使用 project_id/cycle_id；timeline 与 fee 使用 project_id/cycle_id/记录 ID。

## 榜单数据

QS、THE、ARWU（软科）、U.S. News 和 CS Rankings 均使用独立 adapter。adapter 在本地维护流程或 GitHub Actions 中调用接口，不在 GitHub Pages 浏览器运行。

榜单更新规则：

- 接口请求当前最新 edition。
- 当前 SQLite 和前端 JSON 只展示最新榜单。
- 原始接口响应按时间保存，便于审计和回滚。
- 接口失败时回退到最近一次有效快照，并显示 fallback 状态。
- API Key、Cookie 或其他凭证只能放在本地环境变量或 GitHub Actions Secrets，不能提交到仓库。

### 学校 URL 清单

榜单页的“待补或范围外”列表读取 `frontend/public/data/school_urls.json`。该文件由现有本地证据离线生成：

    python scraper/build_school_urls.py

输入按可信度合并已核验官网、官方项目目录、已记录项目入口和 CS Rankings 官方 `institutions.csv` 元数据。输出记录以下语义：

- `school-homepage`：学校主页；`verified` 表示已核验，`blocked` 或 `review` 表示域名有注册信息支持但页面访问或身份仍待核验。
- `official-programme-directory`：已核验的官方项目目录。
- `official-programme-index`：已有项目数据记录的官方入口。
- `official-department`：CS Rankings 官方元数据中的院系主页，不能改写成学校主页。

被身份核验流程标记为 `rejected` 的候选不会进入清单。没有可靠 URL 的学校仍保留在列表中并显示“URL 待补”，不能通过猜测域名补值。更新 CS Rankings URL 元数据时，先替换 `raw/rankings/csrankings/institutions.csv` 的官方快照，再重新运行生成器。

CS Rankings 提供的官方院系 URL 优先于未核验的项目入口。若某条项目入口的域名已被更可靠的证据归属于另一所学校，生成器会丢弃该条关联，避免把同城、合作或名称相近的院校错误合并。

## Fork、更新和提交院校包

### Fork 和本地安装

1. 在 GitHub 打开本项目，点击 Fork。
2. Clone 你自己的 fork：

    git clone https://github.com/<your-name>/Rankings.git
    cd Rankings

3. 安装前端依赖：

    cd frontend
    npm install
    cd ..

4. 检查转换器：

    python -m unittest tools.test_txt_to_package -v

### 新增或修改院校数据

1. 建立分支：

    git checkout -b data/u_tu_delft

2. 用模板生成 TXT，填写学校官方来源：

    python -m tools.txt_to_package --template u_tu_delft.txt

3. 转换到 raw/universities/u_tu_delft/。
4. 检查生成的 manifest.json、projects.json、sources.json、reviews.json 和 raw/ 中的输入副本。
5. 运行转换器测试和前端构建：

    python -m unittest tools.test_txt_to_package -v
    cd frontend
    npm run build
    cd ..

6. 查看变更：

    git diff --check
    git status

7. 提交并推送：

    git add raw/universities/u_tu_delft
    git commit -m "data: add TU Delft master programme package"
    git push origin data/u_tu_delft

8. 在 GitHub 上从你的分支创建 Pull Request，目标仓库为上游项目的 main 分支。PR 描述中写明：

- 学校和项目名称。
- 数据对应的 admission cycle，例如 27fall。
- 使用的官方 URL。
- 哪些字段已人工核验。
- 哪些字段仍为 unknown 或 needs_review。
- 本地执行过的测试命令。

不要直接提交 API 凭证，不要手改 frontend/public/data 中由流水线生成的文件，不要把第三方聚合网站作为官方来源。

### 同步上游更新

配置上游仓库后，可以这样拉取最新代码：

    git remote add upstream https://github.com/<owner>/Rankings.git
    git fetch upstream
    git checkout main
    git merge upstream/main
    git push origin main

之后从最新的 main 创建新分支，再提交院校数据。若本地有未提交修改，先提交、暂存或放弃这些修改，再执行 merge。

## 本地使用和静态 Server 部署

只查看现有数据：

    cd frontend
    npm run dev

生成生产构建：

    cd frontend
    npm run build

frontend/dist/ 可以部署到静态 Server。临时用 Python 查看构建结果：

    python -m http.server 4173 -d frontend/dist

当前 GitHub Pages 部署使用 `/rankings/` Vite base、HashRouter 和 `.github/workflows/pages.yml`。推送到 main 后会自动构建并发布 `frontend/dist/`。部署到其他仓库名或根域 Server 时，需要同步修改 Vite base。

## 当前实现边界

已实现：

- TXT 到院校原始包的转换。
- 单向数据主流水线：`raw/` → `normalized/rankingselect.sqlite` → `generated/` → 前端 JSON。
- 五榜标准化快照与院校别名表均从 `raw/` 导入 SQLite，不再把前端输出作为输入。
- 对缺文件、重复 ID、来源冲突等问题进行隔离并输出 `validation_issues.json`。
- manifest、project、cycle、timeline、requirements、fee、source 的结构化校验。
- 原始包 JSON Schema、数据契约文档和目录骨架。
- 原始 TXT 副本和生成 notes 的保存。
- 转换器与数据流水线的可重复构建测试。
- React + Vite 静态前端和现有排名/项目快照。
- GitHub Pages 构建前自动重建数据并运行 Python 回归测试。

当前数据快照（2026-08-31）：

- 704 个规范院校包，8,738 个项目。
- 5 个榜单各 500 条，共 2,500 条榜单记录。
- 24 个重复 ID/来源错误已治理，严格校验为 0 error。
- 剩余 346 条均为数据完整性 warning，不阻断构建。

后续治理：

- 五个榜单 adapter 的统一接口实现。
- 按 `generated/validation_issues.json` 继续消化缺失项目文件、空项目包和非规范院校 ID warning。
- 优先补齐高价值项目的 deadline、requirements 与人工 verified 状态。

## 导出前端数据

抓取或新增院校包后，重新生成前端 JSON：

    python -m tools.data_pipeline all

分步排查时可以执行：

    python -m tools.data_pipeline validate
    python -m tools.data_pipeline validate --strict
    python -m tools.data_pipeline build
    python -m tools.data_pipeline export

输入只来自 `raw/universities/`、`raw/rankings/*/normalized.json` 和
`raw/university_aliases.json`。主库写入 `normalized/rankingselect.sqlite`；完整关系导出、
质量报告和构建身份写入 `generated/`；前端兼容视图写入
`frontend/public/data/`。旧命令 `python -m tools.build_frontend_data` 仍可使用，但内部也会
强制执行完整主流水线。

构建输出中的 `data-manifest.json` 记录输入语料哈希、稳定数据时间、实体数量与质量指标。
同一份输入重复构建必须产生相同数据库和 JSON。不要手改生成文件，也不要在抓取进程写包时执行构建。

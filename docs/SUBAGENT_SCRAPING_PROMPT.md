# 子 Agent 抓取与数据转换规范

本文档用于把一个独立的网页抓取子 agent 约束成“可审计的数据生产者”。它适用于 RankingSelect 的榜单、院校和硕士项目申请信息抓取。子 agent 不直接修改前端数据，也不把猜测写成事实；它只提交原始证据、结构化候选和校验报告。

## 1. 直接交给子 agent 的系统 Prompt

将下面内容作为子 agent 的 system prompt。调用方只需要在 user prompt 中传入批次和目标文件。

```text
你是 RankingSelect 的网页数据采集子 agent。你的工作是从公开网页或公开 API 获取院校排名、院校身份和官方硕士项目申请信息，并输出可追溯、可复核、符合数据契约的候选数据。

你的首要原则：证据优先、宁缺毋滥、不可臆测、可重复运行。

【范围】
1. 只处理调用方给出的 target；不要擅自扩大院校、榜单、年份或项目范围。
2. 申请信息优先使用院校官方项目页、官方招生页、官方 PDF 和官方 API。
3. 排名信息使用对应榜单发布方的页面/API/公开快照；第三方页面只能用于发现 URL，不能作为最终事实来源。
4. 不绕过登录、付费墙、验证码或访问控制；遇到阻断就记录 blocked，不要编造结果。
5. 当前公开申请周期是 27fall（2027 入学，除非任务显式指定其他周期）。

【身份和 ID】
1. university_id 必须使用输入 target 的 canonical ID；不能根据页面标题另造学校 ID。
2. 项目是具体的学位项目，不是“硕士项目”“招生信息”这类目录页。
3. 稳定项目 ID 为 university_id + campus_id + normalized_program_code。
4. ID 只允许小写 ASCII 字母、数字、下划线和短横线。项目名称变更不改变既有 ID；同项目不同学年使用 admission cycle，不重复建项目。

【状态】
1. 抓到网页不等于事实已核验。抓取结果默认 verification_status=extracted；无法从证据安全结构化时使用 needs_review。
2. 只有人工核对后才能使用 verified。你不得自行把 extracted 或 needs_review 改为 verified。
3. 页面过期使用 stale，页面明确不是目标或内容错误使用 rejected，访问失败使用 blocked（blocked 只出现在抓取报告/原始记录中，不伪造 sources）。
4. 缺失、含糊、冲突的信息必须保留 unknown/needs_review 和证据，不得用 0、空字符串、今天的日期或常识补齐。

【证据要求】
每一条结构化事实都必须能回指一个 source：URL、页面标题、抓取时间（含时区）、内容 hash，以及足以复核的原文短摘录。摘录应包含字段名和数值上下文，不要只截一个孤立数字。若页面有多个候选值，全部记录并标记冲突，不要静默覆盖。

【禁止行为】
- 不把搜索结果摘要、URL slug、导航文字或页面标题当作截止日期/成绩/费用事实。
- 不把“未找到要求”解释为 not_required；只能写 unknown。
- 不把项目目录、admissions hub、新闻、活动、cookie、404、登录页当作具体项目。
- 不从一个项目推断另一个项目、从上一年度推断本年度，或从一个申请人群推断全部申请人。
- 不删除已有来源；冲突由人工 review 解决。

【交付】
每个 target 都要输出一个结果对象，至少包括：status、captured_pages、facts、candidates、issues、next_action。
成功时同时保存原始响应/HTML/PDF（或压缩文件）和 manifest；任何事实都通过 source_id 关联来源。最终候选必须能转换到：
- raw/universities/<university_id>/manifest.json
- raw/universities/<university_id>/projects.json
- raw/universities/<university_id>/sources.json
- raw/universities/<university_id>/reviews.json
- raw/universities/<university_id>/raw/source_evidence.json

结束前执行：ID 唯一性、URL、source_id 外键、27fall 周期、日期类型、费用金额和 JSON Schema 检查，并报告每一项失败原因。
```

## 2. 每批任务的 User Prompt 模板

把实际目标替换到尖括号内。一个子 agent 一次只处理一个小批次，建议 5--20 所学校或一个榜单 edition，便于失败重试和人工校对。

```text
任务：抓取并规范化一个 RankingSelect 数据批次。

批次信息
- batch_id: <例如 programs_27fall_2026-08-19_01>
- data_kind: <ranking | university | program_admission>
- current_cycle: 27fall
- retrieved_at: <ISO 8601，带 Z 或时区偏移>
- target_file: <输入 JSON 文件绝对路径>
- output_dir: <原始证据和结果输出目录绝对路径>

目标列表
<逐条粘贴 target JSON；至少包含 universityId/name/country/indexUrl；榜单任务还需 source/year>

执行要求
1. 先读取 target 文件和仓库的 docs/DATA_CONTRACT.md、schemas/manifest.schema.json、schemas/projects.schema.json、schemas/sources.schema.json、schemas/reviews.schema.json。
2. 为每个 target 先检查 canonical URL，再按“官方项目目录/学院目录 -> 具体项目页 -> 官方招生/费用/语言页 -> 官方 PDF”顺序发现页面。搜索引擎只用于发现，不能作为证据。
3. 每次导航记录最终 URL、HTTP 状态、页面标题、content type、是否被重定向/阻断和抓取时间。保存原始响应，不覆盖同 URL 的旧快照。
4. 先分类页面：concrete_program、official_admission、official_fee、official_ranking、directory、news、navigation、error、blocked。只有 concrete_program 和对应官方事实页可进入候选。
5. 每个字段记录 raw_value、normalized_value、source_id、evidence_text、locator（CSS/XPath/段落标题或 PDF 页码）、verification_status、confidence 和 issues。
6. 项目申请信息至少尝试抽取：项目名称、学位、学科、授课语言、学习方式、官方 URL、申请截止日/轮次/申请人群、语言考试和最低分、GRE、GMAT、学术背景、学费、注册费。
7. 排名任务至少抽取：source、edition/year、rank、university name、country/region、score（页面明确提供时），并保留排名条目原文和原始响应。
8. 无法安全确认的值使用 unknown 或 needs_review。日期只能使用 exact/month/range/rolling/tba/unknown；不要从“通常”“往年”推导 27fall 日期。
9. 对同一项目去重：优先 canonical URL；其次使用规范化名称 + 校区 + 学位。冲突记录为 issues，不丢弃任一 source。
10. 输出 JSONL：每行一个 target_result；另外输出 summary.json。失败 target 也必须有结果行。

交付判定
- captured：原始文件和 manifest 均存在且可读取。
- extracted：至少有一个带证据的候选事实。
- needs_review：页面可访问，但事实不完整、冲突或解析置信度不足。
- blocked：无法访问或必须人工浏览器处理。
- no_concrete_project：只找到目录/招生 hub，没有具体项目页。

不要修改 frontend/public/data/*.json、normalized/rankingselect.sqlite 或已有手工维护包。完成后只报告输出路径、计数、阻塞原因和建议的下一步。
```

## 3. 推荐的中间 JSONL 格式

JSONL 是抓取层和转换层之间的边界；它比直接生成 `projects.json` 更容易审计和重跑。字段可扩展，但以下字段必须保持稳定：

```json
{
  "record_type": "program_fact",
  "batch_id": "programs_27fall_2026-08-19_01",
  "university_id": "u_tu_delft",
  "target_name": "Delft University of Technology",
  "project_key": {
    "name_raw": "MSc Computer Science",
    "campus_raw": "Delft",
    "degree_raw": "MSc",
    "official_url": "https://example.edu/msc-computer-science"
  },
  "cycle_id": "27fall",
  "field": "timeline.application_deadline",
  "value_raw": "1 December 2026 for non-EU applicants",
  "value_normalized": {
    "event": "application_deadline",
    "date_type": "exact",
    "date": "2026-12-01",
    "date_end": null,
    "applicant_group": "non_eu",
    "round": null
  },
  "source": {
    "url": "https://example.edu/admissions",
    "source_type": "official_web",
    "title": "Admission and application",
    "retrieved_at": "2026-08-19T12:00:00Z",
    "content_hash": "sha256:...",
    "evidence_text": "Applications from non-EU applicants must be submitted by 1 December 2026.",
    "locator": "Admissions > Deadlines > Non-EU"
  },
  "verification_status": "extracted",
  "confidence": 0.96,
  "issues": []
}
```

`record_type` 建议使用 `program_candidate`、`program_fact`、`ranking_entry`、`university_identity`、`page_capture`、`crawl_issue`。`field` 使用稳定路径，例如 `project.name`、`timeline.application_deadline`、`requirements.language`、`fee.tuition`。

## 4. 从抓取结果转换为可用数据

转换必须是确定性的：相同输入快照应生成相同 ID、排序和 JSON。建议按以下顺序执行。

### 4.1 先建立来源表

对每个不同的官方 URL 生成稳定 `source_id`，例如 `src_` 加 URL 的 SHA-256 前 12 位。写入 `sources.json`：

```json
{
  "source_id": "src_4f0b8c1a2d3e",
  "url": "https://example.edu/admissions",
  "source_type": "official_web",
  "retrieved_at": "2026-08-19T12:00:00Z",
  "verification_status": "extracted",
  "title": "Admission and application",
  "content_hash": "sha256:...",
  "evidence_text": "..."
}
```

同一 URL 的不同抓取快照不能互相覆盖；可保留最新 source 记录，并把历史快照放在 `raw/source_evidence.json`。`verified` 只能由人工 review 产生。

### 4.2 建立具体项目

1. 丢弃 directory、hub、news、navigation、error 和仅含“Master programmes”之类泛标题的页面。
2. `name` 使用页面明确的具体项目名；`degree` 和 `subject` 只有页面有证据时才填写。
3. `normalized_program_code = slug(name + 必要的学位/校区信息)`，去重后加稳定 hash 解决同名冲突。
4. 生成 `project_id = <university_id>_<campus_id>_<normalized_program_code>`，并检查同校唯一。
5. `official_url` 必须是 HTTP(S) 官方页面；项目入口和事实来源可以不同，所有事实仍要指向各自的 `source_id`。

### 4.3 创建 admission cycle

对于本批次的 2027 秋季入学，创建：

```json
{
  "cycle_id": "27fall",
  "academic_year": 2027,
  "entry_term": "fall",
  "status": "current",
  "timelines": [],
  "requirements": {},
  "fees": []
}
```

旧年份不要复制成 27fall；如果只有旧年份证据，保留为 `historical`，并把当前周期字段设为 `unknown`/`needs_review`。

### 4.4 Timeline 映射

| 抓取文本 | 规范化 | 规则 |
| --- | --- | --- |
| `1 December 2026` | `date_type=exact`, `date=2026-12-01` | 必须有明确日、月、年 |
| `December 2026` | `date_type=month`, `date=2026-12` | 不补具体日 |
| `1 Dec 2026 - 15 Jan 2027` | `date_type=range` | 同时写 `date`、`date_end` |
| `rolling admissions` | `date_type=rolling` | 日期均为 null |
| `to be announced` | `date_type=tba` | 日期均为 null |
| 页面没有截止日 | `date_type=unknown` | 不写猜测日期 |

每个 timeline 必须有 `event`、`applicant_group`、`round`（没有就 null）、`source_id` 和 `verification_status`。EU/non-EU、国际/本地、奖学金等不同人群不能合并成一条。

### 4.5 Requirements 映射

- IELTS/TOEFL 等写入 `language.tests[]`，分数保留字符串，例如 `"7.0"`、`"100"`。
- 页面写“English proficiency may be waived”时，状态通常仍是 `required`，豁免条件写入 `notes` 或 `academic.description`，不要误写 `not_required`。
- 没有 GRE/GMAT 证据时为 `unknown`；明确写“不需要”才是 `not_required`；明确写“可选”才是 `optional`。
- 学术背景写入 `academic.description`，状态按页面使用 `required`/`optional`/`unknown`。
- 无法映射的材料（CV、推荐信、作品集等）写入 `requirements.notes`，不要塞进语言考试数组。

示例：

```json
{
  "language": {
    "status": "required",
    "tests": [
      {"name": "IELTS", "min_score": "7.0"},
      {"name": "TOEFL iBT", "min_score": "100"}
    ]
  },
  "gre": {"status": "unknown", "min_score": null},
  "gmat": {"status": "not_required", "min_score": null},
  "academic": {"status": "required", "description": "Relevant bachelor's degree."},
  "notes": "CV and motivation letter are listed on the official application checklist.",
  "source_id": "src_4f0b8c1a2d3e",
  "verification_status": "needs_review"
}
```

### 4.6 Fee 映射

只生成 `tuition` 或 `registration`。`amount` 必须是 `unknown` 或非负数字字符串；货币、周期、申请人群和条件分别写入 `currency`、`period`、`applicant_group`、`condition`。`varies`、区间、`€12k` 或“视情况而定”不能放进 amount，应保留 amount=`unknown` 并把原文放入 condition/证据。

### 4.7 冲突处理

同一字段有多个官方值时：

1. 每个值都保留为候选记录和独立 source。
2. 不在转换器中按“看起来最新”静默覆盖。
3. 需要人工选择时，写入 `reviews.json`，包含 `selected_source_id`、`rejected_source_ids`、决定理由、审核人和时间。
4. 在 review 完成前，发布字段保持 `needs_review`；不能假装已经 verified。

## 5. 榜单条目的额外转换

榜单 adapter 统一经过 `fetch -> parse -> normalize -> validate` 四步：

1. `fetch` 保存不可变的原始响应快照、请求 URL、时间、状态码和 adapter_version。
2. `parse` 从 JSON、HTML 的结构化数据或 CSV 提取原始 rank/name/country/score，不从视觉位置猜列。
3. `normalize` 统一字段为 `source`、`edition/year`、`rank`、`university_id`、`university_name`、`country`、`score`；名次区间、并列名次和缺失分数保持原语义。
4. `validate` 检查 rank 类型、重复项、edition 一致性、学校 ID 映射和数量；失败时保留上一份有效快照并标记 fallback。
5. 不同榜单的名次不能直接做数学平均，除非产品另有明确算法；跨榜展示应保留来源和原始 edition。

## 6. 子 agent 交付前检查清单

- [ ] 每个 target 都有结果行，包括 blocked/no_concrete_project。
- [ ] 所有事实都有官方 source、抓取时间、hash、原文摘录和定位信息。
- [ ] 没有把搜索摘要、目录页、旧年份或常识写成当前周期事实。
- [ ] project ID、cycle ID 和 source ID 合法且唯一。
- [ ] 所有 `source_id` 都能在 `sources.json` 找到。
- [ ] 27fall 的 exact/month/range/rolling/tba/unknown 与日期字段匹配。
- [ ] 未确认的语言、GRE、GMAT、学术要求和费用使用 unknown/needs_review。
- [ ] fee amount 没有货币符号、区间、自由文本或 0 代替未知。
- [ ] 冲突来源没有被删除，待裁决内容有 review 记录。
- [ ] 原始抓取文件可重新读取，输出 JSON 可解析，Schema 与语义校验均通过。
- [ ] 没有修改前端生成数据或人工维护包；交付报告包含输出路径和下一步。

## 7. 推荐的主 agent 合并流程

主 agent 收到子 agent 输出后，不要直接复制 `facts` 到前端。建议依次执行：

```text
JSONL 结果
  -> 按 source URL 去重并保存 raw/source_evidence.json
  -> 建立 sources.json
  -> 过滤非具体项目和低质量页面
  -> 规范化 project/cycle/timeline/requirements/fee
  -> 生成 reviews.json（仅冲突或人工裁决）
  -> 运行 Schema + 语义校验
  -> 转换到 SQLite / generated JSON
  -> 最后才供 frontend/public/data 使用
```

推荐先运行 `python -m unittest tools.test_txt_to_package -v` 和相关 scraper 测试，再运行前端构建。任何结构、ID、外键或来源引用错误都应阻止合并；仅信息缺失可以以 `unknown`、`needs_review` 或 `stale` 进入人工队列。

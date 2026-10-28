# 榜单规范输入

每个榜单的当前 500 条快照位于 `raw/rankings/<source>/normalized.json`。
支持 `qs`、`the`、`arwu`、`usnews` 和 `csrankings`。
`frontend/public/data/rankings/*.json` 是流水线生成的展示数据，不能手改或作为抓取状态。

发布字段沿用 `rank`、`universityId`、`name`、`country`、`score` 和 `year`。
并列名次按官方值保留；区间名次的 `rank` 沿用区间下界语义，区间原文保存在原始响应中。
U.S. News 的 `year` 表示跨年版的起始年份，例如 `2026` 对应 `2026–2027`。
同校仅名称变动时保留已发布 ID；合并形成的新院校不复用原院校 ID。

## 2026-10-28 更新

| 榜单 | 原标注版本 | 当前版本 | 官方来源 |
| --- | --- | --- | --- |
| QS | 2026 | 2027 | [官方 Excel 下载页](https://www.qs.com/insights/qs-world-university-rankings-2027-results-table-excel) |
| THE | 2026 | 2027 | [官方榜单](https://www.timeshighereducation.com/world-university-rankings/2027/world-ranking) |
| ARWU | 2025 | 2026 | [官方榜单](https://www.shanghairanking.com/rankings/arwu/2026) |
| U.S. News | 2025 | 2026–2027 | [官方榜单](https://www.usnews.com/education/best-global-universities/rankings) |

四榜各 500 条，CS Rankings 本轮未更新。QS 使用官方发布的 2027 工作簿；THE 和 ARWU
复用现有抓取模块；U.S. News 在官方公开页面逐页读取前 50 页 SSR 数据，并核对每页版本、页码和条数。
每榜 `manifest.json` 记录本轮来源、响应文件和名称变体的 ID 映射；原始响应按独立时间戳留存，不覆盖历史证据。

QS 的旧快照已含新版分数，但部分并列名次被改成连续名次，本轮依据官方工作簿纠正；
U.S. News 本次抓取的排名和分数与旧快照一致，修正了旧快照的版本误标。
首页和榜单页改为从实际数据读取版本，避免展示年份继续滞后。
THE 新收录的 Constructor University 还触发了前端名称索引与 `Object.constructor` 的冲突；
名称索引已改为无原型字典，并在浏览器中回归了榜单切换和该校搜索。

更新规范输入后执行：

```bash
python -m tools.data_pipeline all --strict
python run_all_tests.py
npm --prefix frontend ci
npm --prefix frontend run build
```

`data-manifest.json` 的 `dataTimestamp` 沿用流水线的逻辑时间戳，包含榜单版次年份，
不表示实际抓取时间；本轮实际抓取时间见各榜 `manifest.json` 的 `capturedAt`。

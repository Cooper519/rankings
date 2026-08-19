"""启发式项目申请情报抓取(best-effort,verified=False)。

给定一个官方申请页 URL,尝试提取候选信息:
  - 截止日期(deadline):匹配 "deadline / application ... <月份/日期>" 模式
  - 申请材料(materials):匹配常见材料关键词
  - 语言要求(ielts/toefl):匹配 IELTS/TOEFL 分数
结果仅作提示,必须人工校对后再 verified=True。本工具聚焦「拿到官方源链接 + 线索」,
不追求精确解析(各国页面结构差异极大,精确解析需人工/规则库)。

依赖 utils.fetch(纯 stdlib)。仅提取文本,不渲染 JS,故对 JS 重渲染页效果有限。
"""
from __future__ import annotations
import re
from .schema import Program, Deadline, Requirements
from utils import fetch

# 月份(英)用于截止日期匹配
MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December"
          "|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec")
DATE_RE = re.compile(
    rf"\b(\d{{1,2}}\s+(?:{MONTHS})\s+20\d{{2}}|(?:{MONTHS})\s+\d{{1,2}},?\s*20\d{{2}}|"
    rf"\d{{4}}-\d{{2}}-\d{{2}})\b", re.I)
DEADLINE_CTX_RE = re.compile(
    rf"(deadline|application(?:\s+deadline)?|due\s+by|closes?\s+on|submit\s+by)[^.\n]{{0,60}}?({DATE_RE.pattern[1:-1]})",
    re.I | re.S)
MATERIALS = ["transcript", "cv", "curriculum vitae", "motivation letter", "statement of purpose",
             "recommendation", "reference letter", "letter of recommendation", "degree certificate",
             "bachelor", "english proof", "language certificate", "portfolio", "gre"]
IELTS_RE = re.compile(r"ielts[^0-9]{0,8}(\d[\d.]{1,3})", re.I)
TOEFL_RE = re.compile(r"toefl[^0-9]{0,8}(\d{2,3})", re.I)


def _strip_html(html: str) -> str:
    # 去 script/style,再去标签
    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html)


def scrape_program_page(university_id: str, subject: str, dept: str, program: str,
                         source_url: str) -> Program | None:
    """对单个官方页做启发式抓取,返回 Program(verified=False)。"""
    try:
        html = fetch(source_url).text
    except Exception as e:
        print(f"  [programs] 抓取失败 {source_url}: {e}")
        return None
    text = _strip_html(html)
    # 截止日期线索
    deadlines: list[Deadline] = []
    for m in DEADLINE_CTX_RE.finditer(text):
        date_raw = m.group(2).strip()
        if date_raw and not any(d.date in date_raw for d in deadlines):
            deadlines.append(Deadline(round="Application", date=date_raw))
    if not deadlines:
        # 退而求其次:取页面里出现的几个明确日期
        for m in DATE_RE.finditer(text):
            if len(deadlines) >= 3:
                break
            deadlines.append(Deadline(round="Application", date=m.group(1).strip()))
    # 材料
    mats = []
    low = text.lower()
    for kw in MATERIALS:
        if kw in low and kw.title() not in mats:
            mats.append(kw.title())
    # 语言要求
    req = Requirements()
    m = IELTS_RE.search(text)
    if m:
        req.ielts = m.group(1)
    m = TOEFL_RE.search(text)
    if m:
        req.toefl = m.group(1)
    return Program(
        id=f"{university_id}_{subject.lower().replace(' ', '_')}",
        universityId=university_id, subject=subject, dept=dept, program=program,
        deadlines=deadlines, materials=mats, requirements=req,
        sourceUrl=source_url, verified=False, updatedAt=Program.now(),
    )

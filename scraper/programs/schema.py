"""项目申请情报数据模型(与前端 frontend/src/types/index.ts 的 Program 对齐)。

字段说明:
  id            程序稳定 id(slug)
  universityId  对应 universities.json 的 id(用于关联院校)
  subject       学科大类(如 Computer Science / Mechanical Engineering)
  dept          学院/院系
  program       项目名称(英文名)
  deadlines     申请轮次与截止日期(round + ISO date)
  materials     所需材料清单(申请材料)
  requirements  硬性要求(gpa / ielts / toefl / language / academic)
  sourceUrl     官方源链接(供人工校对与跳转)
  verified      是否已人工校对(种子数据 True,抓取启发式 False)
  updatedAt     ISO 时间戳
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Deadline:
    round: str          # 如 "Round 1" / "Non-EU" / "Rolling"
    date: str           # ISO 日期 YYYY-MM-DD(或 YYYY-MM)


@dataclass
class Requirements:
    gpa: Optional[str] = None
    ielts: Optional[str] = None
    toefl: Optional[str] = None
    language: Optional[str] = None
    academic: Optional[str] = None


@dataclass
class Program:
    id: str
    universityId: str
    subject: str
    dept: str
    program: str
    deadlines: list[Deadline] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    requirements: Requirements = field(default_factory=Requirements)
    sourceUrl: str = ""
    verified: bool = False
    updatedAt: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["requirements"] = asdict(self.requirements)
        d["deadlines"] = [asdict(x) for x in self.deadlines]
        return d

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

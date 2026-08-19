"""合并种子(verified=True)+ Playwright MCP 抓取(verified=False) -> programs.json。

抓取数据为启发式、需人工校对(verified=False)。装配时:
  - 过滤明显非项目的噪音页(列表/申请指南/奖学金/活动/博士/学士/hub 等)
  - deadline 后处理:解析为 ISO、过滤过去日期、保留 Non-EU/EU/Round 轮次标签
  - 去重:种子 id 优先;抓取按 universityId + program slug 生成 id,与种子冲突时种子胜出
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
ROOT = Path(r"D:\code Analysis\Rankings")
sys.path.insert(0, str(ROOT / "scraper"))
from utils import slug, write_json
from programs.seed import SEED
from programs.normalize import normalize_deadlines

RAW = ROOT / "_programs_raw.json"
OUT = ROOT / "frontend" / "public" / "data" / "programs.json"

NOISE = re.compile(
    r"^(list of|browse|how to apply|entry requirement|scholarship|ask us|info day|"
    r"fellowship|master.s (programs|studies|programmes)|range of degree|"
    r"bachelor|doctoral|diploma|new degree|study at|study options|frequently asked|"
    r"admission services|apply to bachelor|programmes$|programs$|"
    r"admission to master|key skill|didactic|lifelong learning|"
    r"master.s degree studies|master.s programmes in |browse master.s)", re.I)
NOISE_ANY = re.compile(r"doctoral|\bph\.?d\b|bachelor of science and master|bachelor of business", re.I)


def is_noise(p: dict) -> bool:
    name = (p.get("program") or "").strip()
    if NOISE.search(name):
        return True
    if NOISE_ANY.search(name):
        return True
    if p.get("subject") == "General" and not p.get("deadlines") and len(p.get("materials", [])) < 2:
        return True
    return False


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


seed_dicts = [p.to_dict() for p in SEED]
seed_ids = {p["id"] for p in seed_dicts}
seed_keys = {(p["universityId"], norm(p["program"])) for p in seed_dicts}

raw = json.loads(RAW.read_text(encoding="utf-8")) if RAW.exists() else []
scraped = []
seen_id = set(); seen_key = set(); dropped = 0
for r in raw:
    if is_noise(r):
        dropped += 1; continue
    uid = r.get("universityId") or ""
    prog = (r.get("program") or "").strip()
    if not uid or not prog:
        dropped += 1; continue
    pid = f"{uid}_{slug(prog)}"
    key = (uid, norm(prog))
    if pid in seed_ids or key in seed_keys or pid in seen_id or key in seen_key:
        dropped += 1; continue
    seen_id.add(pid); seen_key.add(key)
    dl = normalize_deadlines(r.get("deadlines", []))
    scraped.append({
        "id": pid, "universityId": uid, "subject": r.get("subject", "General"),
        "dept": "", "program": prog,
        "deadlines": dl, "materials": r.get("materials", []),
        "requirements": r.get("requirements", {"gpa": None, "ielts": None, "toefl": None}),
        "sourceUrl": r.get("sourceUrl", ""), "verified": False,
        "updatedAt": r.get("updatedAt", ""),
    })

programs = seed_dicts + scraped
write_json(OUT, programs)
print(f"programs.json: {len(programs)} 条 (种子 {len(seed_dicts)} verified + 抓取 {len(scraped)} scraped)")
print(f"  过滤噪音/重复: {dropped}")
print(f"  scraped 有 deadline: {sum(1 for p in scraped if p['deadlines'])}")
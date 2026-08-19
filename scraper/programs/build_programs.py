"""聚合项目申请情报 -> frontend/public/data/programs.json。

数据来源:
  1) seed.py 人工整理的种子(verified=True,欧陆重点院校)
  2)(可选)programs_scraper 启发式抓取官方页(verified=False,需人工校对)

用法:
  python build_programs.py              # 仅种子
  python build_programs.py --scrape     # 种子 + 对每条种子 sourceUrl 启发式抓取补充

输出: ../frontend/public/data/programs.json
  schema 与 frontend/src/types/index.ts 的 Program 对齐。
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from .seed import SEED
from .schema import Program

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "data"


def build(scrape: bool = False) -> None:
    programs: list[Program] = list(SEED)
    if scrape:
        from .programs_scraper import scrape_program_page
        print("[programs] 启发式抓取种子 sourceUrl 补充线索(verified=False)...")
        extra = []
        for p in list(SEED):
            sp = scrape_program_page(p.universityId, p.subject, p.dept, p.program, p.sourceUrl)
            if sp:
                extra.append(sp)
        programs.extend(extra)
        print(f"  抓取补充 {len(extra)} 条(均 verified=False,待人工校对)")
    data = [p.to_dict() for p in programs]
    out = OUTPUT_DIR / "programs.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    verified = sum(1 for p in programs if p.verified)
    print(f"  programs.json: {len(data)} 条程序(已校对 {verified},待校对 {len(data) - verified})")
    print(f"  -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scrape", action="store_true", help="对种子 sourceUrl 做启发式抓取补充")
    args = ap.parse_args()
    build(scrape=args.scrape)

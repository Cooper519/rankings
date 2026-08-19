"""RankingSelect 爬虫入口。

输出: ../frontend/public/data/rankings/<source>.json, universities.json
用法: python main.py            # 抓取全部五榜并聚合
      python main.py --source qs  # 仅抓单榜
"""
import argparse
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public" / "data"
RANKINGS = ("qs", "the", "arwu", "usnews", "csrankings")


def run(source: str) -> None:
    mod = {
        "qs": "rankings.qs",
        "the": "rankings.the_rankings",
        "arwu": "rankings.arwu",
        "usnews": "rankings.usnews",
        "csrankings": "rankings.csrankings",
    }[source]
    import importlib
    m = importlib.import_module(mod)
    m.scrape(OUTPUT_DIR)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=RANKINGS, help="指定单榜抓取;省略则全部")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "rankings").mkdir(exist_ok=True)
    sources = (args.source,) if args.source else RANKINGS
    for s in sources:
        print(f"[{s}] 抓取中...")
        try:
            run(s)
        except Exception as e:
            print(f"  [{s}] 失败: {e}")
    # 全量抓取后聚合 universities.json
    if not args.source:
        print("[build] 聚合 universities.json...")
        import build_universities
        build_universities.build()
        print("[build] 构建 programs.json(种子数据)...")
        import programs.build_programs
        programs.build_programs.build()
    print("完成。输出目录:", OUTPUT_DIR)

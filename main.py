import argparse
import asyncio
import importlib
import os
import sys

from core.scheduler import run_spiders
from core.config import MAX_CONCURRENCY
from utils.symbol.factor_calculator import FactorCalculator
import datetime

def get_available_markets() -> list:
    """
    自动扫描 spider 目录，发现所有带有 merge.py 的市场子目录。

    例如存在：
      spider/ashare/merge.py
      spider/fund/merge.py
      spider/crypto/merge.py
    则返回: ["ashare", "fund", "crypto"]
    """
    # 当前文件所在目录: .../FactorMachine
    current_dir = os.path.dirname(os.path.abspath(__file__))
    spider_dir = os.path.join(current_dir, "spider")

    if not os.path.isdir(spider_dir):
        print(f"错误：市场目录不存在: {spider_dir}")
        sys.exit(1)

    markets = []
    for item in os.listdir(spider_dir):
        market_path = os.path.join(spider_dir, item)
        if not os.path.isdir(market_path):
            continue
        merge_file = os.path.join(market_path, "merge.py")
        if os.path.exists(merge_file):
            markets.append(item)

    if not markets:
        print(f"错误：在 {spider_dir} 下未发现任何包含 merge.py 的市场子目录")
        sys.exit(1)

    return markets


def dynamic_import_merge(market: str):
    """
    动态导入指定市场的 merge 函数，相当于 spider.{market}.merge.merge

    要求：
      - 存在模块 spider.{market}.merge
      - 模块内存在可调用对象 merge
    """
    try:
        module = importlib.import_module(f"spider.{market}.merge")
    except ImportError as e:
        print(f"错误：无法导入 spider.{market}.merge 模块: {e}")
        sys.exit(1)

    try:
        merge_func = getattr(module, "merge")
    except AttributeError:
        print(f"错误：模块 spider.{market}.merge 中未找到 merge 函数")
        sys.exit(1)

    if not callable(merge_func):
        print(f"错误：spider.{market}.merge.merge 不是可调用对象")
        sys.exit(1)

    return merge_func


def main():
    parser = argparse.ArgumentParser(description="AkShare 多市场爬虫与因子计算框架")
    parser.add_argument(
        "--mode",
        choices=["full", "update", "spec"],
        default="full",
        help="运行模式: full(全量) / update(增量) / spec(指定爬虫增量)",
    )
    parser.add_argument(
        "--spec",
        help="spec 模式下指定爬虫类名 (例如: StockHistSpider)",
    )
    parser.add_argument(
        "--start-date",
        default="19700101",
        help="开始日期, 格式 YYYYMMDD 或 YYYY-MM-DD (若不指定则由 mode+last_update 决定)",
    )
    parser.add_argument(
        "--end-date",
        default=datetime.datetime.now().strftime("%Y%m%d"),
        help="结束日期, 格式 YYYYMMDD 或 YYYY-MM-DD (若不指定则默认到今天)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=MAX_CONCURRENCY,
        help="最大并发数",
    )
    parser.add_argument(
        "--factors",
        action="store_true",          # 是否“只计算因子”
        help="单独计算因子（不再重新爬取）",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="只执行合并（不跑爬虫；建议与 --factors 配合使用）",
    )
    parser.add_argument(
        "--market",
        default="all",
        help="指定市场: all(默认, 表示全部市场) 或单个市场名 (如 ashare, fund, crypto)",
    )

    args = parser.parse_args()

    # 自动发现所有可用市场
    available_markets = get_available_markets()

    # 根据参数决定本次要处理的市场列表
    if args.market == "all":
        markets = available_markets
    else:
        if args.market not in available_markets:
            print(f"错误：市场 '{args.market}' 不在可用市场列表中: {available_markets}")
            sys.exit(1)
        markets = [args.market]

    print(f"可用市场: {available_markets}")
    print(f"本次处理市场: {markets}")

    # 如果不是“只计算因子”，则需要先跑一遍爬虫
    if not args.factors:
        for market in markets:
            print(f"\n=== 开始运行 {market} 市场爬虫 ===")
            asyncio.run(
                run_spiders(
                    mode=args.mode,
                    spec=args.spec,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    max_concurrency=args.concurrency,
                )
            )
            print(f"=== {market} 市场爬虫完成 ===")

    # 计算因子前，对每个市场可选择性执行 merge
    if args.merge:
        for market in markets:
            print(f"\n=== 开始合并 {market} 市场 parquet ===")
            merge_func = dynamic_import_merge(market)
            merge_func()
            print(f"=== {market} 市场合并完成 ===")

    # 因子计算：对每个市场基于其合并后的 parquet 计算因子
    for market in markets:
        print(f"\n=== 开始计算 {market} 市场因子 ===")
        loader = FactorCalculator(market_type=market)
        loader.run_factors(['ma_26'],max_workers=args.concurrency)
        print(f"=== {market} 市场因子计算完成 ===")


if __name__ == "__main__":
    main()
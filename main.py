import argparse
import asyncio
import datetime
import sys
from typing import List

from core.task import init_task_factory, get_all_tasks, get_task
from core.scheduler import Scheduler
from core.config import MAX_CONCURRENCY

# 假设以下函数在别处定义
from utils.market import get_available_markets
from utils.merge import dynamic_import_merge
from factors.calculator import FactorCalculator


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
        default=False,
        action="store_true",
        help="单独计算因子（不再重新爬取）",
    )
    parser.add_argument(
        "--merge",
        default=False,
        action="store_true",
        help="只执行合并（不跑爬虫；建议与 --factors 配合使用）",
    )
    parser.add_argument(
        "--market",
        default="all",
        help="指定市场: all(默认, 表示全部市场) 或单个市场名 (如 ashare, fund, crypto)",
    )

    args = parser.parse_args()

    # ---------- 1. 初始化任务工厂（加载所有爬虫任务） ----------
    init_task_factory()  # 默认扫描 spider 目录，基类 BaseSpider

    # 自动发现所有可用市场（基于 merge.py 存在与否）
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

    # ---------- 2. 爬虫执行（使用新调度器） ----------
    if not args.factors:
        # 确定要执行的任务列表
        tasks_to_run = []
        if args.spec:
            # 指定了爬虫类名，直接获取该任务
            task = get_task(args.spec)
            if task:
                tasks_to_run = [task]
            else:
                print(f"错误：未找到任务 {args.spec}")
                sys.exit(1)
        else:
            # 未指定 spec：获取所有爬虫任务，并按市场筛选
            all_tasks = get_all_tasks()
            for task in all_tasks:
                # 从任务元数据中获取模块名，解析市场
                module_name = task.metadata.get("module", "")
                # 模块名形如 spider.ashare.xxx_spider
                parts = module_name.split(".")
                if len(parts) >= 2 and parts[0] == "spider":
                    task_market = parts[1]
                    if task_market in markets:
                        tasks_to_run.append(task)
        if not tasks_to_run:
            print("没有找到符合条件的爬虫任务，退出")
            sys.exit(1)

        # 创建调度器并运行任务
        scheduler = Scheduler(max_concurrency=args.concurrency)
        kwargs = {
            "start_date": args.start_date,
            "end_date": args.end_date,
        }
        print(f"将执行 {len(tasks_to_run)} 个任务: {[t.name for t in tasks_to_run]}")
        results = asyncio.run(scheduler.run_tasks([t.name for t in tasks_to_run], **kwargs))
        # 输出简要执行结果
        for task_name, result in results.items():
            status = result.get("status", "unknown")
            if status == "failed":
                print(f"任务 {task_name} 执行失败: {result.get('error')}")
            else:
                print(f"任务 {task_name} 执行成功")

    # ---------- 3. 合并与因子计算（保持原有逻辑） ----------
    if args.merge:
        for market in markets:
            print(f"\n=== 开始合并 {market} 市场 parquet ===")
            merge_func = dynamic_import_merge(market)
            merge_func()
            print(f"=== {market} 市场合并完成 ===")
    if args.factors:
        for market in markets:
            print(f"\n=== 开始计算 {market} 市场因子 ===")
            loader = FactorCalculator(market_type=market)
            loader.run_factors(max_workers=args.concurrency)
            print(f"=== {market} 市场因子计算完成 ===")


if __name__ == "__main__":
    main()
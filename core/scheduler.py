# core/scheduler.py
import os
import glob
import importlib
import asyncio
from typing import List, Optional, Tuple, Dict

from spider.base_spider import BaseSpider
from .storage import save_dataframe, get_last_update_date, load_dataframe
from .config import MAX_CONCURRENCY
from utils.compat.normalize_date import normalize_date_str
import pandas as pd


class ResourceLockManager:
    _locks: Dict[str, asyncio.Lock] = {}
    
    @classmethod
    def get_lock(cls, resource_id: str) -> asyncio.Lock:
        if resource_id not in cls._locks:
            cls._locks[resource_id] = asyncio.Lock()
        return cls._locks[resource_id]


def load_all_spiders() -> List[BaseSpider]:
    spiders: List[BaseSpider] = []
    spiders_dir = os.path.join(os.path.dirname(__file__), "..", "spider")
    markets = ["ashare", "fund", "us", "crypto"]
    for market in markets:
        files = glob.glob(os.path.join(spiders_dir, market, "*spider.py"))
        for file in files:
            module_name = os.path.splitext(os.path.basename(file))[0]
            if module_name.startswith("_"):
                continue
            module = importlib.import_module(f"spider.{market}.{module_name}")
            for attr in dir(module):
                obj = getattr(module, attr)
                if isinstance(obj, type) and issubclass(obj, BaseSpider) and obj is not BaseSpider:
                    spiders.append(obj())
    return spiders


async def run_spiders(
    mode: str = "full",
    spec: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_concurrency: Optional[int] = None,
):
    if max_concurrency is None:
        max_concurrency = MAX_CONCURRENCY

    spiders = load_all_spiders()
    if spec:
        spiders = [s for s in spiders if s.__class__.__name__ == spec]

    if not spiders:
        return

    from datetime import date
    today_yyyymmdd = normalize_date_str(date.today().strftime("%Y%m%d"))
    end_date = end_date or today_yyyymmdd

    # 使用rich的进度管理器
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        expand=True
    )
    
    # 为每个爬虫创建进度任务
    with progress:
        spider_tasks = {}
        for spider in spiders:
            task_desc = f"{spider.__class__.__name__}"
            task_id = progress.add_task(task_desc, total=100)  # 先设为100，具体进度在爬虫内更新
            spider_tasks[spider] = task_id
        
        async def _run_one(spider: BaseSpider):
            task_id = spider_tasks[spider]
            resource = getattr(spider, "resource")
            table_name = getattr(spider, "table_name")
            
            # 更新模式跳过今日已更新的
            last_update = get_last_update_date(table_name)
            start_date = last_update if last_update else None
            if mode == "update" and last_update == today_yyyymmdd:
                progress.update(task_id, completed=100)
                return
            
            # 获取对应资源的锁
            lock = ResourceLockManager.get_lock(resource)
            async with lock:
                try:
                    # 将进度条对象传递给爬虫
                    df = await spider.run(
                        start_date=start_date, 
                        end_date=end_date,
                        progress=progress,
                        task_id=task_id
                    )
                except Exception as e:
                    progress.update(task_id, description=f"{spider.__class__.__name__} [red]ERROR")
                    raise e
                
                if df is not None and hasattr(df, "empty") and not df.empty and table_name:
                    if mode == "update":
                        try:
                            old_df = load_dataframe(table_name)
                        except Exception:
                            old_df = None
                        if old_df is not None and hasattr(old_df, "empty") and not old_df.empty:
                            df = pd.concat([old_df, df], ignore_index=True)
                            key_cols = []
                            for col in ["date", "code"]:
                                if col in df.columns:
                                    key_cols.append(col)
                            if key_cols:
                                df = df.drop_duplicates(
                                    subset=key_cols,
                                    keep="last",
                                )
                    save_dataframe(df, table_name)
                
                progress.update(task_id, completed=100, description=f"{spider.__class__.__name__} [green]DONE")

        # 创建并发任务
        sem = asyncio.Semaphore(max_concurrency)
        
        async def _run_with_semaphore(spider: BaseSpider):
            async with sem:
                await _run_one(spider)
        
        # 并发运行所有爬虫
        await asyncio.gather(*(_run_with_semaphore(sp) for sp in spiders))
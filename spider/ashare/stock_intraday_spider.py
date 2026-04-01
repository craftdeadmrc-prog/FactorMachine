"""
封ip比较严苛
"""
# spider/stock/stock_intraday_sina_spider.py
import asyncio
import logging
import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
from typing import List, Dict
from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.proxy import proxy_pool, PROXY_FILE
from core.scheduler import task
logger = logging.getLogger(__name__)
# @task(description="获取A股日内逐笔快照数据（新浪）")
class StockIntradaySinaSpider(BaseSpider):
    """
    A股日内大单逐笔爬虫
    目标：写入表 kline_1s
    数据源：新浪财经-日内逐笔 (ak.stock_intraday_sina)
    说明：仅获取大于400手的成交数据，最多获取最近20个交易日数据
    """
    resource = "ashare_sina"
    table_name = "kline_1s"
    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)
    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        """
        统一字段命名和格式
        """
        if df.empty:
            return df
        rename_map = {
            "ticktime": "date",
            "price": "open",
            "kind": "type"
        }
        if "prev_price" in df.columns:
            df = df.drop(columns=["prev_price"])
        df = df.rename(columns=rename_map)
        # 添加元数据字段
        df["symbol"] = symbol
        df["market"] = market
        # 确保日期格式正确
        df["date"] = pd.to_datetime(df["date"])
        # 确保数值类型
        for col in ["open"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # 按时间排序
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df
    def check(self):
        super().check()
    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return
        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务，并发执行...")
        # 信号量控制最大并发数
        semaphore = asyncio.Semaphore(len(PROXY_FILE))
        async def fetch_and_save(task_idx, task):
            symbol = task.get("symbol")
            market = task.get("market")
            code = f"{market}{symbol}"
            # 1. 确定日期范围
            end_date_str = task.get("end_date")
            if end_date_str:
                try:
                    end_dt = pd.to_datetime(end_date_str)
                except:
                    end_dt = pd.Timestamp.now()
            else:
                end_dt = pd.Timestamp.now()
            # 生成日期列表 (倒推20日)
            date_list = []
            for i in range(20):
                d = end_dt - timedelta(days=i)
                # === 过滤周末 ===
                # weekday(): 周一为0, 周日为6
                if d.weekday() >= 5: 
                    continue
                date_list.append(d.strftime("%Y%m%d"))
            # === 修改部分：改回 for 循环顺序爬取各日 ===
            for d_str in date_list:
                async with semaphore:
                    try:
                        # 调用接口
                        df = await asyncio.to_thread(
                            proxy_pool,
                            ak.stock_intraday_sina,
                            symbol=code,
                            date=d_str
                        )
                        if df is None or df.empty:
                            continue
                        # 数据清洗
                        df = df.dropna()
                        df = self._rename_columns(df, symbol, market)
                        # 保存数据
                        save_dataframe(
                            df,
                            table_name=self.table_name,
                            db=self.market,
                            primary_key=["symbol", "date"]
                        )
                        # 适当休眠防封
                        await asyncio.sleep(1)
                        if task_idx % 20 == 0:
                            logger.info(f"[{task_idx}/{total}] {code} {d_str} 保存成功 ({len(df)}条)")
                    except KeyError:
                        # 非交易日或无大单成交，静默跳过
                        pass
                    except Exception as e:
                        logger.warning(f"股票 {code} 日期 {d_str} 获取失败: {e}")
        # 2. 构建所有任务的并发协程
        all_coroutines = []
        for idx, t in enumerate(self.tasks, 1):
            all_coroutines.append(fetch_and_save(idx, t))
        # 3. 统一并发执行
        await asyncio.gather(*all_coroutines)
        logger.info(f"{self.__class__.__name__}: 数据抓取完成，共处理 {total} 个任务")
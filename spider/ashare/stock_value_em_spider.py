import asyncio
import random
import logging
import pandas as pd
import akshare as ak
from typing import List, Dict

from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.proxy import proxy_pool
from core.scheduler import task
from core.config import MAX_CONCURRENCY

logger = logging.getLogger(__name__)

@task(description="获取A股估值数据（PE、PB、市值等）")
class StockValueEmSpider(BaseSpider):
    resource = "ashare_eastmoney"
    table = "valuation"

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        rename_map = {
            "数据日期": "date",
            "总市值": "market_cap",
            "流通市值": "circulating_market_cap",
            "总股本": "capitalization",
            "PE(TTM)": "pe_ratio",
            "PE(静)": "pe_ratio_lyr",
            "市净率": "pb_ratio",
            "PEG值": "peg",
            "市现率": "pcf_ratio",
            "市销率": "ps_ratio",
        }
        keep_src_cols = [c for c in rename_map.keys() if c in df.columns]
        df = df[keep_src_cols].rename(columns=rename_map)
        df["date"] = pd.to_datetime(df["date"])
        df["symbol"] = symbol
        df["market"] = market
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df

    def check(self):
        # 只调用父类的 check，完成基础的任务过滤（如数据完整性检查）
        super().check()

    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")

        async def process_one_task(task):
            market = task['market']
            symbol = task['symbol']

            # 添加随机延时，避免请求过快
            # await asyncio.sleep(random.randint(0, 1))

            try:
                # 使用代理池包装 akshare 接口
                df = await asyncio.to_thread(
                    proxy_pool,
                    ak.stock_value_em,
                    symbol=symbol
                )
            except Exception as e:
                logger.error(f"获取股票 {symbol} 估值数据失败: {e}")
                return None

            if df.empty:
                logger.warning(f"股票 {symbol} 返回空数据")
                return None

            # 丢弃不需要的列
            df = df.drop(columns=['当日收盘价', '流通股本'], errors='ignore')
            df = self._rename_columns(df, symbol, market)
            return df

        batch_size = MAX_CONCURRENCY
        for i in range(0, total, batch_size):
            batch_tasks = self.tasks[i:i + batch_size]
            tasks = [asyncio.create_task(process_one_task(one_task)) for one_task in batch_tasks]
            results = await asyncio.gather(*tasks)
            valid_dfs = [df for df in results if df is not None and not df.empty]

            if valid_dfs:
                batch_df = pd.concat(valid_dfs, ignore_index=True)
                try:
                    save_dataframe(
                        batch_df,
                        table=self.table,
                        db=self.market,
                        primary_key=["symbol", "date"]
                    )
                    logger.info(f"{self.__class__.__name__} [{min(i + batch_size, total)}/{total}] 批量保存估值数据，共 {len(batch_df)} 条")
                except Exception as e:
                    logger.error(f"批量插入股票估值数据失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")

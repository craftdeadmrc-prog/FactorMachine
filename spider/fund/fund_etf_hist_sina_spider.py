# spider/fund/fund_etf_hist_sina_spider.py（修改后）

import asyncio
import logging
import pandas as pd
import akshare as ak
from typing import List, Dict

from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)

@task(description="获取ETF日线行情数据（新浪）")
class EtfDailySinaSpider(BaseSpider):
    resource = "fund_sina"
    table_name = "kline_1d"

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        if "prevclose" in df.columns:
            df.drop(columns=["prevclose"], inplace=True)
        df["date"] = pd.to_datetime(df["date"])
        df["symbol"] = symbol
        df["market"] = market
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df

    def check(self):
        super().check()

    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")

        for idx, task in enumerate(self.tasks, 1):
            logger.info(f"{self.__class__.__name__} [{idx}/{total}] 正在处理 {task['symbol']}")

            market = task['market']
            symbol = task['symbol']
            code = f"{market}{symbol}"

            try:
                df = await asyncio.to_thread(
                    proxy_pool,
                    ak.fund_etf_hist_sina,
                    symbol=code
                )
            except Exception as e:
                logger.error(f"获取ETF {code} 日频数据失败: {e}")
                continue

            if df.empty:
                logger.warning(f"ETF {code} 返回空数据")
                continue

            df = self._rename_columns(df, symbol, market)

            try:
                save_dataframe(
                    df,
                    table_name=self.table_name,
                    db=self.market,
                    primary_key=["symbol", "date"]
                )
                logger.info(f"ETF {code} 日线数据已保存，共 {len(df)} 条")
            except Exception as e:
                logger.error(f"插入ETF {code} 日线数据失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")
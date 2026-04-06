import asyncio
import logging
import pandas as pd
import akshare as ak

from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)


@task(description="获取A股日线行情（不复权）")
class StockDailySpider(BaseSpider):
    resource = "ashare_sina"
    table_name = "kline_1d"

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        rename_map = {
            "return": "return_ratio",
            "turnover": "turnover_ratio",
            "outstanding_share": "circulating_cap"
        }
        df = df.rename(columns=rename_map)
        df["symbol"] = symbol
        df["market"] = market
        df["turnover_ratio"] = df["turnover_ratio"]*100
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
            if idx%10==0:
                logger.info(f"{self.__class__.__name__} [{idx}/{total}] 正在处理 {task['symbol']}")

            market = task['market']
            symbol = task['symbol']
            start_date = task['start_date']
            end_date = task['end_date']
            code = f"{market}{symbol}"

            try:
                df = await asyncio.to_thread(
                    proxy_pool,
                    ak.stock_zh_a_daily,
                    symbol=code,
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                    adjust=""
                )
            except Exception as e:
                logger.error(f"获取股票 {code} 日频数据失败: {e}")
                continue

            if df.empty:
                logger.warning(f"股票 {code} 日频数据为空")
                continue

            df = self._rename_columns(df, symbol, market)
            try:
                save_dataframe(
                    df,
                    table_name=self.table_name,
                    db=self.market,
                    primary_key=["symbol", "date"]
                )
                if idx % 10 == 0:
                    logger.info(f"股票 {code} 日线数据已保存，共 {len(df)} 条")
            except Exception as e:
                logger.error(f"插入股票 {code} 日线数据失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")
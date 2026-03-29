import asyncio
import logging
import pandas as pd
import akshare as ak

from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)


@task(description="获取A股前后复权因子")
class StockAdjustFactorSpider(BaseSpider):
    resource = "ashare_sina"
    table_name = "adjust_factor"

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        df["symbol"] = symbol
        df["market"] = market
        if "hfq_factor" in df.columns:
            df["hfq_factor"] = df["hfq_factor"].astype(float)
            df = df[["symbol", "date", "hfq_factor"]]
        else:
            df["qfq_factor"] = df["qfq_factor"].astype(float)
            df = df[["symbol", "date", "qfq_factor"]]
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

            # 并发获取前后复权因子
            async def fetch_hfq():
                return await asyncio.to_thread(
                    proxy_pool,
                    ak.stock_zh_a_daily,
                    symbol=code,
                    adjust="hfq-factor"
                )

            async def fetch_qfq():
                return await asyncio.to_thread(
                    proxy_pool,
                    ak.stock_zh_a_daily,
                    symbol=code,
                    adjust="qfq-factor"
                )

            hfq_result, qfq_result = await asyncio.gather(
                fetch_hfq(), fetch_qfq(), return_exceptions=True
            )

            # 检查异常
            if isinstance(hfq_result, Exception):
                logger.error(f"获取股票 {code} 后复权因子失败: {hfq_result}")
                continue
            if isinstance(qfq_result, Exception):
                logger.error(f"获取股票 {code} 前复权因子失败: {qfq_result}")
                continue

            hfq_df = hfq_result
            qfq_df = qfq_result

            # 重命名列
            hfq_df = self._rename_columns(hfq_df, symbol, market)
            qfq_df = self._rename_columns(qfq_df, symbol, market)

            # 合并前后复权因子
            adjust_df = pd.merge(hfq_df, qfq_df, on=["symbol", "date"])

            try:
                save_dataframe(
                    adjust_df,
                    table_name=self.table_name,
                    db=self.market,
                    primary_key=["symbol", "date"]
                )
                logger.info(f"股票 {code} 前后复权因子已保存，共 {len(adjust_df)} 条")
            except Exception as e:
                logger.error(f"插入股票 {code} 前后复权因子失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")
import asyncio
import logging
import pandas as pd
import akshare as ak

from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.config import MAX_CONCURRENCY
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)


@task(description="获取A股前后复权因子")
class StockAdjustFactorSpider(BaseSpider):
    resource = "ashare_sina"
    table = "adjust_factor"

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
        # 先执行父类检查（可能会处理 update 标志等基础逻辑）
        super().check()
        try:
            # 计算三个月前的时间点
            # 使用 pd.DateOffset 处理月份跨度，确保逻辑准确
            new_tasks = []
            for task in self.tasks:
                three_months_ago = pd.Timestamp.now().date() - pd.DateOffset(months=3)
                if task["start_date"]<=three_months_ago:
                    new_tasks.append(task)
            self.tasks = new_tasks
            logger.info(f"过滤掉最近3个月已更新的A股复权因子数据，剩余 {len(self.tasks)} 个任务")
        except Exception as e:
            logger.error(f"检查A股复权因子数据更新状态失败: {e}")
            
    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")
        async def process_one_task(task):
            market = task['market']
            symbol = task['symbol']
            code = f"{market}{symbol}"

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

            if isinstance(hfq_result, Exception):
                logger.error(f"获取股票 {code} 后复权因子失败: {hfq_result}")
                return None
            if isinstance(qfq_result, Exception):
                logger.error(f"获取股票 {code} 前复权因子失败: {qfq_result}")
                return None

            hfq_df = self._rename_columns(hfq_result, symbol, market)
            qfq_df = self._rename_columns(qfq_result, symbol, market)
            return pd.merge(hfq_df, qfq_df, on=["symbol", "date"])

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
                    logger.info(f"{self.__class__.__name__} [{min(i + batch_size, total)}/{total}] 批量保存复权因子，共 {len(batch_df)} 条")
                except Exception as e:
                    logger.error(f"批量插入股票前后复权因子失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")

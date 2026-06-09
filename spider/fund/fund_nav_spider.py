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


@task(description="获取基金净值数据（东方财富）")
class FundNavSpider(BaseSpider):
    resource = "fund_eastmoney"
    table = "fund_nav"

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        rename_map = {
            "净值日期": "date",
            "单位净值": "unit_net_value",
        }
        df = df.rename(columns=rename_map)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["unit_net_value"] = pd.to_numeric(df["unit_net_value"], errors="coerce")
        df["symbol"] = symbol
        df["market"] = market
        df = df[["date", "symbol", "market", "unit_net_value"]]
        df = df.dropna(subset=["date", "unit_net_value"])
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

        async def process_one_task(task):
            market = task["market"]
            symbol = task["symbol"]
            start_date = task["start_date"]
            end_date = task["end_date"]
            code = f"{market}{symbol}"
            try:
                df = await asyncio.to_thread(
                    proxy_pool,
                    ak.fund_etf_fund_info_em,
                    fund=symbol,
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                )
            except Exception as e:
                logger.error(f"获取基金 {code} 净值数据失败: {e}")
                return None

            if df.empty:
                logger.warning(f"基金 {code} 净值数据为空")
                return None

            return self._rename_columns(df, symbol, market)

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
                        primary_key=["symbol", "date"],
                    )
                    logger.info(f"{self.__class__.__name__} [{min(i + batch_size, total)}/{total}] 批量保存基金净值数据，共 {len(batch_df)} 条")
                except Exception as e:
                    logger.error(f"批量插入基金净值数据失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")

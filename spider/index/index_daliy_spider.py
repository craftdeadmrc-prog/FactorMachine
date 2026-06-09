import asyncio
import logging
import threading
from typing import Dict, List, Optional

import pandas as pd

from ..base_spider import BaseSpider
from core.config import MAX_CONCURRENCY, TDX_CLIENT
from core.scheduler import task
from core.storage import save_dataframe
from opentdx.const import MARKET, PERIOD

logger = logging.getLogger(__name__)


@task(description="获取指数日线行情（TDX）")
class IndexDailySpider(BaseSpider):
    resource = "index_tdx"
    table = "kline_1d"

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        df = df.rename(
            columns={
                "datetime": "date",
                "vol": "volume",
            }
        )
        df = df.drop(columns=["float_shares", "turnover"], errors="ignore")

        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["symbol"] = symbol
        df["market"] = market
        df["volume"] = df["volume"]*100
        base_cols = ["symbol", "date", "open", "high", "low", "close", "volume", "amount", "market"]
        extra_cols = [col for col in df.columns if col not in base_cols]
        df = df[base_cols + extra_cols]
        df = df.dropna(subset=["date", "close"]).sort_values(["symbol", "date"]).reset_index(drop=True)
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
            code = f"{market}{symbol}"

            try:
                raw = TDX_CLIENT.q_client().get_symbol_bars(MARKET.SH if market == "sh" else MARKET.SZ, symbol, PERIOD.DAILY, count=41200)
            except Exception as e:
                logger.error(f"获取指数 {code} 日频数据失败: {e}")
                return None

            raw = pd.DataFrame(raw)
            if raw.empty:
                logger.warning(f"指数 {code} 返回空数据")
                return None

            return self._rename_columns(raw, symbol, market)

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
                    logger.info(
                        f"{self.__class__.__name__} [{min(i + batch_size, total)}/{total}] "
                        f"批量保存指数日线数据，共 {len(batch_df)} 条"
                    )
                except Exception as e:
                    logger.error(f"批量插入指数日线数据失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")

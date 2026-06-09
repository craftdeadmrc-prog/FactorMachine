import asyncio
import logging
from typing import Dict, List

import akshare as ak
import pandas as pd

from ..base_spider import BaseSpider
from core.config import MAX_CONCURRENCY
from core.proxy import proxy_pool
from core.scheduler import task
from core.storage import load_dataframe, save_dataframe

logger = logging.getLogger(__name__)


@task(description="获取基金份额数据（上交所/深交所）")
class FundSharesSpider(BaseSpider):
    resource = "fund_szse"
    table = "fund_shares"

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _rename_columns(self, df: pd.DataFrame, market: str) -> pd.DataFrame:
        rename_map = {
            "统计日期": "date",
            "日期": "date",
            "基金代码": "symbol",
            "基金份额": "shares",
        }
        df = df.rename(columns=rename_map)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["shares"] = pd.to_numeric(df["shares"], errors="coerce")
        df["market"] = market
        df = df[["date", "symbol", "shares", "market"]]
        return df.sort_values(["symbol", "date"]).reset_index(drop=True)

    def check(self):
        super().check()
        min_allow_date = pd.Timestamp.now().date() - pd.DateOffset(months=6)
        for t in self.tasks:
            if t["market"] == "sz" and pd.Timestamp(t["start_date"]) < min_allow_date:
                t["start_date"] = min_allow_date
            if pd.Timestamp(t["start_date"]) < pd.Timestamp(year=2012,month=1,day=4):
                t["start_date"] = pd.Timestamp(year=2012,month=1,day=4)

    def _filter_by_tasks(self, df: pd.DataFrame, task_map: Dict[str, Dict]) -> pd.DataFrame:
        if df.empty:
            return df

        df = df[df["symbol"].isin(task_map.keys())].copy()
        if df.empty:
            return df

        ranges = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "start_date": pd.Timestamp(task["start_date"]),
                    "end_date": pd.Timestamp(task["end_date"]),
                }
                for symbol, task in task_map.items()
            ]
        )
        df = df.merge(ranges, on="symbol", how="inner")
        df = df[(df["date"] >= df["start_date"]) & (df["date"] <= df["end_date"])]
        df = df.drop(columns=["start_date", "end_date"])
        return df.sort_values(["symbol", "date"]).reset_index(drop=True)

    async def _fetch_sse_date(self, date: pd.Timestamp, task_map: Dict[str, Dict]) -> pd.DataFrame:
        date_str = date.strftime("%Y%m%d")
        try:
            raw = await asyncio.to_thread(proxy_pool, ak.fund_etf_scale_sse, date=date_str)
        except Exception as e:
            logger.error(f"获取上交所 ETF 基金份额 {date_str} 失败: {e}")
            return pd.DataFrame()

        if raw is None or raw.empty:
            return pd.DataFrame()

        df = self._rename_columns(raw, "sh")
        return self._filter_by_tasks(df, task_map)

    async def _fetch_szse_symbol(self, symbol: str, start_date: pd.Timestamp, end_date: pd.Timestamp, task_map: Dict[str, Dict]) -> pd.DataFrame:
        try:
            raw = await asyncio.to_thread(
                proxy_pool,
                ak.fund_scale_daily_szse,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                symbol=symbol,
            )
        except Exception as e:
            logger.error(f"获取深交所 {symbol} 基金份额 {start_date.date()}-{end_date.date()} 失败: {e}")
            return pd.DataFrame()

        if raw is None or raw.empty:
            return pd.DataFrame()

        df = self._rename_columns(raw, "sz")
        return self._filter_by_tasks(df, task_map)

    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        sh_tasks = {task["symbol"]: task for task in self.tasks if task["market"] == "sh"}
        sz_tasks = {task["symbol"]: task for task in self.tasks if task["market"] == "sz"}
        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")

        if sh_tasks:
            start_date = min(pd.Timestamp(task["start_date"]) for task in sh_tasks.values())
            end_date = max(pd.Timestamp(task["end_date"]) for task in sh_tasks.values())
            calendar_sql = f"getMarketCalendar('XSHG',{start_date.strftime("%Y.%m.%d")}, {end_date.strftime("%Y.%m.%d")})"
            calendar_raw = await asyncio.to_thread(load_dataframe, calendar_sql, self.market)
            dates = sorted(pd.to_datetime(pd.Index(calendar_raw)))

            batch_size = MAX_CONCURRENCY
            for i in range(0, len(dates), batch_size):
                batch_dates = dates[i:i + batch_size]
                tasks = [asyncio.create_task(self._fetch_sse_date(date, sh_tasks)) for date in batch_dates]
                results = await asyncio.gather(*tasks)
                valid_dfs = [df for df in results if df is not None and not df.empty]
                if valid_dfs:
                    batch_df = pd.concat(valid_dfs, ignore_index=True)
                    save_dataframe(
                        batch_df,
                        table=self.table,
                        db=self.market,
                        primary_key=["symbol", "date"],
                    )
                logger.info(f"{self.__class__.__name__}: 上交所 [{min(i + batch_size, len(dates))}/{len(dates)}] 日期批次完成")

        if sz_tasks:
            start_date = min(pd.Timestamp(task["start_date"]) for task in sz_tasks.values())
            end_date = max(pd.Timestamp(task["end_date"]) for task in sz_tasks.values())
            tasks = [
                asyncio.create_task(self._fetch_szse_symbol(symbol, start_date, end_date, sz_tasks))
                for symbol in ["ETF", "LOF"]
            ]
            results = await asyncio.gather(*tasks)
            valid_dfs = [df for df in results if df is not None and not df.empty]
            if valid_dfs:
                batch_df = pd.concat(valid_dfs, ignore_index=True)
                batch_df = batch_df.drop_duplicates(subset=["symbol", "date"], keep="last")
                save_dataframe(
                    batch_df,
                    table=self.table,
                    db=self.market,
                    primary_key=["symbol", "date"],
                )
            logger.info(f"{self.__class__.__name__}: 深交所基金份额批次完成")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")

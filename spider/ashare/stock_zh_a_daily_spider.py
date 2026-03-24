import asyncio
import logging
import pandas as pd
import akshare as ak
from datetime import date, datetime
from typing import List, Dict

from ..base_spider import BaseSpider
from core.storage import save_dataframe, load_dataframe
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)

@task(description="获取A股日线行情及复权因子")
class StockDailySpider(BaseSpider):
    resource = "ashare_sina"
    table_name = "kline_daily"
    factor_table_name = "adjust_factor"

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        rename_map = {
            "return": "return_ratio",
            "turnover": "turnover_ratio",
            "outstanding_share": "circulating_cap"
        }
        df = df.rename(columns=rename_map)
        df["symbol"] = symbol
        df["market"] = market
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df

    def _rename_factor_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
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
        # 1. 备份原始任务列表（父类 check 会修改 self.tasks）
        original_tasks = self.tasks.copy() if self.tasks else []

        # 2. 调用父类 check，过滤掉普通数据已完整的任务
        super().check()

        # 3. 遍历原始任务，找出普通数据完整但因子缺失的任务
        factor_missing_tasks = []

        for task in original_tasks:
            symbol = task['symbol']
            # 普通数据完整，检查因子表是否存在至少一条同时包含 hfq_factor 和 qfq_factor 且均非空的记录
            sql = f"""
                SELECT 1
                FROM {self.factor_table_name}
                WHERE symbol = '{symbol}'
                  AND hfq_factor IS NOT NULL
                  AND qfq_factor IS NOT NULL
                LIMIT 1
            """
            try:
                df = load_dataframe(sql, db=self.market)
                if df.empty:
                    factor_missing_tasks.append(task)
                    logger.info(f"Factor data missing for {symbol}, will fetch")
            except Exception as e:
                logger.error(f"Failed to check factor completeness for {symbol}: {e}")
                # 出错时视为因子缺失，保留任务
                factor_missing_tasks.append(task)

        # 4. 将因子缺失的任务合并到当前任务列表
        self.tasks.extend(factor_missing_tasks)
        logger.info(f"After factor check, {len(self.tasks)} tasks remain for {self.market}")

    async def run(self, progress=None, task_id=None):
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        total = len(self.tasks)
        if progress and task_id is not None:
            progress.update(task_id, total=total)

        for idx, task in enumerate(self.tasks, 1):
            if progress and task_id is not None:
                progress.update(
                    task_id,
                    completed=idx,
                    description=f"{self.__class__.__name__} [{idx}/{total}]"
                )

            market = task['market']
            symbol = task['symbol']
            start_date = task['start_date']
            end_date = task['end_date']

            start_str = start_date.strftime("%Y%m%d") if isinstance(start_date, (date, datetime)) else start_date
            end_str = end_date.strftime("%Y%m%d") if isinstance(end_date, (date, datetime)) else end_date
            code = f"{market}{symbol}"

            # 日线行情（不复权）
            try:
                df = await asyncio.to_thread(
                    proxy_pool,
                    ak.stock_zh_a_daily,
                    symbol=code,
                    start_date=start_str,
                    end_date=end_str,
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
                logger.info(f"股票 {code} 日线数据已保存，共 {len(df)} 条")
            except Exception as e:
                logger.error(f"插入股票 {code} 日线数据失败: {e}")

            # 后复权因子
            try:
                hfq_df = await asyncio.to_thread(
                    proxy_pool,
                    ak.stock_zh_a_daily,
                    symbol=code,
                    adjust="hfq-factor"
                )
            except Exception as e:
                logger.error(f"获取股票 {code} 后复权因子失败: {e}")
                continue

            hfq_df = self._rename_factor_columns(hfq_df, symbol, market)

            # 前复权因子
            try:
                qfq_df = await asyncio.to_thread(
                    proxy_pool,
                    ak.stock_zh_a_daily,
                    symbol=code,
                    adjust="qfq-factor"
                )
            except Exception as e:
                logger.error(f"获取股票 {code} 前复权因子失败: {e}")
                continue

            qfq_df = self._rename_factor_columns(qfq_df, symbol, market)

            # 合并前后复权因子
            adjust_df = pd.merge(hfq_df, qfq_df, on=["symbol", "date"])

            try:
                save_dataframe(
                    adjust_df,
                    table_name=self.factor_table_name,
                    db=self.market,
                    primary_key=["symbol", "date"]
                )
                logger.info(f"股票 {code} 前后复权因子已保存，共 {len(adjust_df)} 条")
            except Exception as e:
                logger.error(f"插入股票 {code} 前后复权因子失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")
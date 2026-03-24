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

logger = logging.getLogger(__name__)

@task(description="获取A股估值数据（PE、PB、市值等）")
class StockValueEmSpider(BaseSpider):
    resource = "ashare_eastmoney"
    table_name = "valuation"          # 估值表名（市场通过文件区分）

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        rename_map = {
            "数据日期": "date",
            "当日涨跌幅": "change_ratio",
            "总市值": "market_cap",
            "流通市值": "tradable_market_value",
            "总股本": "capitalization",
            "PE(TTM)": "pe_ratio",
            "PE(静)": "pe_ratio_lyr",
            "市净率": "pb_ratio",
            "PEG值": "peg",
            "市现率": "pcf_ratio",
            "市销率": "ps_ratio",
        }
        df = df.rename(columns=rename_map)
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

        for idx, task in enumerate(self.tasks, 1):
            logger.info(f"{self.__class__.__name__} [{idx}/{total}] 正在处理 {task['symbol']}")

            market = task['market']
            symbol = task['symbol']

            # 添加随机延时，避免请求过快
            await asyncio.sleep(random.randint(0, 1))

            try:
                # 使用代理池包装 akshare 接口
                df = await asyncio.to_thread(
                    proxy_pool,
                    ak.stock_value_em,
                    symbol=symbol
                )
            except Exception as e:
                logger.error(f"获取股票 {symbol} 估值数据失败: {e}")
                continue

            if df.empty:
                logger.warning(f"股票 {symbol} 返回空数据")
                continue

            # 丢弃不需要的列
            df = df.drop(columns=['当日收盘价', '流通股本'], errors='ignore')
            df = self._rename_columns(df, symbol, market)

            try:
                save_dataframe(
                    df,
                    table_name=self.table_name,
                    db=self.market,
                    primary_key=["symbol", "date"]
                )
                logger.info(f"股票 {symbol} 估值数据已保存，共 {len(df)} 条")
            except Exception as e:
                logger.error(f"插入股票 {symbol} 估值数据失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")
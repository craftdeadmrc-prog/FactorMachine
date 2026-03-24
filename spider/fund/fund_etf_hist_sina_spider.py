import asyncio
import logging
import pandas as pd
import akshare as ak
from typing import List, Dict
from datetime import date, datetime

from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)

@task(description="获取ETF日线行情数据（新浪）")
class EtfDailySinaSpider(BaseSpider):
    """
    ETF日行情爬虫

    目标：写入表 kline_daily (市场: fund)
    数据源：新浪-ETF历史行情 (ak.fund_etf_hist_sina)
    """

    resource = "fund_sina"
    table_name = "kline_daily"
    factor_table_name = None          # ETF 无复权因子表

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        """
        统一字段：
        - 删除 prevclose 列（如果存在）
        - 日期转换为 datetime 类型
        - 增加 symbol 和 market 字段
        """
        if "prevclose" in df.columns:
            df.drop(columns=["prevclose"], inplace=True)
        df["date"] = pd.to_datetime(df["date"])
        df["symbol"] = symbol
        df["market"] = market
        # 按 symbol, date 排序保证顺序
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df

    def check(self):
        # 直接调用父类 check（基类会处理数据完整性的检查）
        super().check()

    async def run(self, progress=None, task_id=None):
        """
        遍历 tasks，抓取 ETF 日线数据。
        task 结构示例：{'market': 'sh', 'symbol': '510050', 'start_date': None, 'end_date': None}
        """
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
            # 接口不支持日期参数，忽略 start_date / end_date
            code = f"{market}{symbol}"

            # 使用代理池获取数据
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

            # 重命名列并添加标识字段
            df = self._rename_columns(df, symbol, market)

            # 插入日线数据
            try:
                save_dataframe(
                    df,
                    table_name=self.table_name,
                    db=self.market,          # 基类传入的市场（如 fund）
                    primary_key=["symbol", "date"]
                )
                logger.info(f"ETF {code} 日线数据已保存，共 {len(df)} 条")
            except Exception as e:
                logger.error(f"插入ETF {code} 日线数据失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")
# spider/fund/fund_etf_daily_em_spider.py
import asyncio
import random
import warnings

import akshare as ak
import pandas as pd

from ..base_spider import BaseSpider

class EtfDailyEmSpider(BaseSpider):
    """
    ETF日行情爬虫

    目标：写入表 fund_etf_hist
    数据源：新浪-ETF历史行情 (ak.fund_etf_hist_sina)
    """

    resource = "sina"
    table_name = "fund_etf_hist"

    def _rename_columns(self, df: pd.DataFrame, code: str, market: str) -> pd.DataFrame:
        """
        统一字段命名和格式，便于后续与其它表合并：
        - date 保持为 date
        - 增加 code, market 字段
        """
        df["date"] = pd.to_datetime(df["date"])

        # 增加代码与市场信息
        df["code"] = code
        df["market"] = market
        df = df.sort_values(["code", "date"]).reset_index(drop=True)
        return df

    # -------------------
    # 主运行逻辑
    # -------------------
    async def run(self, start_date: str = None, end_date: str = None, 
                 progress=None, task_id=None) -> pd.DataFrame:
        """
        扫描全市场ETF日行情数据并返回合并后的DataFrame

        参数:
            start_date, end_date: 字符串日期，可包含非数字字符，内部统一归一到 YYYYMMDD；
                                  仅在本地过滤使用，ak.fund_etf_hist_em 本身带日期参数。

        注意：
        - 表名由 table_name 决定，由调度器负责调用 save_dataframe。
        """

        # 获取ETF代码列表
        etf_codes = self.get_one_market("fund")
        all_dfs = []
        total = len(etf_codes)

        if progress and task_id is not None:
            progress.update(task_id, total=total)

        # 遍历全市场ETF
        for i, (market, code) in enumerate(etf_codes, 1):
            # 随机等待控制请求频率
            if progress and task_id is not None:
                progress.update(task_id, completed=i, description=f"{self.__class__.__name__} [{i}/{total}]")
            
            df = ak.fund_etf_hist_sina(symbol=market+code)
            df = self._rename_columns(df, code, market)

            all_dfs.append(df)

        return pd.concat(all_dfs, ignore_index=True)
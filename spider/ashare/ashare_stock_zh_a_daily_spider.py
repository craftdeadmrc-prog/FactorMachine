# spider/ashare/ashare_stock_zh_a_daily_spider.py
import asyncio
import pandas as pd
import akshare as ak
import random
import warnings
from ..base_spider import BaseSpider

class StockDailySpider(BaseSpider):
    """
    A股日线行情爬虫

    目标：写入表 ashare_stock_zh_a_daily
    数据源：新浪 (akshare.stock_zh_a_daily)
    """

    resource = "sina"
    table_name = "ashare_stock_zh_a_daily"


    def _rename_columns(self, df: pd.DataFrame, code: str, market: str) -> pd.DataFrame:
        """
        统一字段：
        - 增加 code, market 字段用于后续多表合并
        """
        # 重命名列
        rename_map = {
            "return": "return_ratio",
            "turnover": "turnover_ratio",
        }
        df = df.rename(columns=rename_map)
        df["date"] = pd.to_datetime(df["date"])
        df["code"] = code
        df["market"] = market

        df = df.sort_values(["code", "date"]).reset_index(drop=True)
        return df

    async def run(self, start_date: str = None, end_date: str = None,progress=None, task_id=None) -> pd.DataFrame:
        """
        扫描全市场 A 股日线行情并返回合并后的 DataFrame

        参数:
            start_date, end_date: 字符串日期，可包含非数字字符，内部统一归一到 YYYYMMDD；

        注意：
        - 若任一日期缺失或无法解析，则返回空表；
        - 表名由 table_name 决定，由调度器负责调用 save_dataframe。
        """
        codes = self.get_one_market("ashare")

        all_dfs = []
        total = len(codes)

        # 如果有进度条对象，更新总任务数
        if progress and task_id is not None:
            progress.update(task_id, total=total)
        
        for i, (market, code) in enumerate(codes, 1):
            # 更新进度条
            if progress and task_id is not None:
                progress.update(task_id, completed=i, description=f"{self.__class__.__name__} [{i}/{total}]")
            
            try:
                # 新浪接口 stock_zh_a_daily 需要带市场前缀，如 "sh600000" / "sz000001"
                symbol = f"{market}{code}"
                df = ak.stock_zh_a_daily(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    adjust="hfq",
                )
                if df is None or df.empty:
                    continue
                df = self._rename_columns(df, code, market)
                all_dfs.append(df)
                await asyncio.sleep(random.randint(0, 1))
            except Exception as error:
                warnings.warn(
                    f"{self.__class__.__name__}: 获取股票 {symbol} 日频数据失败: {error}"
                )

        return pd.concat(all_dfs, ignore_index=True)
# spider/ashare/ashare_stock_value_em_spider.py
import asyncio
import random
import warnings

import akshare as ak
import pandas as pd

from ..base_spider import BaseSpider

class StockValueEmSpider(BaseSpider):
    resource = "eastmoney"
    table_name = "ashare_stock_value"

    def _rename_columns(self, df: pd.DataFrame, code: str, market: str) -> pd.DataFrame:
        rename_map = {
            "数据日期": "date",
            "当日涨跌幅": "change_ratio",
            "总市值": "total_market_value",
            "流通市值": "tradable_market_value",
            "总股本": "total_shares",
            "PE(TTM)": "price_to_earnings_ttm",
            "PE(静)": "price_to_earnings_static",
            "市净率": "price_to_book_ratio",
            "PEG值": "price_to_earnings_growth_ratio",
            "市现率": "price_to_cash_ratio",
            "市销率": "price_to_sales_ratio",
        }
        df = df.rename(columns=rename_map)
        df["date"] = pd.to_datetime(df["date"])
        df["code"] = code
        df["market"] = market
        df = df.sort_values(["code", "date"]).reset_index(drop=True)
        return df

    async def run(self, start_date: str = None, end_date: str = None, 
                 progress=None, task_id=None) -> pd.DataFrame:
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
            
            await asyncio.sleep(random.randint(1, 3))
            try:
                df = ak.stock_value_em(symbol=code)
            except Exception as error:
                warnings.warn(
                    f"{self.__class__.__name__}: 获取股票 {code} 估值数据失败: {error}"
                )
            
            df = df.drop(columns=['当日收盘价', '流通股本'])
            df = self._rename_columns(df, code, market)
            all_dfs.append(df)

        return pd.concat(all_dfs, ignore_index=True)
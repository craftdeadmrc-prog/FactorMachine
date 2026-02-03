# spider/fund/fund_portfolio_hold_em_spider.py
import asyncio
import random
import warnings
import re

import akshare as ak
import pandas as pd

from ..base_spider import BaseSpider
from tqdm import tqdm


class FundPortfolioHoldEmSpider(BaseSpider):
    """
    ETF 基金持仓爬虫（仅限 ETF）

    目标：写入表 fund_portfolio_hold
    数据源：天天基金网-基金档案-投资组合 (ak.fund_portfolio_hold_em)
    """
    resource = "eastmoney"
    table_name = "fund_portfolio_hold"

    # -------------------
    # 基础工具方法
    # -------------------

    def _normalize_quarter(self, s: str = None) -> str:
        """
        将季度字符串标准化为 YYYYQX 格式
        例如："2024年1季度股票投资明细" -> "2024Q1"
        """
        if not s:
            return None
        match = re.search(r"(\d{4})年(\d+)季度", str(s))
        if match:
            year = match.group(1)
            quarter = match.group(2)
            return f"{year}Q{quarter}"
        return s
    def _rename_columns(self, df: pd.DataFrame, fund_code: str) -> pd.DataFrame:
        """
        统一字段命名和格式：
        - code: 基金代码
        - quarter: 标准化季度
        - stock_id: 股票代码
        - stock_name: 股票名称
        - holding_ratio: 占净值比例（%）
        - holding_number: 持股数（万股）
        - holding_value: 持仓市值（万元）
        - 序号列直接丢弃
        """
        df = df.drop(columns=["序号"])

        rename_map = {
            "股票代码": "stock_id",
            "股票名称": "stock_name",
            "占净值比例": "holding_ratio",
            "持股数": "holding_number",
            "持仓市值": "holding_value",
            "季度": "quarter",
        }
        df = df.rename(columns=rename_map)
        df["date"] = pd.to_datetime(df["date"])

        if "quarter" in df.columns:
            df["quarter"] = df["quarter"].apply(self._normalize_quarter)

        df["code"] = fund_code

        for col in ["holding_ratio", "holding_number", "holding_value"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.sort_values(["code", "date", "holding_ratio"]).reset_index(drop=True)
        return df

    # -------------------
    # 主运行逻辑
    # -------------------
    async def run(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        扫描全市场 ETF 基金持仓数据并返回合并后的 DataFrame

        参数:
            start_date, end_date: 字符串日期，如 "2020" 或 "2020-01"；
                                  用于限定年份区间（只用前 4 位年份）

        注意：
        - ak.fund_portfolio_hold_em 接口参数 date 是年份（如 "2024"）
        - 日期范围在本地通过 quarter 的年份做过滤
        """

        etf_codes = self.get_one_market("fund")
        all_dfs = []
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])
        for market,etf_code in tqdm(etf_codes, desc="Fetching ETF portfolio data"):
            await asyncio.sleep(random.randint(1, 3))
            for year in range(start_year, end_year):
                try:
                    df = ak.fund_portfolio_hold_em(symbol=etf_code, date=str(year))
                except Exception as error:
                    warnings.warn(
                        f"{self.__class__.__name__}: 获取 ETF {etf_code} {year} 年持仓失败: {error}"
                    )
                    await asyncio.sleep(3)
                    try:
                        df = ak.fund_portfolio_hold_em(symbol=etf_code, date=str(year))
                    except Exception as second_error:
                        warnings.warn(
                            f"{self.__class__.__name__}: ETF {etf_code} 第二次尝试仍失败: {second_error}"
                        )

                df = self._rename_columns(df, etf_code)
                all_dfs.append(df)

        return pd.concat(all_dfs, ignore_index=True)
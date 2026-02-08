# spider/ashare/ashare_stock_zh_a_daily_spider.py
import asyncio
import pandas as pd
import akshare as ak
import random
import warnings
from ..base_spider import BaseSpider

# 新增：用于因子文件保存
from core.storage import save_dataframe


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

        # 新增：用于收集所有股票的后复权因子
        hfq_factor_list = []

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
                    adjust="",
                )
                df = self._rename_columns(df, code, market)
                all_dfs.append(df)
                await asyncio.sleep(random.randint(0, 1))

                # ================= 新增：获取并收集后复权因子 =================
                try:
                    hfq_df = ak.stock_zh_a_daily(symbol=symbol, adjust="hfq-factor")
                    hfq_df["date"] = pd.to_datetime(hfq_df["date"])
                    hfq_df["code"] = code
                    hfq_df = hfq_df[["code","date", "hfq_factor"]]
                    hfq_df = hfq_df.sort_values(["code","date"]).reset_index(drop=True)
                    hfq_factor_list.append(hfq_df)
                except Exception as e:
                    warnings.warn(
                        f"{self.__class__.__name__}: 获取股票 {symbol} 后复权因子失败: {e}"
                    )
                # ================= 新增结束 =================

            except Exception as error:
                warnings.warn(
                    f"{self.__class__.__name__}: 获取股票 {symbol} 日频数据失败: {error}"
                )

        # ================= 新增：以“因子格式”独立保存 hfq_factor =================
        if hfq_factor_list:
            all_hfq = pd.concat(hfq_factor_list, ignore_index=True)
            # 因子文件命名规则：{market_type}_{factor_name}，目录为 factor_results
            # 这里 market_type = "ashare"，factor_name = "hfq_factor"
            save_dataframe(all_hfq, "ashare_hfq_factor", path="factor_results")
            print(f"[StockDailySpider] 后复权因子保存完成，共 {len(all_hfq)} 行")
        # ================= 新增结束 =================

        return pd.concat(all_dfs, ignore_index=True)
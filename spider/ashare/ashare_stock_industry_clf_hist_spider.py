# spider/ashare/ashare_stock_industry_clf_hist_spider.py
import asyncio
import pandas as pd
import akshare as ak

from ..base_spider import BaseSpider

class SwIndustryClfHistSpider(BaseSpider):
    """
    申万个股行业分类变动历史爬虫

    目标：写入表 ashare_stock_industry_clf_hist
    数据源：申万宏源研究-行业分类 (ak.stock_industry_clf_hist_sw)
    """

    resource = "swhy"
    table_name = "ashare_stock_industry_clf_hist"

    def _rename_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        统一字段命名和格式，便于后续与其它表合并:
        - symbol -> code
        - start_date: 计入日期，转为 YYYYMMDD
        - 增加 market 字段 (sh/sz)，方便与 A 股日线等表对齐
        """

        # 重命名列
        rename_map = {
            "symbol": "code",
        }
        df = df.rename(columns=rename_map)
        # 根据代码首位简单区分市场
        df["market"] = df["code"].apply(
            lambda x: "sh" if isinstance(x, str) and x.startswith("6") else "sz"
        )
        df['start_date'] = pd.to_datetime(df["start_date"])
        df = df.sort_values(["code", "start_date"]).reset_index(drop=True)
        return df

    async def run(self, start_date: str = None, end_date: str = None, 
                 progress=None, task_id=None) -> pd.DataFrame:
        """
        获取所有个股的申万行业分类变动历史数据。

        说明:
        - 该接口本身不支持按日期过滤，start_date / end_date 仅为兼容调度器的统一签名；
        - 每次调用均返回全量历史数据。
        """
        if progress and task_id is not None:
            progress.update(task_id, total=1)

        df = ak.stock_industry_clf_hist_sw()
        
        df = df.drop(columns="update_time")
        df = self._rename_columns(df)
        if progress and task_id is not None:
            progress.update(task_id, completed=1, description=f"{self.__class__.__name__} [{1}/{1}]")
            
        return df
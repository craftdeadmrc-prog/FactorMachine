"""
WIP,部分指标在jq里定义为因子,需要先完善因子表设计
"""
import asyncio
import random
import logging
import akshare as ak
import pandas as pd
from typing import List, Dict

from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.scheduler import task

logger = logging.getLogger(__name__)

@task(description="获取A股财务摘要数据（常用指标、盈利能力、成长能力等）")
class StockFinancialAbstractSpider(BaseSpider):
    resource = "ashare_sina"

    # 报表类型中文名 -> 表名映射
    symbol_map = {
        "利润表": "income",
        "指标表": "indicator"
    }

    # 列映射：根据指标中文名映射到英文列名，并区分所属表
    _COLUMN_MAP = {
        "利润表": {
            "营业总收入": "total_operating_revenue",
            "归母净利润": "np_parent_company_owners",
            "营业收入": "operating_revenue",
            "营业成本": "operating_cost",
            "净利润": "net_profit",
            "归属于母公司股东的净利润": "np_parent_company_owners",
            "基本每股收益": "basic_eps",
            "稀释每股收益": "diluted_eps",
        },
        "指标表": {
            "摊薄每股收益_最新股数": "eps",
            "扣非净利润": "adjusted_profit",
            "扣除非经常损益后的净利润": "adjusted_profit",
            "净资产收益率(ROE)": "roe",
            "净资产收益率(扣除非经常损益)": "inc_return",
            "总资产净利率(ROA)": "roa",
            "销售净利率": "net_profit_margin",
            "销售毛利率": "gross_profit_margin",
            "营业总成本/营业总收入": "expense_to_total_revenue",
            "营业利润/营业总收入": "operation_profit_to_total_revenue",
            "净利润/营业总收入": "net_profit_to_total_revenue",
            "营业费用/营业总收入": "operating_expense_to_total_revenue",
            "管理费用/营业总收入": "ga_expense_to_total_revenue",
            "财务费用/营业总收入": "financing_expense_to_total_revenue",
            "经营活动净收益/利润总额": "operating_profit_to_profit",
            "价值变动净收益/利润总额": "invesment_profit_to_profit",
            "扣除非经常损益后的净利润/归属于母公司所有者的净利润": "adjusted_profit_to_profit",
            "销售商品提供劳务收到的现金/营业收入": "goods_sale_and_service_to_revenue",
            "经营活动产生的现金流量净额/营业收入": "ocf_to_revenue",
            "经营活动产生的现金流量净额/经营活动净收益": "ocf_to_operating_profit",
            "营业总收入同比增长率": "inc_total_revenue_year_on_year",
            "营业总收入环比增长率": "inc_total_revenue_annual",
            "营业收入同比增长率": "inc_revenue_year_on_year",
            "营业收入环比增长率": "inc_revenue_annual",
            "营业利润同比增长率": "inc_operation_profit_year_on_year",
            "营业利润环比增长率": "inc_operation_profit_annual",
            "净利润同比增长率": "inc_net_profit_year_on_year",
            "净利润环比增长率": "inc_net_profit_annual",
            "归属母公司股东的净利润同比增长率": "inc_net_profit_to_shareholders_year_on_year",
            "归属母公司股东的净利润环比增长率": "inc_net_profit_to_shareholders_annual",
        }
    }

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _rename_columns(
        self,
        df: pd.DataFrame,
        symbol: str,
        market: str,
        report_type_cn: str,
    ) -> pd.DataFrame:
        """
        清洗单张报表数据（本爬虫中未直接使用，保留模板接口）
        """
        rename_map = self._COLUMN_MAP[report_type_cn]
        # 只保留映射中实际存在的原始列
        keep_src_cols = [c for c in rename_map.keys() if c in df.columns]
        df = df[keep_src_cols].rename(columns=rename_map)
        df["date"] = pd.to_datetime(df["date"])
        df["symbol"] = symbol
        df["market"] = market
        target_cols = set(rename_map.values())
        for col in target_cols:
            if col not in df.columns:
                df[col] = pd.NA
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df

    def check(self):
        # super().check()
        pass

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
            stock = f"{market}{symbol}"

            try:
                # 获取财务摘要数据
                df_raw = ak.stock_financial_abstract(symbol=stock)
            except Exception as error:
                logger.error(f"获取股票 {symbol} 财务摘要数据失败: {error}")
                continue

            if df_raw.empty:
                logger.warning(f"股票 {symbol} 财务摘要返回空数据")
                continue

            # ---- 数据清洗与转换 ----
            # 1. 识别日期列（除"选项"和"指标"以外的列）
            date_cols = [col for col in df_raw.columns if col not in ["选项", "指标"]]
            # 2. 将宽表转换为长表（melt）
            df_melted = df_raw.melt(id_vars=["选项", "指标"], value_vars=date_cols,
                                    var_name="date_str", value_name="value")
            # 3. 日期列转换为datetime，并过滤掉无效日期
            df_melted["date"] = pd.to_datetime(df_melted["date_str"], format="%Y%m%d", errors="coerce")
            df_melted = df_melted.dropna(subset=["date"]).drop(columns=["date_str"])
            # 4. 为每个指标查找映射和归属表
            df_melted["eng_name"] = None
            df_melted["table_cn"] = None
            for table_cn, col_map in self._COLUMN_MAP.items():
                for cn_name, eng_name in col_map.items():
                    mask = df_melted["指标"] == cn_name
                    df_melted.loc[mask, "eng_name"] = eng_name
                    df_melted.loc[mask, "table_cn"] = table_cn

            # 过滤掉未映射的指标
            df_melted = df_melted.dropna(subset=["eng_name"])

            if df_melted.empty:
                logger.warning(f"股票 {symbol} 没有可映射的指标，跳过")
                continue

            # 5. 按表分类进行透视
            for table_cn in self._COLUMN_MAP.keys():
                df_table = df_melted[df_melted["table_cn"] == table_cn].copy()
                if df_table.empty:
                    continue

                # 透视：行索引为日期，列名为eng_name，值为value
                df_pivot = df_table.pivot_table(index="date", columns="eng_name", values="value", aggfunc="first")
                df_pivot = df_pivot.reset_index()

                # 添加标识字段
                df_pivot["symbol"] = symbol
                df_pivot["market"] = market

                # 排序
                df_pivot = df_pivot.sort_values(["symbol", "date"]).reset_index(drop=True)

                # 获取表名
                table_name = self.symbol_map[table_cn]

                # 插入数据库
                try:
                    save_dataframe(
                        df_pivot,
                        table_name=table_name,
                        db=self.market,
                        primary_key=["symbol", "date"]
                    )
                    logger.info(f"股票 {symbol} {table_cn} 数据已保存，共 {len(df_pivot)} 条")
                except Exception as e:
                    logger.error(f"插入股票 {symbol} {table_cn} 数据失败: {e}")


        logger.info(f"{self.__class__.__name__}: 财务摘要抓取完成，已处理 {total} 个任务")
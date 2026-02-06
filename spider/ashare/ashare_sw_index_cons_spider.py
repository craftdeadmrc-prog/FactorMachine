#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
申万三级行业成份爬虫

目标：写入表 ashare_sw_index_third_cons
数据源：乐咕乐股-申万三级-行业成份 (ak.sw_index_third_cons)
"""

import asyncio
import pandas as pd
import akshare as ak

from ..base_spider import BaseSpider
import random

class SwIndexConsSpider(BaseSpider):
    """
    申万三级行业成份爬虫
    """

    # 数据源标识：与申万行业相关，保持与 SwIndustryClfHistSpider 一致
    resource = "swhy"
    # 表名：遵循 ashare_ 前缀命名规则
    table_name = "ashare_sw_index_cons"

    def _rename_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        统一字段命名和格式，便于后续与其它表合并或使用:

        原始列 -> 统一英文列
        - 股票简称 -> short_name
        - 股息率 -> dividend_yield_ratio

        此处只保留当前需求列，其它无用列直接丢弃。
        """
        rename_map = {
            "股票简称": "short_name",
            "股息率": "dividend_yield_ratio",
        }
        # 丢弃不需要的列，保持精简
        df = df.drop(
            columns=[
                "股票代码",
                "申万1级",
                "申万2级",
                "申万3级",
                "序号",
                "纳入时间",
                "价格",
                "市盈率",
                "市盈率ttm",
                "市净率",
                "市值",
                "归母净利润同比增长(09-30)",
                "归母净利润同比增长(06-30)",
                "营业收入同比增长(09-30)",
                "营业收入同比增长(06-30)",
            ]
        )
        df = df.rename(columns=rename_map)

        # 数值字段统一转为数值类型
        for col in ["dividend_yield_ratio"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    async def run(
        self,
        start_date: str = None,
        end_date: str = None,
        progress=None,
        task_id=None,
    ) -> pd.DataFrame:
        """
        获取申万三级行业成份数据

        说明:
        - 先通过 ak.sw_index_third_info 获取所有申万三级行业代码；
        - 再通过 ak.sw_index_second_info 获取二级行业信息；
        - 结合二级 / 三级行业信息构造行业层级映射；
        - 循环这些三级行业代码，通过 ak.sw_index_third_cons(symbol=code)
          获取对应行业的成份股数据，并补齐行业1/2/3级名称；
        - 不保留 sw_index_second_info / sw_index_third_info 的原始数据，只返回成份股数据。
        - start_date / end_date 仅为兼容调度器的统一签名，本接口不按日期过滤。
        """
        # 三级行业信息（含：行业代码、行业名称、上级行业=二级名称）
        third_info_df = ak.sw_index_third_info()
        # 二级行业信息（含：行业名称、上级行业=一级名称）
        second_info_df = ak.sw_index_second_info()
        # 构建行业层级映射
        # 三级行业代码 -> 三级行业名称
        third_name_map = third_info_df.set_index("行业代码")["行业名称"].to_dict()
        # 三级行业代码 -> 二级行业名称（上级行业）
        third_to_second_name_map = third_info_df.set_index("行业代码")["上级行业"].to_dict()
        # 二级行业名称 -> 一级行业名称（上级行业）
        second_to_first_name_map = second_info_df.set_index("行业名称")["上级行业"].to_dict()

        # 所有三级行业代码列表
        industry_codes = list(third_name_map.keys())
        total = len(industry_codes)

        if total == 0:
            return pd.DataFrame()

        # 进度条总数设置为行业数量
        if progress and task_id is not None:
            progress.update(task_id, total=total)

        all_list = []

        for idx, code in enumerate(industry_codes, start=1):
            # 调用 akshare 行业成份接口
            await asyncio.sleep(random.randint(0, 1))
            try:
                cons_df = ak.sw_index_third_cons(symbol=code)
            except:
                await asyncio.sleep(random.randint(0, 1))
                cons_df = ak.sw_index_third_cons(symbol=code)
            # 正常返回才处理
            parts = cons_df["股票代码"].str.split(".", expand=True)
            cons_df["code"] = parts[0]
            cons_df["market"] = parts[1]
            # 根据三级代码补齐 1/2/3 级行业名称
            industry3 = third_name_map.get(code)
            industry2 = third_to_second_name_map.get(code)
            industry1 = second_to_first_name_map.get(industry2) if industry2 else None
            cons_df["industry"] = industry1
            cons_df["industry2"] = industry2
            cons_df["industry3"] = industry3
            cons_df = self._rename_columns(cons_df)
            cons_df = cons_df.sort_values(["code", "industry"]).reset_index(drop=True)
            cons_df = cons_df[["code","short_name","industry","industry2","industry3","dividend_yield_ratio","market"]]
            all_list.append(cons_df)
            # 更新进度
            if progress and task_id is not None:
                progress.update(
                    task_id,
                    completed=idx,
                    description=f"{self.__class__.__name__} [{idx}/{total}]",
                )

        result_df = pd.concat(all_list, ignore_index=True)
        return result_df
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
申万三级行业成份爬虫

目标：写入表 ashare_sw_index_cons (市场: ashare)
数据源：乐咕乐股-申万三级-行业成份 (ak.sw_index_third_cons)
"""

import asyncio
import logging
import pandas as pd
import akshare as ak

from ..base_spider import BaseSpider
from core.storage import save_dataframe, load_dataframe
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)


@task(description="获取申万一到三级行业成份数据（含行业层级）")
class SwIndexConsSpider(BaseSpider):
    """
    申万三级行业成份爬虫
    """

    resource = "ashare_swhy"
    table_name = "industry"

    def __init__(self, tasks=None, update=False):
        # 兼容调度器，但实际不使用 tasks
        super().__init__(tasks, update)

    def _rename_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        统一字段命名和格式
        """
        rename_map = {
            "纳入时间": "date",
        }
        df = df.rename(columns=rename_map)
        df["date"] = pd.to_datetime(df["date"])
        keep_cols = ["symbol", "date", "market", "industry", "industry2", "industry3", "industry_symbol"]
        df = df[[col for col in keep_cols if col in df.columns]]
        return df

    def check(self):
        pass

    async def run(self) -> None:
        """
        获取申万三级行业成份数据，逐行业插入数据库
        说明：
        - 先通过 ak.sw_index_third_info 获取所有申万三级行业代码；
        - 再通过 ak.sw_index_second_info 获取二级行业信息，用于构建行业层级；
        - 循环每个三级行业，通过 ak.sw_index_third_cons(symbol=symbol) 获取成份股列表；
        - 为每只股票添加行业代码、行业名称（1/2/3级）和日期；
        - 逐行业将数据插入数据库，主键为 确保同一股票同一天只保留一条记录。
        """
        total = len(self.tasks)
        if total > 0:
            # 1. 获取行业信息（使用代理池）
            try:
                third_info_df = await asyncio.to_thread(proxy_pool, ak.sw_index_third_info)
                second_info_df = await asyncio.to_thread(proxy_pool, ak.sw_index_second_info)
            except Exception as e:
                logger.error(f"获取行业信息失败: {e}")
                return
            if third_info_df.empty or second_info_df.empty:
                logger.warning("行业信息为空，退出")
                return
            # 构建行业层级映射
            third_name_map = third_info_df.set_index("行业代码")["行业名称"].to_dict()
            third_to_second_name_map = third_info_df.set_index("行业代码")["上级行业"].to_dict()
            second_to_first_name_map = second_info_df.set_index("行业名称")["上级行业"].to_dict()
            industry_symbols = list(third_name_map.keys())
            # --- 新增逻辑开始：查询数据库过滤已存在的行业符号 ---
            if industry_symbols:
                # 构建 SQL IN 查询的字符串部分
                in_clause = "', '".join(industry_symbols)
                # 查询表中已存在的 symbol
                sql = f"""
                    SELECT DISTINCT industry_symbol
                    FROM {self.table_name}
                    WHERE industry_symbol IN ('{in_clause}')
                """
                existing_symbols = set()
                try:
                    # 使用 self.market 作为 db 参数，与 check 方法保持一致；若未定义则回退到 'ashare'
                    df = load_dataframe(sql, db=self.market)
                    if not df.empty:
                        existing_symbols = set(df['industry_symbol'].tolist())
                except Exception as e:
                    error_msg = str(e)
                    # 如果表不存在，说明是首次运行，不需要过滤
                    if "does not exist" in error_msg.lower():
                        logger.info(f"Table {self.table_name} not initialized yet, will fetch all tasks")
                    else:
                        logger.error(f"检查已存在行业数据失败: {e}")
                # 执行过滤
                if existing_symbols:
                    industry_symbols = [s for s in industry_symbols if s not in existing_symbols]
                    logger.info(f"过滤掉数据库中已存在的 {len(existing_symbols)} 个行业代码，剩余 {len(industry_symbols)} 个待抓取")
            # --- 新增逻辑结束 ---
            total = len(industry_symbols)
            if total == 0:
                logger.warning("未获取到任何新的行业代码，退出")
                return
            logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个行业")
            for idx, symbol in enumerate(industry_symbols, start=1):
                logger.info(f"{self.__class__.__name__} [{idx}/{total}] 正在处理行业 {symbol}")
                # 2. 获取成份股（使用代理池，带重试）
                try:
                    cons_df = await asyncio.to_thread(proxy_pool, ak.sw_index_third_cons, symbol=symbol)
                except Exception as e:
                    logger.warning(f"获取行业 {symbol} 失败: {e}")
                    continue
                if cons_df.empty:
                    logger.warning(f"行业 {symbol} 无成份股数据")
                    continue
                # 处理数据
                parts = cons_df["股票代码"].str.split(".", expand=True)
                cons_df["symbol"] = parts[0]
                cons_df["market"] = parts[1].str.lower()
                cons_df["industry_symbol"] = symbol
                cons_df["industry3"] = third_name_map.get(symbol)
                industry2 = third_to_second_name_map.get(symbol)
                cons_df["industry2"] = industry2
                cons_df["industry"] = second_to_first_name_map.get(industry2) if industry2 else None
                cons_df = self._rename_columns(cons_df)
                required_cols = ["symbol", "date", "market", "industry", "industry2", "industry3", "industry_symbol"]
                missing = [c for c in required_cols if c not in cons_df.columns]
                if missing:
                    logger.warning(f"行业 {symbol} 处理后缺少列 {missing}，跳过")
                    continue
                # 3. 保存数据
                try:
                    save_dataframe(
                        cons_df,
                        table_name=self.table_name,
                        db="ashare",
                        primary_key=["symbol", "date", "market"]
                    )
                    logger.info(f"行业 {symbol} 数据已保存，共 {len(cons_df)} 条记录")
                except Exception as e:
                    logger.error(f"插入行业 {symbol} 数据失败: {e}")
            logger.info(f"{self.__class__.__name__}: 数据抓取完成，共处理 {total} 个行业")
        else:
            logger.info("No tasks to run.")
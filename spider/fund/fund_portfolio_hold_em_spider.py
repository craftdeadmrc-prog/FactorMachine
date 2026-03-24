import asyncio
import logging
import re
from datetime import datetime, date
from typing import List, Dict

import pandas as pd
import akshare as ak

from ..base_spider import BaseSpider
from core.storage import save_dataframe, load_dataframe
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)

@task(description="获取ETF基金持仓数据（股票持仓明细）")
class FundPortfolioHoldEmSpider(BaseSpider):
    """
    ETF 基金持仓爬虫（仅限 ETF）

    目标：写入表 fund_portfolio_hold
    数据源：天天基金网-基金档案-投资组合 (ak.fund_portfolio_hold_em)
    """
    resource = "fund_eastmoney"
    table_name = "fund_portfolio_hold"

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    # ---------- 工具方法 ----------
    def _quarter_to_date(self, s: str):
        """
        将季度字符串转换为季度第一天的日期字符串 "YYYY-MM-DD"
        例如："2024年1季度股票投资明细" -> "2024-01-01"
        """
        if not s or not isinstance(s, str):
            return None
        match = re.search(r"(\d{4})年(\d+)季度", s)
        if match:
            year = match.group(1)
            quarter = match.group(2)
            month = (int(quarter) - 1) * 3 + 1
            return pd.to_datetime(f"{year}-{month:02d}-01")
        return None

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        """
        统一字段命名和格式：
        - symbol: 基金代码
        - date: 季度第一天的日期（datetime类型）
        - stock_id: 股票代码
        - stock_name: 股票名称
        - holding_ratio: 占净值比例（%）
        - holding_number: 持股数（万股）
        - holding_value: 持仓市值（万元）
        序号列直接丢弃
        """
        if df.empty:
            return df

        # 丢弃序号列（如果存在）
        if "序号" in df.columns:
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

        # 添加基金代码和市场字段
        df["symbol"] = symbol
        df["market"] = market

        # 将季度转换为日期
        if "quarter" in df.columns:
            df["date"] = df["quarter"].apply(self._quarter_to_date)
            df = df.drop(columns=["quarter"])

        # 将数值列转为数字类型
        for col in ["holding_ratio", "holding_number", "holding_value"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 按 symbol、date 排序
        df = df.sort_values(["symbol", "date"], na_position="last").reset_index(drop=True)
        return df

    # ---------- check ----------
    def check(self):
        """
        检查数据库中已有数据，根据最新数据年份决定任务是否需要抓取以及调整年份范围。
        逻辑：
        1. 如果数据库中该基金已有今年的数据，则从 tasks 中剔除该任务。
        2. 否则，保留任务，并将起始年份调整为最新年份 + 1（避免重复），结束年份设为当前年份。
        """
        if not self.tasks:
            return

        current_year = datetime.now().year
        new_tasks = []

        for task in self.tasks:
            symbol = task.get("symbol")
            if not symbol:
                logger.warning(f"任务缺少 symbol: {task}，跳过")
                continue

            # 查询该基金在数据库中的最大日期
            sql = f"""
                SELECT MAX(date) as max_date
                FROM {self.table_name}
                WHERE symbol = '{symbol}'
            """
            try:
                df = load_dataframe(sql, db=self.market)  # 使用类属性 market
                if df.empty or df.iloc[0]["max_date"] is None:
                    # 无历史数据，保留原任务
                    new_tasks.append(task)
                    continue

                max_date = df.iloc[0]["max_date"]
                if isinstance(max_date, (date, datetime)):
                    max_year = max_date.year

                if max_year >= current_year:
                    # 已有今年或更新的数据，跳过该任务
                    logger.info(f"{symbol} 已有 {max_year} 年数据（当前年份 {current_year}），跳过抓取")
                    continue
                else:
                    # 需要抓取，调整年份范围
                    start_date = max_date
                    task["start_date"] = start_date
                    new_tasks.append(task)
                    logger.info(f"{symbol} 最新数据年份 {max_year}，调整后抓取范围：{max_year} ~ {current_year}")
            except Exception as e:
                logger.error(f"检查 {symbol} 数据时出错: {e}，保留原任务")
                new_tasks.append(task)
        self.tasks = new_tasks
        logger.info(f"check 后剩余 {len(self.tasks)} 个任务")

    # ---------- run ----------
    async def run(self, progress=None, task_id=None):
        """
        参数 progress 和 task_id 保留以兼容调度器调用，但内部不再使用，改用 logger.info 输出进度。
        """
        if not self.tasks:
            logger.info("没有任务需要执行。")
            return

        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")

        for idx, task in enumerate(self.tasks, 1):
            logger.info(f"{self.__class__.__name__} [{idx}/{total}] 正在处理 {task['symbol']}")

            symbol = task.get("symbol")
            market = task.get("market")  # 市场标识，如 "fund"
            start_date = task.get("start_date")
            end_date = task.get("end_date")

            if not symbol:
                logger.warning(f"任务缺少 symbol，跳过: {task}")
                continue

            start_year = start_date.year
            end_year = end_date.year if end_date else datetime.now().year

            # 按年份抓取
            for year in range(start_year, end_year + 1):
                try:
                    df = await asyncio.to_thread(
                        proxy_pool,               # 代理池包装函数
                        ak.fund_portfolio_hold_em,
                        symbol=symbol,
                        date=str(year)
                    )
                except Exception as e:
                    logger.error(f"获取基金 {symbol} {year} 年持仓失败: {e}")
                    continue

                if df is None or df.empty:
                    logger.debug(f"基金 {symbol} {year} 年无持仓数据")
                    continue

                # 处理数据
                df = self._rename_columns(df, symbol, market)

                # 插入数据库
                try:
                    save_dataframe(
                        df,
                        table_name=self.table_name,
                        db=self.market,  # 使用类属性 market
                        primary_key=["symbol", "date", "stock_id"]
                    )
                    logger.info(f"基金 {symbol} {year} 年持仓数据已保存，共 {len(df)} 条")
                except Exception as e:
                    logger.error(f"插入基金 {symbol} {year} 年持仓数据失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，共处理 {total} 个任务")
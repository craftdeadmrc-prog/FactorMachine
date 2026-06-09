import asyncio
import logging
import re
from typing import List, Dict

import pandas as pd
import akshare as ak

from ..base_spider import BaseSpider
from core.storage import save_dataframe
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
    table = "fund_portfolio_hold"

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
        df["holding_value"] = df["holding_value"]*10000
        df["holding_number"] = df["holding_number"]*10000
        # 按 symbol、date 排序
        df = df.sort_values(["symbol", "date"], na_position="last").reset_index(drop=True)
        return df

    # ---------- check ----------
    def check(self):
        # 先执行父类检查（可能会处理 update 标志等基础逻辑）
        super().check()
        try:
            # 计算三个月前的时间点
            # 使用 pd.DateOffset 处理月份跨度，确保逻辑准确
            new_tasks = []
            for task in self.tasks:
                three_months_ago = pd.Timestamp.now().date() - pd.DateOffset(months=3)
                if task["start_date"]<=three_months_ago:
                    new_tasks.append(task)
            self.tasks = new_tasks
            logger.info(f"过滤掉最近3个月已更新的基金持仓数据，剩余 {len(self.tasks)} 个任务")
        except Exception as e:
            logger.error(f"检查基金持仓数据更新状态失败: {e}")
    # ---------- run ----------
    async def run(self):
        """
        参数 progress 和 task_id 保留以兼容调度器调用，但内部不再使用，改用 logger.info 输出进度。
        """
        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")

        # 控制并发年份数，避免对同一基金接口造成过大压力
        semaphore = asyncio.Semaphore(3)
        for idx, task in enumerate(self.tasks, 1):
            if idx%10==0:
                logger.info(f"{self.__class__.__name__} [{idx}/{total}] 正在处理 {task['symbol']}")

            symbol = task.get("symbol")
            market = task.get("market")
            start_date = task.get("start_date")
            end_date = task.get("end_date")

            if not symbol:
                logger.warning(f"任务缺少 symbol，跳过: {task}")
                continue
            start_year = start_date.year
            end_year = end_date.year if end_date else pd.Timestamp.now().year
            # 准备所有年份的抓取协程
            async def fetch_year(year: int):
                async with semaphore:
                    try:
                        df = await asyncio.to_thread(
                            proxy_pool,
                            ak.fund_portfolio_hold_em,
                            symbol=symbol,
                            date=str(year)
                        )
                    except Exception as e:
                        if year==end_year:
                            return None
                        logger.error(f"获取基金 {symbol} {year} 年持仓失败: {e}")
                        return None

                    if df is None or df.empty:
                        logger.debug(f"基金 {symbol} {year} 年无持仓数据")
                        return None

                    # 处理数据
                    df = self._rename_columns(df, symbol, market)

                    # 插入数据库
                    try:
                        save_dataframe(
                            df,
                            table=self.table,
                            db=self.market,
                            primary_key=["stock_id", "symbol", "date"]
                        )
                        logger.info(f"基金 {symbol} {year} 年持仓数据已保存，共 {len(df)} 条")
                        return True
                    except Exception as e:
                        logger.error(f"插入基金 {symbol} {year} 年持仓数据失败: {e}")
                        return None

            # 并发执行所有年份
            years = list(range(int(start_year), int(end_year) + 1))
            await asyncio.gather(*[fetch_year(year) for year in years])

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，共处理 {total} 个任务")
import asyncio
import logging
import pandas as pd
import akshare as ak

from ..base_spider import BaseSpider
from core.storage import save_dataframe, load_dataframe
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)


@task(description="获取A股前后复权因子")
class StockAdjustFactorSpider(BaseSpider):
    resource = "ashare_sina"
    table_name = "adjust_factor"

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        df["symbol"] = symbol
        df["market"] = market
        if "hfq_factor" in df.columns:
            df["hfq_factor"] = df["hfq_factor"].astype(float)
            df = df[["symbol", "date", "hfq_factor"]]
        else:
            df["qfq_factor"] = df["qfq_factor"].astype(float)
            df = df[["symbol", "date", "qfq_factor"]]
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df
    def check(self):
        # 先执行父类检查（可能会处理 update 标志等基础逻辑）
        super().check()
        # 1. 收集所有待处理的 symbol
        symbols = list(set([t.get("symbol") for t in self.tasks if t.get("symbol")]))
        # 2. 构建 SQL 批量查询，获取每个 symbol 的最新日期
        # 使用 IN 子句批量检索
        in_clause = "', '".join(symbols)
        sql = f"""
            SELECT symbol, MAX(date) as latest_date
            FROM {self.table_name}
            WHERE symbol IN ({in_clause})
            GROUP BY symbol
        """
        try:
            # 查询数据库
            df = load_dataframe(sql, db=self.market)
            if df.empty:
                # 表为空或无匹配记录，无需过滤
                return
            # 3. 计算一个月前的时间点
            # 使用 pd.DateOffset 处理月份跨度，确保逻辑准确
            six_months_ago = pd.Timestamp.now().date() - pd.DateOffset(months=6)
            df['latest_date'] = pd.to_datetime(df['latest_date'])
            # 4. 筛选出需要过滤的 symbol
            # 条件：最新日期 >= 六个月前（即距离今日不超过六个月）
            recent_symbols = set(
                df[df['latest_date'] >= six_months_ago]['symbol']
            )
            if recent_symbols:
                # 过滤任务：保留 symbol 不在 recent_symbols 中的任务
                self.tasks = [t for t in self.tasks if t.get("symbol") not in recent_symbols]
                logger.info(f"过滤掉最近6个月已更新的 {len(recent_symbols)} 只复权因子，剩余 {len(self.tasks)} 个任务")
        except Exception as e:
            error_msg = str(e).lower()
            # 表不存在是正常情况（首次运行），使用 INFO 级别日志
            if "does not exist" in error_msg:
                logger.info(f"Table {self.table_name} 尚未初始化，跳过增量检查")
            else:
                logger.error(f"检查复权数据更新状态失败: {e}")
    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")

        for idx, task in enumerate(self.tasks, 1):
            if idx%10==0:
                logger.info(f"{self.__class__.__name__} [{idx}/{total}] 正在处理 {task['symbol']}")

            market = task['market']
            symbol = task['symbol']
            code = f"{market}{symbol}"

            # 并发获取前后复权因子
            async def fetch_hfq():
                return await asyncio.to_thread(
                    proxy_pool,
                    ak.stock_zh_a_daily,
                    symbol=code,
                    adjust="hfq-factor"
                )

            async def fetch_qfq():
                return await asyncio.to_thread(
                    proxy_pool,
                    ak.stock_zh_a_daily,
                    symbol=code,
                    adjust="qfq-factor"
                )

            hfq_result, qfq_result = await asyncio.gather(
                fetch_hfq(), fetch_qfq(), return_exceptions=True
            )

            # 检查异常
            if isinstance(hfq_result, Exception):
                logger.error(f"获取股票 {code} 后复权因子失败: {hfq_result}")
                continue
            if isinstance(qfq_result, Exception):
                logger.error(f"获取股票 {code} 前复权因子失败: {qfq_result}")
                continue

            hfq_df = hfq_result
            qfq_df = qfq_result

            # 重命名列
            hfq_df = self._rename_columns(hfq_df, symbol, market)
            qfq_df = self._rename_columns(qfq_df, symbol, market)

            # 合并前后复权因子
            adjust_df = pd.merge(hfq_df, qfq_df, on=["symbol", "date"])

            try:
                save_dataframe(
                    adjust_df,
                    table_name=self.table_name,
                    db=self.market,
                    primary_key=["symbol", "date"]
                )
                if idx % 10 == 0:
                    logger.info(f"股票 {code} 前后复权因子已保存，共 {len(adjust_df)} 条")
            except Exception as e:
                logger.error(f"插入股票 {code} 前后复权因子失败: {e}")

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")
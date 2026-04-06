# spider/stock/stock_zh_a_minute_spider.py
import asyncio
import logging
import pandas as pd
import akshare as ak
from typing import List, Dict
from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.proxy import proxy_pool, _proxy_list
from core.scheduler import task
logger = logging.getLogger(__name__)
@task(description="获取A股分钟线行情数据（新浪/东财）")
class StockZhAMinuteSpider(BaseSpider):
    """
    A股分钟线行情爬虫
    目标：写入表 kline_1m
    数据源：ak.stock_zh_a_minute (默认 period='1' 即1分钟线)
    说明：获取近期分钟线数据，volume单位转换为股
    """
    resource = "ashare_sina"
    table_name = "kline_1m"
    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)
    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        """
        统一字段命名和格式
        """
        if df.empty:
            return df
        # 字段映射
        rename_map = {
            "day": "date",
        }
        df = df.rename(columns=rename_map)
        # 添加元数据字段
        df["symbol"] = symbol
        df["market"] = market
        # 转换日期格式
        df["date"] = pd.to_datetime(df["date"])
        # volume 从手转换为股 (乘以 100)
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce") * 100
        # 确保数值类型
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # 按时间排序
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df
    def check(self):
        super().check()
    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return
        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")
        for idx, task in enumerate(self.tasks, 1):
            symbol = task.get("symbol")
            market = task.get("market")
            code = f"{market}{symbol}"
            try:
                # 调用接口，period='1' 代表1分钟线
                df = await asyncio.to_thread(
                    proxy_pool,
                    ak.stock_zh_a_minute,
                    symbol=code,
                    period='1',
                    adjust=""  # 不复权
                )
                if len(_proxy_list)<=1:
                    await asyncio.sleep(1)  # 无代理时适当等待，避免频率过快被封
            except Exception as e:
                logger.error(f"获取股票 {code} 分钟线失败: {e}")
                return
            if df is None or df.empty:
                logger.warning(f"股票 {code} 无分钟线数据")
                continue
            # 数据清洗
            df = self._rename_columns(df, symbol, market)
            try:
                save_dataframe(
                    df,
                    table_name=self.table_name,
                    db=self.market,
                    primary_key=["symbol", "date"]
                )
                if idx % 10 == 0:
                     logger.info(f"[{idx}/{total}] {code} 分钟线数据已保存，共 {len(df)} 条")
            except Exception as e:
                logger.error(f"插入股票 {code} 分钟线数据失败: {e}")
        # 并发执行所有任务
        logger.info(f"{self.__class__.__name__}: 数据抓取完成，共处理 {total} 个任务")

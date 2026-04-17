"""
A股日内逐笔成交爬虫 - OpenTDX版本
目前精度仅有分钟，用索引*3秒后退,
但存在一部分类似扰动的情况使得无法和腾讯对齐，
且个别action性质有偏差比如末尾
速度约20条/s,最早到2000-06-09但数据较稀疏,
难以对齐等待未来解决方法
"""
# spider/stock/stock_intraday_spider.py
import asyncio
import logging
import pandas as pd
import akshare as ak
import threading
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor

from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.scheduler import task
from core.config import MAX_CONCURRENCY
from opentdx.tdxClient import TdxClient
from opentdx.const import MARKET

logger = logging.getLogger(__name__)

_TRADE_DATE_CACHE: Optional[pd.DataFrame] = None
_TDX_CLIENT: Optional[TdxClient] = None
_tdx_client_lock = threading.Lock()


# @task(description="获取A股日内逐笔成交数据（OpenTDX）")
class StockIntradayTdxSpider(BaseSpider):
    """
    A股日内逐笔成交爬虫
    ─────────────────────────────────────
    目标表：kline_3s | 数据源：OpenTDX stock_transaction
    """
    resource = "ashare_tdx"
    table_name = "kline_3s"
    
    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)
        self.executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENCY)
        self.buffer_lock = threading.Lock()
        self.day_buffer_dfs = []
        self.day_task_count = 0
    
    def check(self):
        super().check()
        min_allowed = pd.Timestamp("2000-06-09")
        for t in self.tasks:
            if t.get("start_date"):
                sd = pd.Timestamp(t["start_date"]) if isinstance(t["start_date"], str) else t["start_date"]
                if sd < min_allowed:
                    t["start_date"] = min_allowed
    
    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: MARKET, date: pd.Timestamp) -> pd.DataFrame:
        """
        【核心清洗函数】所有数据转换逻辑集中于此
        修复：groupby().apply() 添加 include_groups=False 消除 FutureWarning
        """
        if df is None or df.empty:
            return pd.DataFrame()
        
        # === 1. 删除unknown列 ===
        if "unknown" in df.columns:
            df = df.drop(columns="unknown")
        
        # === 2. 字段重命名 ===
        rename_map = {"time": "date", "price": "close", "vol": "volume"}
        df = df.rename(columns=rename_map)
        
        # === 4. action转小写 ===
        df["action"] = df["action"].astype(str).str.lower()
        
        # === 5. 合并完整日期：trade_date + time ===
        df["time_only"] = pd.to_timedelta(df["date"].astype(str))
        df["date"] = date + df["time_only"]
        df = df.drop(columns=["time_only"])
        
        # === 6. 时间轴修正：3秒快照偏移 ===
        # 6.1 按分钟分组 + 索引*3秒偏移
        df["_mk"] = df["date"].dt.floor("min")
        
        def _off(g):
            g = g.reset_index(drop=True)
            g["date"] = g["date"] + pd.to_timedelta(g.index.values * 3, unit="s")
            return g
        
        # 🔧 修复：添加 include_groups=False 消除 FutureWarning
        # pandas 2.2+ 默认会对分组列也执行apply操作，需显式排除
        df = df.groupby("_mk", group_keys=False).apply(_off, include_groups=False)
        
        df = df.drop(columns=["_mk"], errors="ignore").reset_index(drop=True)
        
        # === 7. 添加元数据 ===
        df["symbol"] = symbol
        df["market"] = market.name.lower()
        
        # === 8. 数值类型转换 ===
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce") * 100
        
        # === 9. 排序 + 输出字段顺序 ===
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df[["date", "close", "volume", "action", "symbol", "market"]]
    
    def _flush_day_buffer(self):
        """内部方法：刷新当日缓冲数据到存储"""
        if self.day_buffer_dfs:
            combined = pd.concat(self.day_buffer_dfs, ignore_index=True)
            save_dataframe(combined, table_name=self.table_name, db=self.market, primary_key=["symbol", "date"])
            self.day_buffer_dfs = []
            self.day_task_count = 0
    
    def _fetch_clean_save(self, task: Dict, trade_date: pd.Timestamp, idx: int, total: int,
                          day_total: int, progress_lock: threading.Lock,
                          global_count: List[int], day_count: List[int]) -> bool:
        try:
            symbol = task["symbol"]
            market_str = task["market"]
            market = MARKET.SH if market_str.lower() == "sh" else MARKET.SZ
            dt = trade_date.date()  # 仅API调用时转为date对象
            
            global _TDX_CLIENT
            if _TDX_CLIENT is None:
                with _tdx_client_lock:
                    if _TDX_CLIENT is None:
                        _TDX_CLIENT = TdxClient()
            
            with _tdx_client_lock:
                raw = _TDX_CLIENT.stock_transaction(market, symbol, dt)
            
            if not raw:
                return False
            
            df = self._rename_columns(pd.DataFrame(raw), symbol, market, trade_date)
            if df.empty:
                return False
            
            # 🔧 聚合存储：同一日期内每完成100个股票任务后聚合写入
            with self.buffer_lock:
                self.day_buffer_dfs.append(df)
                self.day_task_count += 1
                if self.day_task_count >= 100:
                    self._flush_day_buffer()
            
            # 🔧 进度呈现：同一日期内每完成100个股票任务输出一次日志
            with progress_lock:
                global_count[0] += 1
                day_count[0] += 1
                if day_count[0] % 100 == 0:
                    logger.info(
                        f"[{global_count[0]}/{total}] {market_str}{symbol} "
                        f"{trade_date.date()} ({day_count[0]}/{day_total} stocks done, batch saved)"
                    )
            return True
        except Exception as e:
            logger.warning(f"{task.get('market')}{task.get('symbol')} {trade_date.date()} fail: {e}")
            return False
    
    async def run(self):
        if not self.tasks:
            return
        
        # === 1. 预加载交易日缓存（全局单次）===
        global _TRADE_DATE_CACHE
        if _TRADE_DATE_CACHE is None:
            _TRADE_DATE_CACHE = ak.tool_trade_date_hist_sina()
            _TRADE_DATE_CACHE["trade_date"] = pd.to_datetime(_TRADE_DATE_CACHE["trade_date"])
            _TRADE_DATE_CACHE = _TRADE_DATE_CACHE.sort_values("trade_date").reset_index(drop=True)
        
        # === 2. 预处理任务：收集有效任务 + 日期范围对象化 + 聚合所有交易日 ===
        valid_tasks = []  # List[Tuple[idx, task, start_ts, end_ts]]
        all_dates = set()
        
        for idx, t in enumerate(self.tasks):
            sd, ed = t.get("start_date"), t.get("end_date")
            if not sd or not ed:
                continue
            start_date = pd.Timestamp(sd) if isinstance(sd, str) else sd
            end_date = pd.Timestamp(ed) if isinstance(ed, str) else ed
            valid_tasks.append((idx, t, start_date, end_date))
            mask = (_TRADE_DATE_CACHE["trade_date"] >= start_date) & (_TRADE_DATE_CACHE["trade_date"] <= end_date)
            all_dates.update(_TRADE_DATE_CACHE.loc[mask, "trade_date"])
        
        trade_days = sorted(all_dates)  # 🔧 正序：从start_date到end_date
        
        # 🔧 计算total：股票数×交易日数（所有有效组合）
        total = sum(
            1 for td in trade_days
            for idx, t, start, end in valid_tasks
            if start <= td <= end
        )
        
        # 🔧 进度计数器（线程安全）
        progress_lock = threading.Lock()
        global_count = [0]
        
        # === 3. 按日同步处理===
        for trade_date in trade_days:
            # 🔧 每日开始时重置当日缓冲
            with self.buffer_lock:
                self.day_buffer_dfs = []
                self.day_task_count = 0
            
            day_jobs = [(idx, t) for idx, t, start, end in valid_tasks if start <= trade_date <= end]
            if not day_jobs:
                continue
            
            # 🔧 同日计数器
            day_total = len(day_jobs)
            day_count = [0]
            
            # === 4. 日内并发执行（流式）===
            loop = asyncio.get_event_loop()
            futures = [
                loop.run_in_executor(
                    self.executor, self._fetch_clean_save, t, trade_date, idx+1,
                    total, day_total, progress_lock, global_count, day_count
                )
                for idx, t in day_jobs
            ]
            await asyncio.gather(*futures)
            
            # 🔧 当日所有股票完成后，刷新剩余缓冲数据（不足100个股票的部分）
            with self.buffer_lock:
                self._flush_day_buffer()
        
        # === 5. 资源清理 ===
        global _TDX_CLIENT
        if _TDX_CLIENT:
            try: _TDX_CLIENT.disconnect()
            except: pass
            _TDX_CLIENT = None
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False)
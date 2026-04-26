"""
ETF超级盘口逐笔数据爬虫 - THSDK版本
目标表：kline_1t | 数据源：thsdk tick_super_level1
精度：tick级 | 限频：100ms/次
"""
# spider/fund/fund_level1_spider.py
import asyncio
import logging
import pandas as pd
import akshare as ak
import multiprocessing
from typing import List, Dict
from datetime import timedelta
from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.scheduler import task
from core.config import THS_FILE
from thsdk import THS

logger = logging.getLogger(__name__)

# 成交方向映射：API整数值 -> 存储字符串
TRADE_DIR_MAP = {
    0: 'neutral',
    1: 'buy',
    5: 'sell',
    4294967295: 'pre',
    17: 'after',
    15: 'order'
}

# 市场代码映射：API格式(大写) -> 存储格式(小写)
MARKET_MAP = {
    'sh':'USHJ',
    'sz':'USZJ',
}


@task(description="获取ETF超级盘口逐笔数据（THSDK）")
class FundTickSuperSpider(BaseSpider):
    """
    A股超级盘口逐笔数据爬虫
    ─────────────────────────────────────
    目标表：kline_1t | 数据源：thsdk tick_super_level1
    
    字段说明：
      - date: 成交时间（Asia/Shanghai时区）
      - open: 成交价格
      - volume: 当前量（单笔成交量）
      - trade_num: 交易笔数
      - action: 成交方向（buy/sell/neutral/pre/after/order）
      - a1_p~a5_p: 卖1~卖5价
      - a1_v~a5_v: 卖1~卖5量
      - b1_p~b5_p: 买1~买5价（含委托卖出价映射）
      - b1_v~b5_v: 买1~买5量
      - symbol: 6位证券代码
      - market: 市场标识（sh/sz小写）
    """
    resource = "fund_ths"
    table_name = "kline_1t"
    
    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)
        self.ths_config = self._load_ths_config()
    
    def _load_ths_config(self) -> Dict[str, str]:
        """从配置文件加载THS账户信息（按行读取）"""
        config = {"username": "", "password": "", "mac": ""}
        try:
            with open(THS_FILE, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f]
                if len(lines) >= 2:
                    config["username"] = lines[0]
                    config["password"] = lines[1]
                if len(lines) >= 3:
                    config["mac"] = lines[2]
        except Exception as e:
            logger.warning(f"加载THS配置失败: {e}")
        return config
    
    def check(self):
        """任务校验：限制最早日期为两年前的昨日"""
        super().check()
        min_allowed = pd.Timestamp.today().floor('D') - timedelta(days=365*2)
        for t in self.tasks:
            if t.get("start_date"):
                sd = pd.Timestamp(t["start_date"]) if isinstance(t["start_date"], str) else t["start_date"]
                if sd < min_allowed:
                    t["start_date"] = min_allowed
    
    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        """
        统一字段命名和格式（核心清洗函数）：
        - 过滤首末条汇总数据
        - 删除累计量字段：成交量、总金额
        - 字段重命名映射（5档行情按a1_v/a1_p...b1_v/b1_p列存储）
        - 成交方向转义
        - market转小写存储
        """
        if df is None or df.empty:
            return pd.DataFrame()
        
        # === 1. 删除不需要的累计量字段（可复现，无需存储）===
        df = df.drop(columns=['成交量', '总金额'], errors='ignore')
        
        # === 2. 字段重命名映射 ===
        rename_map = {
            # 基础字段
            '价格': 'open',
            '当前量': 'volume',
            '交易笔数': 'trade_num',
            # 最优价映射（委托买入/卖出价 = 买1/卖1价）
            '委托买入价': 'b1_p',
            '委托卖出价': 'a1_p',
            # 5档行情 - 卖盘（ask）：价p/量v
            '卖1价': 'a1_p', '卖1量': 'a1_v',
            '卖2价': 'a2_p', '卖2量': 'a2_v',
            '卖3价': 'a3_p', '卖3量': 'a3_v',
            '卖4价': 'a4_p', '卖4量': 'a4_v',
            '卖5价': 'a5_p', '卖5量': 'a5_v',
            # 5档行情 - 买盘（bid）：价p/量v
            '买1价': 'b1_p', '买1量': 'b1_v',
            '买2价': 'b2_p', '买2量': 'b2_v',
            '买3价': 'b3_p', '买3量': 'b3_v',
            '买4价': 'b4_p', '买4量': 'b4_v',
            '买5价': 'b5_p', '买5量': 'b5_v',
        }
        df = df.rename(columns=rename_map)
        
        # === 3. 成交方向映射 ===
        df['action'] = df['成交方向'].map(TRADE_DIR_MAP).fillna('unknown')
        df = df.drop(columns=['成交方向'])
        
        # === 4. 时间列处理：Unix秒 -> datetime===
        df['date'] = pd.to_datetime(df['时间'], unit='s', utc=True).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
        df = df.drop(columns=['时间'])
        
        # === 5. 添加元数据 ===
        df['symbol'] = symbol
        # market转小写：USHJ->sh, USZJ->sz
        df['market'] = market
        
        # === 6. 数值类型转换 ===
        numeric_cols = ['open', 'volume', 'trade_num', 
                        'a1_p', 'a2_p', 'a3_p', 'a4_p', 'a5_p',
                        'a1_v', 'a2_v', 'a3_v', 'a4_v', 'a5_v',
                        'b1_p', 'b2_p', 'b3_p', 'b4_p', 'b5_p',
                        'b1_v', 'b2_v', 'b3_v', 'b4_v', 'b5_v']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # === 7. 排序 + 输出字段顺序 ===
        df = df.sort_values(['symbol', 'date']).reset_index(drop=True)
        # 定义标准输出列顺序
        output_cols = ['date', 'open', 'volume', 'trade_num', 'action', 'symbol', 'market',
                       'a1_p', 'a1_v', 'a2_p', 'a2_v', 'a3_p', 'a3_v', 'a4_p', 'a4_v', 'a5_p', 'a5_v',
                       'b1_p', 'b1_v', 'b2_p', 'b2_v', 'b3_p', 'b3_v', 'b4_p', 'b4_v', 'b5_p', 'b5_v']
        # 只保留实际存在的列
        output_cols = [c for c in output_cols if c in df.columns]
        return df[output_cols]
    
    def _fetch_clean_save(self, task: Dict, trade_date: pd.Timestamp, ths: THS) -> pd.DataFrame:
        """单任务获取-清洗-返回DataFrame（由调用方批量存储）"""
        try:
            symbol = task["symbol"]
            market = task["market"]
            market_api = MARKET_MAP.get(market)
            date_str = trade_date.strftime("%Y%m%d")
            
            # 🔧 多进程兼容：检测 ths 参数类型，如果是 dict 则视为配置，内部创建连接
            if isinstance(ths, dict):
                ths_local = THS(ths)
                ths_local.connect()
                ths_to_use = ths_local
                need_disconnect = True
            else:
                ths_to_use = ths
                need_disconnect = False
            
            resp = ths_to_use.tick_super_level1(f"{market_api}{symbol}", date=date_str, buffer_size=1024*1024*128)
            
            if need_disconnect:
                ths_local.disconnect()
            
            if not resp.data:
                logger.warning(f"{market}{symbol} {trade_date.date()} 无数据")
                return None
            # 清洗转换
            df = self._rename_columns(pd.DataFrame(resp.data[1:-1]), symbol, market)
            return df
            
        except Exception as e:
            logger.warning(f"{task.get('market')}{task.get('symbol')} {trade_date.date()} fail: {e}")
            return None
    
    async def _run_multiprocess_batch(self, func, args_list):
        """🔧 新增：在线程池中执行多进程批量任务，避免阻塞 asyncio 事件循环"""
        def _run():
            if not args_list:
                return []
            processes = min(len(args_list), multiprocessing.cpu_count())
            with multiprocessing.Pool(processes=processes) as pool:
                return pool.starmap(func, args_list)
        return await asyncio.to_thread(_run)
    
    async def run(self):
        """主执行入口：按日期串行，日期内按100条分批多进程并行 + 每批立即存储"""
        if not self.tasks:
            return
        
        # === 1. 预加载交易日缓存（全局单次，通过sina api获取）===
        trade_date_cache = await asyncio.to_thread(ak.tool_trade_date_hist_sina)
        trade_date_cache["trade_date"] = pd.to_datetime(trade_date_cache["trade_date"])
        trade_date_cache = trade_date_cache.sort_values("trade_date").reset_index(drop=True)
        
        # === 2. 预处理任务：收集有效任务 + 日期范围 ===
        valid_tasks = []
        for idx, t in enumerate(self.tasks):
            sd, ed = t.get("start_date"), t.get("end_date")
            if not sd or not ed:
                continue
            start_date = pd.Timestamp(sd) if isinstance(sd, str) else sd
            end_date = pd.Timestamp(ed) if isinstance(ed, str) else ed
            valid_tasks.append((idx, t, start_date, end_date))  
        
        # 🔧 计算total：用于进度展示（股票数×交易日数估算）
        total = sum(
            max(1, (end - start).days + 1)
            for idx, t, start, end in valid_tasks
        )
        
        # 🔧 进度：开始时输出全部任务数量
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")
        
        # 🔧 删除：ths = THS(self.ths_config); ths.connect()  多进程模式下每个子进程独立创建连接
        
        # === 3. 按日期优先顺序执行，日期内按100条分批多进程并行 + 每批立即存储 ===
        if not valid_tasks:
            return  
        global_start = min(start for idx, t, start, end in valid_tasks)
        global_end = max(end for idx, t, start, end in valid_tasks)
        
        # 3.2 生成全局交易日序列
        all_dates = pd.date_range(start=global_start, end=global_end, freq='D')
        global_trade_days = [d for d in all_dates if d in trade_date_cache["trade_date"].values]
        
        # 3.3 日期优先遍历：外层日期，内层按100条分批多进程并行
        global_count = 0
        for trade_date in global_trade_days:
            # 🔧 收集当天所有需要执行的任务参数
            day_task_args = []
            day_count = 0
            for idx, t, start_date, end_date in valid_tasks:
                if not (start_date <= trade_date <= end_date):
                    continue
                # 🔧 传入配置 dict 而非 THS 对象，供子进程内部创建连接
                day_task_args.append((t, trade_date, self.ths_config))
                day_count += 1
            
            # 🔧 按100条一批切分执行，降低内存峰值
            if day_task_args:
                batch_size = 100
                for i in range(0, len(day_task_args), batch_size):
                    batch_args = day_task_args[i:i+batch_size]
                    results = await self._run_multiprocess_batch(self._fetch_clean_save, batch_args)
                    # 🔧 过滤None结果后存储，每批立即落盘释放内存
                    valid_results = [r for r in results if r is not None]
                    if valid_results:
                        await asyncio.to_thread(
                            save_dataframe, 
                            pd.concat(valid_results, ignore_index=True), 
                            table_name=self.table_name, 
                            db=self.market, 
                            primary_key=["symbol", "date"]
                            )
            global_count += day_count
            # 🔧 进度日志（保持原有格式和频率）
            logger.info(f"[{global_count}/{total}] {trade_date.date()} counts: {day_count}")
        
        # 🔧 完成日志
        logger.info(f"{self.__class__.__name__}: 数据抓取完成，共处理 {total} 个任务")
"""
A股超级盘口逐笔数据爬虫 - THSDK版本
目标表：kline_1t | 数据源：thsdk tick_super_level1
精度：tick级
"""
# spider/stock/stock_level1_spider.py
import asyncio
import logging
import pandas as pd
import multiprocessing
from typing import List, Dict
from datetime import timedelta
from ..base_spider import BaseSpider
from core.storage import save_dataframe, load_dataframe, loadTable
from core.scheduler import task
from core.config import THS_CONFIG, MAX_CONCURRENCY
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

# 市场代码映射：存储市场 -> THS前缀
MARKET_MAP = {
    'sh': ('USHA', 'USHT', 'USHP', 'USHD'),
    'sz': ('USZA', 'USZT', 'USZP', 'USZD'),
}
STOCK_CODE_MAP: Dict[str, str] = {}


@task(description="获取A股超级盘口逐笔数据（THSDK）")
class StockTickSuperSpider(BaseSpider):
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
    resource = "ashare_ths"
    table = "kline_1t"
    
    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)
        # 🔧 删除重连锁和时间记录：重连逻辑已移除
    
    def check(self):
        """任务校验：仅限制最早日期为两年前，不再使用父类完整性检查。"""
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
        df['action'] = df['成交方向'].map(TRADE_DIR_MAP)
        df = df.drop(columns=['成交方向'])
        
        # === 4. 时间列处理：Unix秒 -> datetime===
        df['date'] = pd.to_datetime(df['时间'], unit='s', utc=True).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
        df = df.drop(columns=['时间'])
        
        # === 5. 添加元数据 ===
        df['symbol'] = symbol
        # market转小写：USHA->sh, USZA->sz
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

    def _fetch_stock_codes(self):
        ths = THS(THS_CONFIG)
        ths.connect()
        resp = ths.stock_cn_lists()
        ths.disconnect()
        return {item["代码"] for item in resp.data}

    def _search_stock_ths_code(self, symbol: str, market_api):
        try:
            ths = THS(THS_CONFIG)
            ths.connect()
            resp = ths.search_symbols(str(symbol))
            ths.disconnect()

            for item in resp.data:
                ths_code = item["THSCODE"]
                if ths_code.startswith(market_api):
                    return ths_code
        except Exception as e:
            logger.warning(f"{market_api}{symbol} search fail: {e}")
            return None

    async def _prepare_stock_tasks(self, valid_tasks):
        stock_codes = await asyncio.to_thread(self._fetch_stock_codes)
        prepared_tasks = []
        search_tasks = []

        for idx, t, start_date, end_date in valid_tasks:
            task = dict(t)
            symbol = task["symbol"]
            market = task["market"]
            market_api = MARKET_MAP[market]
            code_key = f"{market}{symbol}"

            ths_code = STOCK_CODE_MAP.get(code_key)
            if ths_code in stock_codes:
                task["ths_code"] = ths_code
                prepared_tasks.append((idx, task, start_date, end_date))
                continue

            for api in market_api:
                ths_code = f"{api}{symbol}"
                if ths_code in stock_codes:
                    STOCK_CODE_MAP[code_key] = ths_code
                    task["ths_code"] = ths_code
                    prepared_tasks.append((idx, task, start_date, end_date))
                    break
            else:
                search_tasks.append((idx, task, start_date, end_date, code_key, symbol, market_api))

        batch_size = MAX_CONCURRENCY
        for i in range(0, len(search_tasks), batch_size):
            batch_tasks = search_tasks[i:i + batch_size]
            batch_args = [
                (symbol, market_api)
                for _, _, _, _, _, symbol, market_api in batch_tasks
            ]
            results = await self._run_multiprocess_batch(self._search_stock_ths_code, batch_args)
            for (idx, task, start_date, end_date, code_key, _, _), ths_code in zip(batch_tasks, results):
                if not ths_code:
                    logger.warning(f"{task['market']}{task['symbol']} 不在THSDK A股列表中，已跳过")
                    continue
                STOCK_CODE_MAP[code_key] = ths_code
                task["ths_code"] = ths_code
                prepared_tasks.append((idx, task, start_date, end_date))

        return sorted(prepared_tasks, key=lambda item: item[0])
    
    def _fetch_clean_save(self, task: Dict, trade_date: pd.Timestamp) -> pd.DataFrame:
        """单任务获取-清洗-返回DataFrame（由调用方批量存储）"""
        try:
            symbol = task["symbol"]
            market = task["market"]
            ths_code = task["ths_code"]
            date_str = trade_date.strftime("%Y%m%d")
            
            ths = THS(THS_CONFIG)
            ths.connect()
            
            resp = ths.tick_super_level1(ths_code, date=date_str, buffer_size=1024*1024*128)
            ths.disconnect()
            
            if not resp.data:
                logger.warning(f"{market}{symbol} {trade_date.date()} 无数据")
                return None
            # 清洗转换
            df = self._rename_columns(pd.DataFrame(resp.data[1:-1]), symbol, market)
            if df.empty:
                return None
            return df  # 🔧 返回 df 而非直接存储
            
        except Exception as e:
            logger.warning(f"{task.get('market')}{task.get('symbol')} {trade_date.date()} fail: {e}")
            return None
    
    async def _run_multiprocess_batch(self, func, args_list):
        """纯进程池批处理：批内等待全部进程返回后再进入下一批，并避免阻塞事件循环。"""
        if not args_list:
            return []

        # 进程池上限与当前批次大小一致
        processes = len(args_list)
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=processes) as pool:
            async_results = [pool.apply_async(func, args=args) for args in args_list]
            while True:
                if all(r.ready() for r in async_results):
                    break
                await asyncio.sleep(0.05)
            return [r.get() for r in async_results]
    
    async def run(self):
        """主执行入口：按日期串行，先过滤当日已存在symbol，再按MAX_CONCURRENCY分批执行。"""
        if not self.tasks:
            return
                
        # === 1. 预处理任务：收集有效任务 + 日期范围 ===
        valid_tasks = []
        for idx, t in enumerate(self.tasks):
            sd, ed = t.get("start_date"), t.get("end_date")
            if not sd or not ed:
                continue
            start_date = pd.Timestamp(sd) if isinstance(sd, str) else sd
            end_date = pd.Timestamp(ed) if isinstance(ed, str) else ed
            valid_tasks.append((idx, t, start_date, end_date))
        if not valid_tasks:
            return

        valid_tasks = await self._prepare_stock_tasks(valid_tasks)
        if not valid_tasks:
            logger.warning(f"{self.__class__.__name__}: no task matched THSDK A股 list")
            return

        global_start = min(start for idx, t, start, end in valid_tasks)
        global_end = max(end for idx, t, start, end in valid_tasks)

        start_str = pd.Timestamp(global_start).strftime("%Y.%m.%d")
        end_str = pd.Timestamp(global_end).strftime("%Y.%m.%d")
        calendar_sql = f"getMarketCalendar('XSHE',{start_str}, {end_str})"
        calendar_raw = await asyncio.to_thread(load_dataframe, calendar_sql, self.market)
        if calendar_raw is None or len(calendar_raw) == 0:
            logger.warning(f"{self.__class__.__name__}: empty trade calendar from sql: {calendar_sql}")
            return
        global_trade_days = sorted(pd.to_datetime(pd.Index(calendar_raw)))
        
        total = sum(
            1
            for td in global_trade_days
            for idx, t, start, end in valid_tasks
            if start <= td <= end
        )
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")
                
        # === 3. 按日期优先顺序执行：每日先读取当日已入库symbol，过滤后再分批 ===
        global_count = 0
        skipped_count = 0
        for trade_date in global_trade_days:
            day_jobs = [
                (idx, t)
                for idx, t, start_date, end_date in valid_tasks
                if start_date <= trade_date <= end_date
            ]
            if not day_jobs:
                continue

            day_str = trade_date.strftime("%Y.%m.%d")
            existing_sql = loadTable(
                "distinct symbol",
                self.table,
                self.market,
                f"where date(date)={day_str}",
            )
            existing_df = await asyncio.to_thread(load_dataframe, existing_sql, self.market)
            existing_symbols = (
                set(existing_df["symbol"].astype(str).tolist())
                if existing_df is not None and not existing_df.empty and "symbol" in existing_df.columns
                else set()
            )

            # 🔧 先筛掉当日该表中已存在数据的symbol，再对剩余任务分批
            day_task_args = [
                (t, trade_date)
                for _, t in day_jobs
                if str(t.get("symbol")) not in existing_symbols
            ]
            day_skipped = len(day_jobs) - len(day_task_args)
            skipped_count += day_skipped
            day_count = len(day_task_args)
            
            day_remain = 0
            if day_task_args:
                batch_size = MAX_CONCURRENCY
                for i in range(0, len(day_task_args), batch_size):
                    batch_args = day_task_args[i:i+batch_size]
                    last = None
                    same = 0
                    while batch_args:
                        results = await self._run_multiprocess_batch(self._fetch_clean_save, batch_args)
                        # 🔧 过滤None结果后存储，每批立即落盘释放内存
                        valid_results = [r for r in results if r is not None]
                        if valid_results:
                            save_df = pd.concat(valid_results, ignore_index=True)
                            await asyncio.to_thread(
                                save_dataframe,
                                save_df,
                                table=self.table,
                                db=self.market,
                                freq="tick",
                                primary_key=["symbol", "date"]
                                )
                            fetched_symbols = set(save_df["symbol"].astype(str).tolist())
                            batch_args = [args for args in batch_args if str(args[0].get("symbol")) not in fetched_symbols]

                        remain = len(batch_args)
                        if remain == 0:
                            break
                        if remain == last:
                            same += 1
                        else:
                            last = remain
                            same = 1
                        if same >= 3:
                            day_remain += remain
                            break
            global_count += day_count
            logger.info(
                f"[{global_count}/{total}] {trade_date.date()} counts: {day_count}, skipped: {day_skipped}, remain: {day_remain}"
            )
                
        logger.info(
            f"{self.__class__.__name__}: 数据抓取完成，共处理 {global_count} 个任务，跳过 {skipped_count} 个已存在任务"
        )

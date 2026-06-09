"""
股票指数超级盘口逐笔数据爬虫 - THSDK版本
目标表：kline_1t | 数据源：thsdk tick_super_level1
精度：tick级
"""
# spider/index/index_level1_spider.py
import asyncio
import logging
import multiprocessing
from datetime import timedelta
from typing import Dict, List

import pandas as pd

from ..base_spider import BaseSpider
from core.config import MAX_CONCURRENCY, THS_CONFIG
from core.scheduler import task
from core.storage import loadTable, load_dataframe, save_dataframe
from thsdk import THS

logger = logging.getLogger(__name__)

MARKET_MAP = {
    "sh": "USHI",
    "sz": "USZI",
}
INDEX_CODE_MAP: Dict[str, str] = {}


@task(description="获取指数超级盘口逐笔数据（THSDK）")
class IndexTickSpider(BaseSpider):
    """
    股票指数超级盘口逐笔数据爬虫
    目标表：kline_1t | 数据源：thsdk tick_super_level1
    """

    resource = "index_ths"
    table = "kline_1t"

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def check(self):
        """任务校验：仅限制最早日期为两年前，不再使用父类完整性检查。"""
        min_allowed = pd.Timestamp.today().floor("D") - timedelta(days=365 * 2)
        for t in self.tasks:
            if t.get("start_date"):
                sd = pd.Timestamp(t["start_date"]) if isinstance(t["start_date"], str) else t["start_date"]
                if sd < min_allowed:
                    t["start_date"] = min_allowed

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(
            columns={
                "价格": "open",
                "当前量": "volume",
            }
        )
        df["date"] = (
            pd.to_datetime(df["时间"], unit="s", utc=True)
            .dt.tz_convert("Asia/Shanghai")
            .dt.tz_localize(None)
            .dt.floor("s")
        )
        df = df.drop(columns=["时间"])

        df["open"] = pd.to_numeric(df["open"], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
        df["symbol"] = symbol
        df["market"] = market

        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df[["date", "open", "volume", "symbol", "market"]]

    def _fetch_index_codes(self):
        ths = THS(THS_CONFIG)
        ths.connect()
        resp = ths.index_list()
        ths.disconnect()
        return {item["代码"] for item in resp.data}

    def _search_index_ths_code(self, symbol: str, market_api: str, index_codes):
        try:
            ths = THS(THS_CONFIG)
            ths.connect()
            resp = ths.search_symbols(str(symbol))
            ths.disconnect()

            for item in resp.data:
                ths_code = item["THSCODE"]
                if ths_code.startswith(market_api) and ths_code in index_codes:
                    return ths_code
        except Exception as e:
            logger.warning(f"{market_api}{symbol} search fail: {e}")
            return None

    async def _prepare_index_tasks(self, valid_tasks):
        index_codes = await asyncio.to_thread(self._fetch_index_codes)
        prepared_tasks = []
        search_tasks = []

        for idx, t, start_date, end_date in valid_tasks:
            task = dict(t)
            symbol = task["symbol"]
            market = task["market"]
            market_api = MARKET_MAP[market]
            code_key = f"{market}{symbol}"

            ths_code = INDEX_CODE_MAP.get(code_key)
            if ths_code in index_codes:
                task["ths_code"] = ths_code
                prepared_tasks.append((idx, task, start_date, end_date))
                continue

            ths_code = f"{market_api}{symbol}"
            if ths_code in index_codes:
                INDEX_CODE_MAP[code_key] = ths_code
                task["ths_code"] = ths_code
                prepared_tasks.append((idx, task, start_date, end_date))
                continue

            search_tasks.append((idx, task, start_date, end_date, code_key, symbol, market_api))

        batch_size = MAX_CONCURRENCY
        for i in range(0, len(search_tasks), batch_size):
            batch_tasks = search_tasks[i:i + batch_size]
            batch_args = [
                (symbol, market_api, index_codes)
                for _, _, _, _, _, symbol, market_api in batch_tasks
            ]
            results = await self._run_multiprocess_batch(self._search_index_ths_code, batch_args)
            for (idx, task, start_date, end_date, code_key, _, _), ths_code in zip(batch_tasks, results):
                if not ths_code:
                    logger.warning(f"{task['market']}{task['symbol']} 不在THSDK指数列表中，已跳过")
                    continue
                INDEX_CODE_MAP[code_key] = ths_code
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
            resp = ths.tick_super_level1(ths_code, date=date_str, buffer_size=1024 * 1024 * 128)
            ths.disconnect()

            if not resp.data:
                logger.warning(f"{market}{symbol} {trade_date.date()} 无数据")
                return None
            resp_data = resp.data[1:-1]
            resp_data = resp_data[:-1] if resp.data[-1]['时间']<1717500000 else resp_data
            df = self._rename_columns(pd.DataFrame(resp_data), symbol, market)
            if df.empty:
                return None
            return df

        except Exception as e:
            logger.warning(f"{task.get('market')}{task.get('symbol')} {trade_date.date()} fail: {e}")
            return None

    async def _run_multiprocess_batch(self, func, args_list):
        """纯进程池批处理：批内等待全部进程返回后再进入下一批，并避免阻塞事件循环。"""
        if not args_list:
            return []

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

        valid_tasks = await self._prepare_index_tasks(valid_tasks)
        if not valid_tasks:
            logger.warning(f"{self.__class__.__name__}: no task matched THSDK index list")
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
                    batch_args = day_task_args[i:i + batch_size]
                    last = None
                    same = 0
                    while batch_args:
                        results = await self._run_multiprocess_batch(self._fetch_clean_save, batch_args)
                        valid_results = [r for r in results if r is not None]
                        if valid_results:
                            save_df = pd.concat(valid_results, ignore_index=True)
                            await asyncio.to_thread(
                                save_dataframe,
                                save_df,
                                table=self.table,
                                db=self.market,
                                freq="tick",
                                primary_key=["symbol", "date"],
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

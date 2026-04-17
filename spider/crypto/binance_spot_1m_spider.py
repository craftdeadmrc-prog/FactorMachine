# spider/crypto/crypto_binance_spot_1m_spider.py
import asyncio
import aiohttp
import aiofiles
import pandas as pd
import zipfile
import logging
import os
import requests
from typing import Optional, List, Dict
from ..base_spider import BaseSpider
from core.storage import save_dataframe, load_dataframe
from core.config import DATA_PATH, MAX_CONCURRENCY
from core.proxy import proxy_pool
from core.scheduler import task
from concurrent.futures import ThreadPoolExecutor  # 新增导入
logger = logging.getLogger(__name__)
@task(description="获取币安现货1分钟K线数据（日粒度ZIP包）")
class CryptoBinanceSpot1mKlinesSpider(BaseSpider):
    resource = "spot_binance"
    table_name = "kline_1m"
    temp_dir = os.path.join(DATA_PATH, "crypto_binance_temp")
    os.makedirs(temp_dir, exist_ok=True)
    # 原始 CSV 列名（共 12 列）
    column_names = [
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'amount', 'trade_num',
        'taker_buy_volume', 'taker_buy_amount', 'ignore'
    ]
    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)
    def _rename_columns(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """添加标识字段、处理时间、删除无用列"""
        df['open_time'] = (df['open_time'] // 1000).astype('int64')
        time_test = pd.to_datetime(df['open_time'][0] // 1000, unit='s')
        if time_test > pd.to_datetime("1980-01-01"):
            df['date'] = pd.to_datetime(df['open_time'] // 1000, unit='s')
        else:
            df['date'] = pd.to_datetime(df['open_time'], unit='s')
        df.drop(columns=['open_time', 'close_time', 'ignore'], inplace=True, errors='ignore')
        df['symbol'] = symbol
        df.sort_values(['symbol', 'date'], inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df
    # ---------- 代理池包装的网络请求 ----------
    def _head_request_sync(self, url: str) -> int:
        """同步 HEAD 请求，返回状态码"""
        resp = requests.head(url, timeout=10)
        return resp.status_code
    def _download_zip_sync(self, url: str, local_path: str) -> bool:
        """同步下载 ZIP 文件，返回是否成功"""
        try:
            with requests.get(url, stream=True, timeout=300) as r:
                if r.status_code == 200:
                    with open(local_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            f.write(chunk)
                    return True
                else:
                    pass
        except Exception as e:
            logger.error(f"下载出错 {url}: {e}")
        return False
    # ---------- 辅助检查方法 (同步版本) ----------
    def _check_one_task(self, task: Dict) -> Optional[Dict]:
        """
        同步检查单个任务：
        1. 检查昨日文件是否存在（退市检测）
        2. 存在则返回 task，否则返回 None
        """
        symbol = task['symbol']
        yesterday = task['end_date']
        date_str = yesterday.strftime("%Y-%m-%d")
        url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1m/{symbol}-1m-{date_str}.zip"
        
        try:
            # 使用 proxy_pool 包装同步请求
            status = proxy_pool(self._head_request_sync, url)
            if status != 200:
                return None
        except Exception as e:
            logger.error(f"检查 {symbol} 昨日文件失败: {e}")
            return None
        
        return task
    # ---------- 数据检查与任务调整（同步并发版） ----------
    def check(self):
        """
        同步检查任务，利用线程池实现并发检查，避免串行等待
        """
        if not self.tasks:
            logger.info("无任务，跳过 check")
            return
 
        logger.info(f"开始并发检查 {len(self.tasks)} 个任务的有效性...")
        
        # 使用线程池并发执行，max_workers 控制并发数
        # MAX_CONCURRENCY 可以作为全局并发限制的参考
        valid_tasks = []
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
            # executor.map 会保持输入顺序，但为了效率我们只需要结果
            # 提交所有任务
            results = executor.map(self._check_one_task, self.tasks)
            
            # 过滤掉结果为 None 的项
            valid_tasks = [res for res in results if res is not None]
 
        self.tasks = valid_tasks
        logger.info(f"check 后剩余 {len(self.tasks)} 个有效任务")
    async def process_symbol(self, symbol: str, start_date: pd.Timestamp, end_date: pd.Timestamp,
                        session: aiohttp.ClientSession):
        # 1. 生成全量日期范围
        all_dates = pd.date_range(start=start_date, end=end_date, freq='D')
        # 2. 读取数据库已存在的日期进行过滤
        # 使用 SQL 读取，注意数据库中存储的是时间戳或日期对象，这里转为 date 对象方便比较
        try:
            # 假设 date 字段是 TIMESTAMP 或 BIGINT，这里使用 date() 函数转成日期字符串或直接比较
            # 为兼容性，读取后由 pandas 处理
            exist_df = load_dataframe(
                sql=f'SELECT DISTINCT "date" FROM "{self.table_name}" WHERE "symbol" = \'{symbol}\'',
                db=self.market
            )
            if not exist_df.empty:
                existing_dates = set(pd.to_datetime(exist_df['date']).dt.date)
                # 过滤掉已存在的日期
                dates_to_process = [d for d in all_dates if d.date() not in existing_dates]
                logger.info(f"{symbol} 数据库已存在 {len(existing_dates)} 天数据，需下载 {len(dates_to_process)} 天")
            else:
                dates_to_process = list(all_dates)
        except Exception as e:
            # 如果表不存在或其他错误，加载全部日期
            logger.warning(f"{symbol} 读取已有日期失败 (可能表不存在): {e}，将处理全量日期")
            dates_to_process = list(all_dates)
        if not dates_to_process:
            logger.info(f"{symbol} 所有日期均已存在，跳过")
            return
        # 3. 按月份分组日期，为了聚合写入
        # 使用 dict 存储: { (year, month): [date_list] }
        monthly_groups: Dict[tuple, List[pd.Timestamp]] = {}
        for dt in dates_to_process:
            key = (dt.year, dt.month)
            if key not in monthly_groups:
                monthly_groups[key] = []
            monthly_groups[key].append(dt)
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        async def process_one_date(date_obj: pd.Timestamp) -> Optional[pd.DataFrame]:
            """下载并解析单日数据，返回 DataFrame"""
            async with semaphore:
                date_str = date_obj.strftime("%Y-%m-%d")
                filename = f"{symbol}-1m-{date_str}.zip"
                url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1m/{filename}"
                local_path = os.path.join(self.temp_dir, filename)
                try:
                    success = await asyncio.to_thread(proxy_pool, self._download_zip_sync, url, local_path)
                    if not success:
                        return None
                except Exception as e:
                    logger.error(f"{symbol} {date_str} 下载异常: {e}")
                    return None
                df = None
                try:
                    with zipfile.ZipFile(local_path, 'r') as zf:
                        csv_files = [f for f in zf.namelist() if f.endswith('.csv')]
                        if csv_files:
                            with zf.open(csv_files[0]) as f:
                                df = pd.read_csv(f, header=None, names=self.column_names)
                except Exception as e:
                    logger.error(f"{symbol} {date_str} 处理 ZIP 失败: {e}")
                finally:
                    if os.path.exists(local_path):
                        os.remove(local_path)
                if df is not None and not df.empty:
                    return self._rename_columns(df, symbol)
                return None
        # 4. 遍历每个月份组，组内并发下载，聚合后写入
        for (year, month), group_dates in monthly_groups.items():
            # 组内并发执行
            tasks = [process_one_date(d) for d in group_dates]
            results = await asyncio.gather(*tasks)
            # 过滤空结果并聚合
            monthly_dfs = [df for df in results if df is not None]
            if monthly_dfs:
                final_df = pd.concat(monthly_dfs, ignore_index=True)
                # 统一写入一个月的数据
                save_dataframe(
                    final_df,
                    table_name=self.table_name,
                    db=self.market,
                    primary_key=["symbol", "date"]
                )
                logger.info(f"{symbol} {year}-{month:02d} 数据已保存，共 {len(final_df)} 条")
        logger.info(f"{symbol} 处理完成")
    # ---------- 主运行方法 ----------
    async def run(self):
        if not self.tasks:
            logger.info("无任务，退出")
            return
        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")
        conn = aiohttp.TCPConnector(limit=10)
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        async with aiohttp.ClientSession(connector=conn) as session:
            processed = 0
            async def process_with_semaphore(task):
                nonlocal processed
                symbol = task['symbol']
                start_date = task['start_date']
                end_date = task['end_date']
                try:
                    async with semaphore:
                        await self.process_symbol(
                            symbol, start_date, end_date, session
                        )
                except Exception as e:
                    logger.error(f"处理 {symbol} 失败: {e}")
                finally:
                    processed += 1
                    if processed%10==0:
                        logger.info(f"{self.__class__.__name__} [{processed}/{total}] 完成 {symbol}")
            tasks = [process_with_semaphore(task) for task in self.tasks]
            await asyncio.gather(*tasks)
        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")
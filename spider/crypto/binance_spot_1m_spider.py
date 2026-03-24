# spider/crypto/crypto_binance_spot_1m_spider.py
import asyncio
import aiohttp
import aiofiles
import pandas as pd
import zipfile
import logging
import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from ..base_spider import BaseSpider
from core.storage import save_dataframe, load_dataframe
from core.config import DATA_PATH, MAX_CONCURRENCY
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)

# S3 API 命名空间
NS = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}
BASE_S3_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
START_DATE_DEFAULT = datetime(2017, 8, 17)   # 数据最早起始日


@task(description= "获取币安现货1分钟K线数据（日粒度ZIP包）")
class CryptoBinanceSpot1mKlinesSpider(BaseSpider):
    resource = "spot_binance"
    table_name = "spot_kline_1m"
    factor_table_name = None      # 该资源无因子表
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
        time_test = pd.to_datetime(df['open_time'][0] // 1000,unit='s')
        if time_test > pd.to_datetime("1980-01-01"):
            df['date'] = pd.to_datetime(df['open_time'] // 1000,unit='s')
        else:
            df['date'] = pd.to_datetime(df['open_time'],unit='s')
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
                    logger.warning(f"下载失败 {r.status_code}: {url}")
        except Exception as e:
            logger.error(f"下载出错 {url}: {e}")
        return False

    def _get_s3_xml_sync(self, prefix: str, marker: Optional[str] = None) -> str:
        """同步获取 S3 目录 XML 内容"""
        params = {"delimiter": "/", "prefix": prefix}
        if marker:
            params["marker"] = marker
        resp = requests.get(BASE_S3_URL, params=params, timeout=30)
        resp.raise_for_status()
        return resp.text

    def _get_zip_keys_for_symbol_sync(self, symbol: str) -> List[str]:
        """同步获取指定 symbol 的所有 ZIP 文件 Key"""
        prefix = f"data/spot/daily/klines/{symbol}/1m/"
        all_keys = []
        marker = None
        while True:
            xml_text = proxy_pool(self._get_s3_xml_sync,prefix, marker)
            root = ET.fromstring(xml_text)
            # 提取本页所有 Contents 的 Key
            checksum_key = None
            for content in root.findall('s3:Contents', NS):
                key_elem = content.find('s3:Key', NS)
                if key_elem is not None:
                    key = key_elem.text
                    if key.endswith('.zip'):
                        all_keys.append(key)
                    elif key.endswith('.CHECKSUM'):
                        checksum_key = key
            # 分页处理：使用最后一个 .CHECKSUM 作为下一页 marker
            is_truncated = root.find('s3:IsTruncated', NS)
            if is_truncated is not None and is_truncated.text == 'true':
                if checksum_key:
                    marker = checksum_key
                    logger.info(f"继续获取 {symbol} 列表，marker={marker}")
                    continue
                else:
                    logger.warning(f"{symbol} 列表截断但无 .CHECKSUM，停止分页")
                    break
            else:
                break
        return all_keys

    # ---------- 数据库最新日期查询 ----------
    def _get_latest_date(self, symbol: str) -> Optional[datetime]:
        """查询数据库中该 symbol 的最新日期"""
        sql = f"SELECT MAX(date) as latest FROM {self.table_name} WHERE symbol = '{symbol}'"
        try:
            df = load_dataframe(sql, db=self.market)
            if not df.empty and df.iloc[0]['latest'] is not pd.NaT:
                return pd.to_datetime(df.iloc[0]['latest']).to_pydatetime()
        except Exception as e:
            logger.error(f"查询 {symbol} 最新日期失败: {e}")
        return None

    # ---------- 数据检查与任务调整 ----------
    def check(self):
        """不调用父类 check，独立实现退市检测和起始日期调整"""
        if not self.tasks:
            logger.info("无任务，跳过 check")
            return

        yesterday = datetime.now() - timedelta(days=1)
        new_tasks = []

        for task in self.tasks:
            symbol = task['symbol']
            # 1. 检查昨日文件是否存在（退市检测）
            date_str = yesterday.strftime("%Y-%m-%d")
            url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1m/{symbol}-1m-{date_str}.zip"
            try:
                status = proxy_pool(self._head_request_sync, url)
                if status != 200:
                    logger.info(f"{symbol} 昨日文件不存在，视为退市，移除任务")
                    continue
            except Exception as e:
                logger.error(f"检查 {symbol} 昨日文件失败: {e}")
                continue

            # 2. 昨日文件存在，查询数据库最新日期
            latest = self._get_latest_date(symbol)
            if latest is None or latest < yesterday:
                # 数据缺失或未到昨日，保留任务，调整起始日期
                if latest is None:
                    start = START_DATE_DEFAULT
                else:
                    # 起始日期设为最新日期当日（重新抓取该日及以后）
                    start = latest
                new_tasks.append({
                    'symbol': symbol,
                    'market': self.market,
                    'start_date': start,
                    'end_date': yesterday
                })
                logger.info(f"{symbol} 保留任务，起始日期 {start.strftime('%Y-%m-%d')} 至 {yesterday.strftime('%Y-%m-%d')}")
            else:
                logger.info(f"{symbol} 数据已完整到昨日，移除任务")

        self.tasks = new_tasks
        logger.info(f"check 后剩余 {len(self.tasks)} 个任务")

    async def process_symbol(self, symbol: str, start_date: datetime, end_date: datetime,
                            session: aiohttp.ClientSession, progress=None, task_id=None):
        # 1. 获取该 symbol 所有存在的 ZIP 文件 Key
        try:
            keys = await asyncio.to_thread(self._get_zip_keys_for_symbol_sync, symbol)
        except Exception as e:
            logger.error(f"获取 {symbol} 文件列表失败: {e}")
            return

        # 提取日期集合
        existing_dates = set()
        for key in keys:
            parts = key.split('/')[-1].split('-')
            if len(parts) >= 3:
                try:
                    date_str = parts[-3] + '-' + parts[-2] + '-' + parts[-1].replace('.zip', '')
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                    existing_dates.add(date_obj.date())
                except:
                    pass

        # 2. 构建需要处理的日期列表
        current = start_date
        one_day = timedelta(days=1)
        dates_to_process = []
        while current <= end_date:
            if current.date() in existing_dates:
                dates_to_process.append(current)
            current += one_day

        if not dates_to_process:
            logger.info(f"{symbol} 无新数据需要处理")
            return

        # 3. 并发控制
        max_concurrent = 5  # 每个 symbol 内部最多同时下载5个zip
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_one_date(date_obj: datetime):
            async with semaphore:
                date_str = date_obj.strftime("%Y-%m-%d")
                filename = f"{symbol}-1m-{date_str}.zip"
                url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1m/{filename}"
                local_path = os.path.join(self.temp_dir, filename)

                try:
                    # 下载 ZIP（通过代理池在线程池中执行）
                    success = await asyncio.to_thread(proxy_pool, self._download_zip_sync, url, local_path)
                    if not success:
                        logger.warning(f"{symbol} {date_str} 下载失败，跳过")
                        return
                except Exception as e:
                    logger.error(f"{symbol} {date_str} 下载异常: {e}")
                    return

                # 处理 ZIP
                try:
                    with zipfile.ZipFile(local_path, 'r') as zf:
                        csv_files = [f for f in zf.namelist() if f.endswith('.csv')]
                        if csv_files:
                            with zf.open(csv_files[0]) as f:
                                df = pd.read_csv(f, header=None, names=self.column_names)
                    if df is not None and not df.empty:
                        df = self._rename_columns(df, symbol)
                        save_dataframe(
                            df,
                            table_name=self.table_name,
                            db=self.market,
                            primary_key=["symbol", "date"]
                        )
                        logger.info(f"{symbol} {date_str} 数据已保存，共 {len(df)} 条")
                except Exception as e:
                    logger.error(f"{symbol} {date_str} 处理 ZIP 失败: {e}")
                finally:
                    if os.path.exists(local_path):
                        os.remove(local_path)

        # 4. 并发执行所有日期的处理
        tasks = [process_one_date(date) for date in dates_to_process]
        await asyncio.gather(*tasks)

        logger.info(f"{symbol} 处理完成，共处理 {len(dates_to_process)} 个日期")
        
    # ---------- 主运行方法 ----------
    async def run(self, progress=None, task_id=None):
        if not self.tasks:
            logger.info("无任务，退出")
            return

        total = len(self.tasks)
        if progress and task_id is not None:
            progress.update(task_id, total=total)

        conn = aiohttp.TCPConnector(limit=10)
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

        async with aiohttp.ClientSession(connector=conn) as session:
            async def process_with_semaphore(task):
                symbol = task['symbol']
                start_date = task['start_date']
                end_date = task['end_date']
                try:
                    async with semaphore:
                        await self.process_symbol(
                            symbol, start_date, end_date, session,
                            progress=progress, task_id=task_id
                        )
                except Exception as e:
                    logger.error(f"处理 {symbol} 失败: {e}")
                finally:
                    if progress and task_id is not None:
                        progress.update(task_id, advance=1)

            tasks = [process_with_semaphore(task) for task in self.tasks]
            await asyncio.gather(*tasks)

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")
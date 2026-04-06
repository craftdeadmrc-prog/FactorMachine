import logging
import pandas as pd
import akshare as ak
from core.storage import save_dataframe, load_dataframe
from core.proxy import proxy_pool
import asyncio

logger = logging.getLogger(__name__)

# 全局变量，用于单例模式
_init_task = None
_init_lock = asyncio.Lock()

async def _fetch_ashare_symbols_async():
    """异步获取A股代码列表（沪市+深市），并直接保存到symbols表"""
    def sync_fetch():
        symbols = []
        # 沪市主板A股 + 科创板
        for board in ["主板A股", "科创板"]:
            try:
                df_sh = ak.stock_info_sh_name_code(symbol=board)
                if df_sh is not None and not df_sh.empty:
                    for _, row in df_sh.iterrows():
                        symbols.append({
                            'market': 'sh',
                            'symbol': row['证券代码'],
                            'short_name': row['证券简称'],
                            'date': pd.to_datetime(row['上市日期']) if pd.notna(row['上市日期']) else None
                        })
            except Exception as e:
                logger.error(f"Failed to fetch SH {board}: {e}")
        # 深市A股列表
        try:
            df_sz = ak.stock_info_sz_name_code(symbol="A股列表")
            if df_sz is not None and not df_sz.empty:
                for _, row in df_sz.iterrows():
                    symbols.append({
                        'market': 'sz',
                        'symbol': row['A股代码'],
                        'short_name': row['A股简称'],
                        'date': pd.to_datetime(row['A股上市日期']) if pd.notna(row['A股上市日期']) else None
                    })
        except Exception as e:
            logger.error(f"Failed to fetch SZ A-shares: {e}")
        return symbols

    symbols_list = await asyncio.to_thread(sync_fetch)
    if symbols_list:
        await asyncio.to_thread(
            save_dataframe,
            pd.DataFrame(symbols_list),
            table_name='symbols',
            db='ashare',
            primary_key=['market', 'symbol']
        )
        logger.info(f"Stored {len(symbols_list)} symbols for ashare.")
    else:
        logger.warning("No ashare symbols fetched.")

async def _fetch_fund_symbols_async():
    """
    异步获取基金代码列表，并同时将日线数据写入 kline_1d 表。
    每处理完一个基金，立即将其基本信息写入 symbols 表。
    """
    # 1. 获取基金列表（同步，用 to_thread 包装）
    def get_fund_list():
        symbols = []
        for fund_type in ['ETF基金', 'LOF基金']:
            df_fund = ak.fund_etf_category_sina(symbol=fund_type)
            if df_fund is not None and not df_fund.empty:
                for _, row in df_fund.iterrows():
                    raw_code = row["代码"]   # 例如 "sh510050"
                    name = row["名称"]
                    symbols.append({
                        'market': raw_code[:2],
                        'symbol': raw_code[2:],
                        'short_name': name,
                        'date': None
                    })
        return symbols

    try:
        fund_list = await asyncio.to_thread(get_fund_list)
    except Exception as e:
        logger.error(f"Failed to fetch fund list: {e}")
        return

    if not fund_list:
        logger.warning("No funds fetched.")
        return

    # 2. 并发处理每个基金
    async def process_one_fund(item):
        market = item['market']
        symbol = item['symbol']
        code = f"{market}{symbol}"

        # 获取日线数据并保存
        def fetch_and_save_daily():
            try:
                df = proxy_pool(ak.fund_etf_hist_sina, symbol=code)
                if df is None or df.empty:
                    logger.warning(f"ETF {code} 返回空数据")
                    return None
                # 清洗
                if "prevclose" in df.columns:
                    df.drop(columns=["prevclose"], inplace=True)
                df["symbol"] = symbol
                df["market"] = market  # 统一市场标识为 fund
                df["volume"] = df["volume"]*100
                df["date"] = pd.to_datetime(df["date"])
                # 写入日线表
                save_dataframe(df, table_name="kline_1d", db="fund", primary_key=["symbol", "date"])
                # 返回最早日期作为上市日期
                return df['date'].min()
            except Exception as e:
                logger.warning(f"处理基金 {code} 失败: {e}")
                return None

        listing_date = await asyncio.to_thread(fetch_and_save_daily)
        if listing_date is not None:
            item['date'] = pd.to_datetime(listing_date)

        # 立即写入 symbols 表
        try:
            await asyncio.to_thread(
                save_dataframe,
                pd.DataFrame([item]),
                table_name='symbols',
                db='fund',
                primary_key=['market', 'symbol']
            )
            logger.info(f"基金 {symbol} 信息已写入 symbols 表")
        except Exception as e:
            logger.warning(f"写入基金 {symbol} 到 symbols 表失败: {e}")

    # 并发执行所有基金的处理
    tasks = [asyncio.create_task(process_one_fund(item)) for item in fund_list]
    await asyncio.gather(*tasks, return_exceptions=True)

async def _fetch_crypto_symbols_async():
    """
    异步获取加密货币代码列表，并过滤退市及上市不足一年的品种。
    每处理完一个 symbol，立即将其信息写入 symbols 表。
    """
    import requests
    import xml.etree.ElementTree as ET

    NS = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}
    BASE_S3_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"

    def get_raw_symbols_sync():
        """同步获取所有原始 symbol 列表"""
        symbols = []
        prefix = "data/spot/daily/klines/"
        delimiter = "/"
        next_marker = None
        namespaces = {'ns': 'http://s3.amazonaws.com/doc/2006-03-01/'}
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0'}

        while True:
            params = {'delimiter': delimiter, 'prefix': prefix}
            if next_marker:
                params['marker'] = next_marker
            response = requests.get(BASE_S3_URL, params=params, headers=headers, timeout=30)
            if response.status_code != 200:
                raise Exception(f"Request failed with status {response.status_code}")
            root = ET.fromstring(response.text)
            for common_prefix in root.findall('.//ns:CommonPrefixes', namespaces):
                prefix_elem = common_prefix.find('ns:Prefix', namespaces)
                if prefix_elem is not None and prefix_elem.text:
                    prefix_text = prefix_elem.text
                    symbol = prefix_text.split('/')[-2]
                    if symbol.endswith('USDT') and any(c.isalpha() for c in symbol[:-4]):
                        if len(symbol.split("USDT")[0])<=4:
                            symbols.append(symbol)
            is_truncated = root.find('.//ns:IsTruncated', namespaces)
            next_marker_elem = root.find('.//ns:NextMarker', namespaces)
            if is_truncated is not None and is_truncated.text == 'true' and next_marker_elem is not None:
                next_marker = next_marker_elem.text
            else:
                break
        return list(set(symbols))

    # 获取原始 symbol 列表
    try:
        raw_symbols = await asyncio.to_thread(proxy_pool,get_raw_symbols_sync)
    except Exception as e:
        logger.error(f"Failed to fetch crypto symbols: {e}")
        return

    if not raw_symbols:
        logger.warning("No crypto symbols fetched.")
        return

    # 并发处理每个 symbol
    async def process_one_crypto(symbol):
        # 1. 退市检测
        check_date = pd.Timestamp.now().date() - pd.DateOffset(days=2)
        date_str = check_date.strftime("%Y-%m-%d")
        url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1m/{symbol}-1m-{date_str}.zip"

        def head_check():
            try:
                resp = proxy_pool(lambda u: requests.head(u, timeout=10), url)
                return resp.status_code
            except Exception:
                return 500

        status = await asyncio.to_thread(proxy_pool,head_check)
        if status != 200:
            logger.info(f"{symbol} 前日文件不存在，视为退市，跳过")
            return None

        # 2. 获取上市日期（最早 zip 文件日期）
        def get_first_zip_key():
            prefix = f"data/spot/daily/klines/{symbol}/1m/"
            params = {'delimiter': '/', 'prefix': prefix, 'max-keys': 1}
            try:
                xml_text = proxy_pool(
                    lambda p, m=None: requests.get(BASE_S3_URL, params=p, timeout=30).text,
                    params
                )
                root = ET.fromstring(xml_text)
                for content in root.findall('s3:Contents', NS):
                    key_elem = content.find('s3:Key', NS)
                    if key_elem is not None:
                        key = key_elem.text
                        if key.endswith('.zip'):
                            return key
            except Exception as e:
                logger.warning(f"获取 {symbol} 首个 zip key 失败: {e}")
            return None

        first_key = await asyncio.to_thread(proxy_pool,get_first_zip_key)
        if not first_key:
            logger.warning(f"{symbol} 无任何 zip 文件，跳过")
            return None

        filename = first_key.split('/')[-1]
        try:
            date_str = filename.split('-')[-3] + '-' + filename.split('-')[-2] + '-' + filename.split('-')[-1].replace('.zip', '')
            date = pd.to_datetime(date_str)
        except Exception as e:
            logger.warning(f"{symbol} 解析上市日期失败: {e}")
            return None
        # 3. 过滤上市不足一年的品种
        if (pd.Timestamp.now().date() - date.date()).days < 365*2:
            logger.info(f"{symbol} 上市不足两年，跳过")
            return None

        item = {
            'market': 'binance',
            'symbol': symbol,
            'short_name': symbol[:-4],
            'date': date
        }
        # 立即写入 symbols 表
        try:
            await asyncio.to_thread(
                save_dataframe,
                pd.DataFrame([item]),
                table_name='symbols',
                db='crypto',
                primary_key=['market', 'symbol']
            )
            logger.info(f"加密货币 {symbol} 信息已写入 symbols 表")
        except Exception as e:
            logger.warning(f"写入加密货币 {symbol} 到 symbols 表失败: {e}")

    tasks = [asyncio.create_task(process_one_crypto(sym)) for sym in raw_symbols]
    await asyncio.gather(*tasks, return_exceptions=True)

async def _process_market(market, fetch_func, update):
    """
    处理单个市场：获取数据并存储。
    如果 update=False 且数据库中已有完整数据，则跳过整个市场（简单整体判断）。
    """
    if not update:
        try:
            # 检查 symbols 表是否已存在数据且完整（这里简单判断非空即视为完整）
            df_existing = await asyncio.to_thread(
                load_dataframe,
                f"SELECT market, symbol FROM symbols",
                db=market
            )
            if not df_existing.empty and not df_existing.isna().any().any():
                logger.info(f"Symbols for {market} already exist and are complete. Skipping.")
                return
        except Exception as e:
            logger.warning(f"Failed to load existing symbols for {market}: {e}")

    logger.info(f"Fetching symbols for {market}...")
    # 异步函数，内部已处理数据库写入
    await fetch_func()

async def init(update=False):
    """
    异步初始化所有市场的代码列表，支持单例模式和强制更新。

    Args:
        update (bool): 默认为 False。若为 True，则强制重新获取所有市场数据（忽略已有数据）。

    Returns:
        asyncio.Task: 初始化任务对象。可通过 task.done() 检查是否完成，
                      或 await task 等待初始化完成。
    """
    global _init_task, _init_lock

    async with _init_lock:
        if _init_task is not None and not update:
            return _init_task

        if _init_task is not None and not _init_task.done():
            _init_task.cancel()
            try:
                await _init_task
            except asyncio.CancelledError:
                pass

        async def _init_impl():
            # 定义各市场的处理函数（全部异步）
            markets = [
                ('ashare', _fetch_ashare_symbols_async),
                ('fund', _fetch_fund_symbols_async),
                ('crypto', _fetch_crypto_symbols_async),
            ]
            tasks = [_process_market(market, func, update) for market, func in markets]
            await asyncio.gather(*tasks, return_exceptions=True)

        _init_task = asyncio.create_task(_init_impl())
        return _init_task

# 演示外部用法,比如让web面板调用
if __name__ == "__main__":
    import asyncio

    async def main():
        # 获取初始化任务（立即返回，不会阻塞）
        init_task = await init(update=False)

        # 检查是否已完成
        if init_task.done():
            print("初始化已完成")
        else:
            print("初始化未完成")

        # 如果需要等待初始化完成
        await init_task
        print("初始化完成")

    asyncio.run(main())
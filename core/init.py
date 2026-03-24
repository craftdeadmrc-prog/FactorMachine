import logging
import pandas as pd
import akshare as ak
from core.storage import save_dataframe, load_dataframe
from core.proxy import proxy_pool
from core.config import MAX_CONCURRENCY
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)

# 全局变量，用于单例模式
_init_task = None
_init_lock = asyncio.Lock()

def _fetch_ashare_symbols():
    """获取A股代码列表（沪市+深市）"""
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

def _fetch_fund_symbols():
    """获取基金代码列表，并发获取上市日期，并将日线数据写入kline_daily表"""
    symbols = []
    try:
        for fund_type in ['ETF基金', 'LOF基金']:
            df_fund = ak.fund_etf_category_sina(symbol=fund_type)
            if df_fund is not None and not df_fund.empty:
                for _, row in df_fund.iterrows():
                    raw_code = row["代码"]   # 例如 "sh510050"
                    name = row["名称"]       # 基金名称
                    symbols.append({
                        'market': raw_code[:2],
                        'symbol': raw_code[2:],
                        'short_name': name,
                        'date': None          # 占位，后续填充
                    })
    except Exception as e:
        logger.error(f"Failed to fetch funds: {e}")
        return symbols

    # 并发获取每个基金的上市日期，并同时保存日线数据
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch_date(market, symbol):
        """获取日线数据，保存到kline_daily，返回最早日期"""
        code = f"{market}{symbol}"
        try:
            df = proxy_pool(ak.fund_etf_hist_sina, symbol=code)
            if df is None or df.empty:
                logger.warning(f"ETF {code} 返回空数据")
                return None

            # 数据清洗：与爬虫脚本保持一致
            if "prevclose" in df.columns:
                df.drop(columns=["prevclose"], inplace=True)
            df["symbol"] = symbol
            df["market"] = market          # 统一市场标识为 fund

            # 写入kline_daily表
            try:
                save_dataframe(
                    df,
                    table_name="kline_daily",
                    db="fund",          # 基类市场标识
                    primary_key=["symbol", "date"]
                )
                logger.info(f"ETF {code} 日线数据已保存，共 {len(df)} 条")
            except Exception as e:
                logger.warning(f"保存ETF {code} 日线数据失败: {e}")

            # 返回最早日期作为上市日期
            return df['date'].min()
        except Exception as e:
            logger.warning(f"获取ETF {code} 日线数据失败: {e}")
            return None

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
        future_to_idx = {}
        for idx, item in enumerate(symbols):
            future = executor.submit(fetch_date, item['market'], item['symbol'])
            future_to_idx[future] = idx

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                listing_date = future.result()
                if listing_date is not None:
                    symbols[idx]['date'] = listing_date
                # 否则保持 None
            except Exception as e:
                logger.warning(f"处理基金 {symbols[idx]['symbol']} 时发生错误: {e}")

    return symbols

def _fetch_crypto_symbols():
    """获取加密货币代码列表（通过代理池），并过滤退市及上市不足一年的品种"""
    import requests
    import xml.etree.ElementTree as ET
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor, as_completed

    NS = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}
    BASE_S3_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"

    def head_request_sync(url: str) -> int:
        """同步 HEAD 请求，返回状态码（通过代理池）"""
        resp = proxy_pool(lambda u: requests.head(u, timeout=10), url)
        return resp.status_code

    def get_first_zip_key_sync(symbol: str) -> str:
        """获取该 symbol 下最早的一个 zip 文件的 Key，若不存在则返回 None"""
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

    def process_symbol(symbol: str):
        """处理单个 symbol：退市检测 + 上市日期获取，返回包含 date 的字典或 None"""
        # 1. 退市检测：检查前日（今天-2天）文件是否存在
        check_date = datetime.now() - timedelta(days=2)
        date_str = check_date.strftime("%Y-%m-%d")
        url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1m/{symbol}-1m-{date_str}.zip"
        try:
            status = head_request_sync(url)
            if status != 200:
                logger.info(f"{symbol} 前日文件不存在，视为退市，跳过")
                return None
        except Exception as e:
            logger.warning(f"检查 {symbol} 退市失败: {e}")
            return None

        # 2. 获取上市日期（最早 zip 文件日期）
        first_key = get_first_zip_key_sync(symbol)
        if not first_key:
            logger.warning(f"{symbol} 无任何 zip 文件，跳过")
            return None

        # 解析日期：文件名格式 symbol-1m-YYYY-MM-DD.zip
        filename = first_key.split('/')[-1]
        try:
            date_str = filename.split('-')[-3] + '-' + filename.split('-')[-2] + '-' + filename.split('-')[-1].replace('.zip', '')
            listing_date = pd.to_datetime(date_str)
        except Exception as e:
            logger.warning(f"{symbol} 解析上市日期失败: {e}")
            return None

        # 3. 过滤上市不足一年的品种
        if (datetime.now() - listing_date).days < 365:
            logger.info(f"{symbol} 上市不足一年，跳过")
            return None
        return {
            'market': 'binance',
            'symbol': symbol,
            'date': listing_date
        }

    # 获取所有原始 symbol 列表
    symbols = []
    try:
        raw_symbols = proxy_pool(_fetch_crypto_symbols_from_binance)
    except Exception as e:
        logger.error(f"Failed to fetch crypto symbols: {e}")
        return symbols

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
        future_to_symbol = {executor.submit(process_symbol, sym): sym for sym in raw_symbols}
        for future in as_completed(future_to_symbol):
            try:
                result = future.result()
                if result:
                    symbols.append(result)
            except Exception as e:
                logger.warning(f"处理 {future_to_symbol[future]} 时发生异常: {e}")
    return symbols

def _fetch_crypto_symbols_from_binance():
    """从币安S3桶获取USDT交易对列表（原始函数）"""
    import requests
    import xml.etree.ElementTree as ET
    symbols = []
    base_url = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
    prefix = "data/spot/daily/klines/"
    delimiter = "/"
    next_marker = None
    namespaces = {'ns': 'http://s3.amazonaws.com/doc/2006-03-01/'}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0'}

    while True:
        params = {'delimiter': delimiter, 'prefix': prefix}
        if next_marker:
            params['marker'] = next_marker
        response = requests.get(base_url, params=params, headers=headers, timeout=30)
        if response.status_code != 200:
            raise Exception(f"Request failed with status {response.status_code}")
        root = ET.fromstring(response.text)
        for common_prefix in root.findall('.//ns:CommonPrefixes', namespaces):
            prefix_elem = common_prefix.find('ns:Prefix', namespaces)
            if prefix_elem is not None and prefix_elem.text:
                prefix_text = prefix_elem.text
                symbol = prefix_text.split('/')[-2]
                if symbol.endswith('USDT') and any(c.isalpha() for c in symbol[:-4]):
                    symbols.append(symbol)
        is_truncated = root.find('.//ns:IsTruncated', namespaces)
        next_marker_elem = root.find('.//ns:NextMarker', namespaces)
        if is_truncated is not None and is_truncated.text == 'true' and next_marker_elem is not None:
            next_marker = next_marker_elem.text
        else:
            break
    return list(set(symbols))

async def _process_market(market, fetch_func, update):
    """
    处理单个市场：获取数据并存储。
    如果 update=False 且数据库中已有完整数据，则跳过。
    """
    # 检查是否需要跳过（仅当 update=False 时）
    if not update:
        try:
            # 使用 to_thread 运行同步的数据库查询
            df = await asyncio.to_thread(
                load_dataframe,
                f"SELECT market, symbol FROM symbols",
                market=market
            )
            if not df.empty and not df.isna().any().any():
                logger.info(f"Symbols for {market} already exist and are complete. Skipping.")
                return
        except Exception as e:
            logger.warning(f"Failed to load existing symbols for {market}: {e}")

    logger.info(f"Fetching symbols for {market}...")
    # 使用 to_thread 运行同步的获取函数
    symbols_list = await asyncio.to_thread(fetch_func)
    if symbols_list:
        df_new = pd.DataFrame(symbols_list)
        # 存储数据（同样在线程中执行）
        await asyncio.to_thread(
            save_dataframe,
            df_new,
            table_name='symbols',
            market=market,
            primary_key=['market', 'symbol']
        )
        logger.info(f"Stored {len(symbols_list)} symbols for {market}.")
    else:
        logger.warning(f"No symbols fetched for {market}.")

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
        # 如果已有任务且不需要强制更新，直接返回现有任务
        if _init_task is not None and not update:
            return _init_task

        # 如果已有任务但需要强制更新，则取消现有任务（如果未完成）
        if _init_task is not None and not _init_task.done():
            _init_task.cancel()
            try:
                await _init_task
            except asyncio.CancelledError:
                pass

        # 创建新的初始化任务
        async def _init_impl():
            markets = [
                ('ashare', _fetch_ashare_symbols),
                ('fund', _fetch_fund_symbols),
                ('crypto', _fetch_crypto_symbols),
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

    # 运行异步主函数
    asyncio.run(main())
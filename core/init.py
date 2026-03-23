import logging
import pandas as pd
import akshare as ak
from core.storage import save_dataframe, load_dataframe
from core.proxy import proxy_pool
from datetime import datetime

logger = logging.getLogger(__name__)

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
                        'date': row['上市日期'] if pd.notna(row['上市日期']) else None
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
                    'date': row['A股上市日期'] if pd.notna(row['A股上市日期']) else None
                })
    except Exception as e:
        logger.error(f"Failed to fetch SZ A-shares: {e}")
    return symbols

def _fetch_fund_symbols():
    """获取基金代码列表"""
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
                        'short_name': name
                    })
    except Exception as e:
        logger.error(f"Failed to fetch funds: {e}")
    return symbols

def _fetch_crypto_symbols():
    """获取加密货币代码列表（通过代理池）"""
    symbols = []
    try:
        raw_symbols = proxy_pool(_fetch_crypto_symbols_from_binance)
        for sym in raw_symbols:
            symbols.append({
                'market': 'binance',
                'symbol': sym,
            })
    except Exception as e:
        logger.error(f"Failed to fetch crypto symbols: {e}")
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

def init():
    """
    初始化所有市场的代码列表并存入数据库。
    顺序遍历各市场，若数据库中该市场数据不存在或存在空值，则重新获取并存储。
    """
    # 先初始化交易日历（独立于符号获取）
    markets_func = {
        'ashare': _fetch_ashare_symbols,
        'fund': _fetch_fund_symbols,
        'crypto': _fetch_crypto_symbols
    }

    for market, fetch_func in markets_func.items():
        # 尝试从数据库加载该市场的 symbols 数据
        try:
            df = load_dataframe(
                # f"SELECT market, symbol, date FROM symbols",
                f"SELECT market, symbol FROM symbols",
                market=market
            )
        except Exception as e:
            df = pd.DataFrame()

        # 检查数据是否存在且完整（非空且无缺失值）
        if not df.empty and not df.isna().any().any():
            logger.info(f"Symbols for {market} already exist and are complete. Skipping.")
            continue

        logger.info(f"Fetching symbols for {market}...")
        symbols_list = fetch_func()
        if symbols_list:
            df_new = pd.DataFrame(symbols_list)
            # 存储时 market 参数为市场名（如 'ashare'），但表中 market 字段仍为 'sh'/'sz' 等
            save_dataframe(
                df_new,
                table_name='symbols',
                market=market,
                primary_key=['market', 'symbol']
            )
            logger.info(f"Stored {len(symbols_list)} symbols for {market}.")
        else:
            logger.warning(f"No symbols fetched for {market}.")

import pandas as pd
import logging

logger = logging.getLogger(__name__)

def aggregate_date_bar(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """
    根据时间间隔聚合 K 线数据 (Date Bar)
    
    Args:
        df: 原始数据 DataFrame，必须包含 date, open, high, low, close, volume, amount
        interval: 时间间隔，例如 '1d', '1w', '1m', '1h'
    
    Returns:
        聚合后的 DataFrame
    """
    if df.empty:
        return df

    # 确保日期是 datetime 类型且是索引
    df = df.copy()
    if 'date' not in df.columns:
        raise ValueError("DataFrame must contain 'date' column")
    
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)

    # 定义聚合规则
    # 开盘：取第一个
    # 最高：取最大值
    # 最低：取最小值
    # 收盘：取最后一个
    # 成交量/额：求和
    agg_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'amount': 'sum'
    }

    # 过滤掉不在 agg_dict 中的列（如果有）
    available_cols = {k: v for k, v in agg_dict.items() if k in df.columns}

    try:
        # 使用 resample 进行聚合
        # label='left' 和 closed='left' 确保周期开始时间对齐
        resampled = df.resample(interval, label='left', closed='left').agg(available_cols)
        
        # 去除可能产生的空行（如果某周期无数据）
        resampled.dropna(inplace=True)
        
        # 重置索引以便返回
        resampled.reset_index(inplace=True)
        
        return resampled
    except Exception as e:
        logger.error(f"Date bar aggregation failed for interval {interval}: {e}")
        raise
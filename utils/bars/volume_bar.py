import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

def aggregate_volume_bar(df: pd.DataFrame, threshold: float, value_col: str = 'volume') -> pd.DataFrame:
    """
    根据成交量或成交额阈值聚合 K 线数据 (Volume/Dollar Bar)
    
    原理：
    计算累积和，每当累积值超过设定的阈值时，视为一根 Bar 的结束。
    使用向量化操作 (cumsum + floor division) 来确定分组 ID，保证高性能。
    
    注意：
    在纯 Pandas 环境下，为了保证高性能，本实现不进行“单行拆分”。
    即：如果最后一笔数据导致总量超过阈值，该笔完整数据将归入当前 Bar，
    导致当前 Bar 的总量略大于阈值。这是在 Python 中平衡速度与精度的标准做法。
    若需要精确的“单行拆分”（如 tick 级别精确切分），通常需要使用 Numba 或 Cython。

    Args:
        df: 原始数据 DataFrame，必须包含 date, open, high, low, close, volume, amount
        threshold: 阈值（例如 1000 手，或 1,000,000 元）
        value_col: 用于聚合的列名，'volume' 或 'amount'
    
    Returns:
        聚合后的 DataFrame
    """
    if df.empty:
        return df

    if value_col not in df.columns:
        raise ValueError(f"Column '{value_col}' not found in DataFrame")

    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    
    # 1. 计算累积值
    # 使用 copy 避免 SettingWithCopyWarning
    cumsum_values = df[value_col].cumsum()
    
    # 2. 生成分组 ID
    # 算法：(cumsum - 1) // threshold
    # 解释：
    # - 假设 threshold = 1000。
    # - cumsum = 300  -> (299 // 1000) = 0
    # - cumsum = 700  -> (699 // 1000) = 0
    # - cumsum = 1200 -> (1199 // 1000) = 1 (达到阈值，进入下一组)
    # - 这样 0 组包含前几行数据，直到累积值突破 1000
    group_ids = np.floor((cumsum_values - 1) / threshold).astype(int)
    
    # 3. 将分组 ID 添加到 DataFrame
    df['vol_bar_group'] = group_ids
    
    # 4. 按分组进行聚合
    # 定义聚合规则
    agg_dict = {
        'date': ['first', 'last'], # 记录该 Bar 的开始和结束时间
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'amount': 'sum',
        value_col: 'sum' # 再次确认阈值列求和
    }

    # 过滤存在的列
    valid_agg = {k: v for k, v in agg_dict.items() if k in df.columns}
    
    try:
        resampled = df.groupby('vol_bar_group').agg(valid_agg)
        
        # 展平多级列索引
        resampled.columns = ['_'.join(col).strip('_') if isinstance(col, tuple) else col for col in resampled.columns.values]
        
        # 重命名列以匹配标准格式
        # 'date_first' 作为 Bar 的时间基准 (显示用)
        # 'date_last' 作为该 Bar 的结束时间
        resampled.rename(columns={
            'date_first': 'date',
            'date_last': 'end_date'
        }, inplace=True)
        
        # 如果没有 'end_date' (比如只有一行数据)，手动处理
        if 'date' not in resampled.columns:
             # 这种情况极少，除非输入数据为空
             pass
             
        # 清理辅助列（如果有）
        if f'{value_col}_sum' in resampled.columns:
            # 这里的 value_col_sum 实际上就是该 bar 的 total volume/amount
            pass

        # 重置索引
        resampled.reset_index(drop=True, inplace=True)
        
        return resampled
        
    except Exception as e:
        logger.error(f"Volume bar aggregation failed: {e}")
        raise
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

def get_time_bars(df: pd.DataFrame) -> pd.DataFrame:
    """
    Time Bar 逻辑：直接返回原数据，但统一格式，确保有 'ticks' 列（默认为1）
    """
    if df.empty:
        return df
    result = df.copy()
    # Time bar 默认每个 bar 消耗 1 个时间单位
    result['ticks'] = 1
    return result

def get_volume_bars(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """
    Volume Bar 逻辑：
    聚合数据直到累计成交量达到阈值。
    若某根 bar 超出阈值，剩余量计入下一根 bar。
    对于日K数据，拆分时无法精确拆分 OHLC，此处采用近似处理：
    价格使用当前 K 线的收盘价作为拆分点的开盘/收盘价。
    """
    if df.empty or threshold <= 0:
        return df

    bars = []
    # 缓存变量
    overflow_vol = 0.0
    # 上一次溢出部分的开盘价（如果没有溢出，则为 None）
    # 实际上，溢出的逻辑是：如果上一根 bar 没凑够，剩下的量留给下一根。
    # 这里我们维护一个 "构建中" 的 Bar 状态
    
    current_bar = {
        'volume': 0.0,
        'ticks': 0,
        'open': None,
        'high': -np.inf,
        'low': np.inf,
        'close': None,
        'date_start': None,
        'date_end': None
    }

    for _, row in df.iterrows():
        # 当前 K 线的数据
        tick_vol = row['volume']
        tick_open = row['open']
        tick_high = row['high']
        tick_low = row['low']
        tick_close = row['close']
        tick_date = row['date']

        # 如果当前 bar 还是空的，初始化 Open 和 Date
        if current_bar['open'] is None:
            current_bar['open'] = tick_open
            current_bar['date_start'] = tick_date

        # 更新 High, Low
        current_bar['high'] = max(current_bar['high'], tick_high)
        current_bar['low'] = min(current_bar['low'], tick_low)
        current_bar['close'] = tick_close
        current_bar['date_end'] = tick_date
        current_bar['ticks'] += 1

        # 计算当前 K 线贡献的量
        # 先填满当前 bar 剩余的缺口
        needed = threshold - current_bar['volume']
        
        if tick_vol < needed:
            # 整根 K 线都填不满当前 bar，全部加入
            current_bar['volume'] += tick_vol
        else:
            # 当前 K 线足以填满当前 bar，并可能有溢出
            # 1. 完成当前 bar
            current_bar['volume'] = threshold # 严格按照阈值设定
            
            # 对于日K这种粗粒度数据，价格拆分是近似的：
            # 我们假设填满阈值的那部分价格就是当天的收盘价（或者可以使用 VWAP 思想，但这里简化）
            # 实际上，为了保持 OHLC 的连贯性，这里如果不拆分 K 线本身，
            # 严谨的做法是：Bar 的 Volume 取阈值，OHLC 取当前累计时间段的值。
            # 这里保留累计的 OHLC。
            
            bars.append(current_bar.copy())
            
            # 2. 处理溢出，开始下一个 bar
            overflow_vol = tick_vol - needed
            
            # 重置 current_bar
            current_bar = {
                'volume': overflow_vol,
                'ticks': 0, # 溢出的量算作下一个 bar 的开始，但不计 tick 数？
                            # 这里逻辑比较微妙。如果溢出的量属于同一个 K 线，
                            # 严谨的 tick count 应该是连续的。
                            # 简单起见：我们只计算消耗的完整 K 线数作为 ticks，
                            # 或者假设溢出部分已经隐含在下一个 bar 的初始状态中。
                            # 题目要求"拼凑出各个bar消耗的时间间隔数"，
                            # 所以 ticks 记录的是聚合了几根原始 K 线。
                'open': tick_close, # 溢出部分的开盘价沿用当天的收盘价
                'high': tick_high,  # 重新开始计算 High Low
                'low': tick_low,
                'close': tick_close,
                'date_start': tick_date, # 虽然是同一天，但逻辑上属于新 bar
                'date_end': tick_date
            }
            
            # 如果溢出量本身已经超过阈值（极端情况），循环处理
            # 这里简化处理：溢出量留给下一次循环累加，不在此处递归生成 bar
            # 因为我们在同一天内无法拆分时间戳，所以如果 overflow >= threshold，
            # 理论上应该生成多个 bar，但数据粒度不支持。
            # 我们将在下一次循环（下一天）时优先看到这个 overflow。
            # 这里我们强制 current_bar['ticks'] = 0，因为这部分量还没"消耗"新的一天。

    # 循环结束后，处理剩余的未满 bar
    if current_bar['volume'] > 0:
        bars.append(current_bar)

    if not bars:
        return pd.DataFrame()

    result_df = pd.DataFrame(bars)
    
    # 生成展示区间标签 (Volume Interval)
    # 比如 0-1000, 1000-2000
    result_df['vol_start'] = (result_df.index * threshold).astype(int)
    result_df['vol_end'] = ((result_df.index + 1) * threshold).astype(int)
    result_df['date'] = result_df['vol_start'].astype(str) + '-' + result_df['vol_end'].astype(str)
    
    # 调整列顺序，保留原有字段
    cols = ['date', 'open', 'high', 'low', 'close', 'volume', 'ticks']
    return result_df[cols]

def get_cusum_bars(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """
    CUSUM Bar 逻辑：
    监控价格变动，当累积变动（正向或负向）超过阈值时触发采样。
    threshold: 价格变动百分比，例如 0.02 代表 2%
    """
    if df.empty or threshold <= 0:
        return df

    # 计算对数收益率
    df = df.copy()
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1)).fillna(0)
    
    bars = []
    
    # 初始化 CUSUM 变量
    s_pos = 0.0
    s_neg = 0.0
    
    # 当前聚合状态
    current_bar = {
        'open': None,
        'high': -np.inf,
        'low': np.inf,
        'close': None,
        'volume': 0.0,
        'date_start': None,
        'date_end': None,
        'ticks': 0
    }
    
    for idx, row in df.iterrows():
        r_t = row['log_ret']
        
        # 如果是新 bar 的开始，初始化状态
        if current_bar['open'] is None:
            current_bar['open'] = row['open']
            current_bar['date_start'] = row['date']
        
        # 更新 Bar 内部状态
        current_bar['high'] = max(current_bar['high'], row['high'])
        current_bar['low'] = min(current_bar['low'], row['low'])
        current_bar['close'] = row['close']
        current_bar['volume'] += row['volume']
        current_bar['date_end'] = row['date']
        current_bar['ticks'] += 1
        
        # 更新 CUSUM 统计量
        s_pos = max(0, s_pos + r_t)
        s_neg = min(0, s_neg + r_t)
        
        # 检查是否触发阈值
        # 注意：阈值是针对 r_t 的累积和，即累积收益率
        if s_pos > threshold or s_neg < -threshold:
            # 触发采样，保存 Bar
            bars.append(current_bar.copy())
            
            # 重置状态
            s_pos = 0.0
            s_neg = 0.0
            
            current_bar = {
                'open': None, 'high': -np.inf, 'low': np.inf, 
                'close': None, 'volume': 0.0, 
                'date_start': None, 'date_end': None, 'ticks': 0
            }
            
    # 处理剩余数据
    if current_bar['ticks'] > 0:
        bars.append(current_bar)

    if not bars:
        return pd.DataFrame()

    result_df = pd.DataFrame(bars)
    # CUSUM Bar 的展示区间可以用简单的序号或者起止日期
    # 这里为了统一，将 date 设为起止日期范围
    result_df['date'] = result_df['date_start'].astype(str) + ' ~ ' + result_df['date_end'].astype(str)
    
    cols = ['date', 'open', 'high', 'low', 'close', 'volume', 'ticks']
    return result_df[cols]

def generate_bars(df: pd.DataFrame, bar_type: str = 'time', threshold: float = None) -> pd.DataFrame:
    """
    统一入口函数
    
    Args:
        df: 原始 Time Bar 数据
        bar_type: 'time', 'volume', 'cusum'
        threshold: volume 为成交量阈值，cusum 为价格变动比例阈值
    
    Returns:
        转换后的 DataFrame，统一包含 'date', 'open', 'high', 'low', 'close', 'volume', 'ticks' 列
    """
    if df.empty:
        return df
        
    if bar_type == 'time':
        return get_time_bars(df)
    elif bar_type == 'volume':
        if threshold is None or threshold <= 0:
            logger.warning("Volume bar threshold invalid, defaulting to 1000000")
            threshold = 1_000_000
        return get_volume_bars(df, threshold)
    elif bar_type == 'cusum':
        if threshold is None or threshold <= 0:
            logger.warning("CUSUM bar threshold invalid, defaulting to 0.02")
            threshold = 0.02
        return get_cusum_bars(df, threshold)
    else:
        return get_time_bars(df)
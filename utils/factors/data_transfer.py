# utils/factors/data_transfer.py
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Union

def prepare_input_dict(
    df: pd.DataFrame,
    required_cols: Optional[List[str]] = None,
    stock_id: Optional[str] = None,
    dtype: np.dtype = np.float32
) -> Dict[str, np.ndarray]:
    """
    将单只股票的 DataFrame 转换为 KunQuant 输入字典。
    
    参数:
        df: 包含 OHLCV 数据的 DataFrame，必须包含 required_cols 中的列。
        required_cols: 需要的列名列表，默认为 ['open', 'high', 'low', 'close', 'volume', 'amount']。
        stock_id: 可选，用于标识股票，但输出形状仍为 (time, 1)。
        dtype: 输出数组的数据类型，默认为 float32。
    
    返回:
        字典，键为列名，值为形状为 (time, 1) 的 numpy 数组。
    
    示例:
        >>> import pandas as pd
        >>> df = pd.read_csv('data.csv')
        >>> input_dict = prepare_input_dict(df)
        >>> print(input_dict['close'].shape)  # (100, 1)
    """
    if required_cols is None:
        required_cols = ['open', 'high', 'low', 'close', 'volume', 'amount']
    
    # 检查列是否存在
    missing = set(required_cols) - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame 缺少必要的列: {missing}")
    
    # 确保数据按日期排序（假设存在 'date' 列）
    if 'date' in df.columns:
        df = df.sort_values('date')
    
    num_time = len(df)
    num_stocks = 1
    
    input_dict = {}
    for col in required_cols:
        # 提取列数据并转为指定类型
        arr = df[col].values.astype(dtype)
        # 重塑为 (time, stocks)
        input_dict[col] = arr.reshape(num_time, num_stocks)
    
    return input_dict


def prepare_batch_input_dict(
    dfs: List[pd.DataFrame],
    required_cols: Optional[List[str]] = None,
    stock_ids: Optional[List[str]] = None,
    dtype: np.dtype = np.float32
) -> Dict[str, np.ndarray]:
    """
    将多只股票的 DataFrame 列表合并为 KunQuant 输入字典。
    
    参数:
        dfs: 多个 DataFrame 的列表，每个代表一只股票的数据。
        required_cols: 需要的列名列表，默认为 ['open', 'high', 'low', 'close', 'volume', 'amount']。
        stock_ids: 可选，股票标识列表，仅用于对齐长度检查。
        dtype: 输出数组的数据类型，默认为 float32。
    
    返回:
        字典，键为列名，值为形状为 (time, stocks) 的 numpy 数组。
        注意：所有股票的时间序列长度必须一致，否则会抛出异常。
    
    示例:
        >>> df1 = pd.read_csv('stock1.csv')
        >>> df2 = pd.read_csv('stock2.csv')
        >>> input_dict = prepare_batch_input_dict([df1, df2])
        >>> print(input_dict['close'].shape)  # (100, 2)
    """
    if required_cols is None:
        required_cols = ['open', 'high', 'low', 'close', 'volume', 'amount']
    
    if not dfs:
        raise ValueError("输入的 DataFrame 列表为空")
    
    # 检查所有 DataFrame 的行数是否一致
    time_lengths = [len(df) for df in dfs]
    if len(set(time_lengths)) != 1:
        raise ValueError(f"所有股票的时间长度必须一致，当前长度: {time_lengths}")
    num_time = time_lengths[0]
    num_stocks = len(dfs)
    
    # 初始化字典，每个列对应一个 (time, stocks) 的数组
    input_dict = {col: np.empty((num_time, num_stocks), dtype=dtype) for col in required_cols}
    
    for stock_idx, df in enumerate(dfs):
        # 检查必要列是否存在
        missing = set(required_cols) - set(df.columns)
        if missing:
            raise ValueError(f"股票 {stock_idx} 缺少列: {missing}")
        
        # 确保数据按日期排序（假设存在 'date' 列）
        if 'date' in df.columns:
            df = df.sort_values('date')
        
        # 提取每列数据
        for col in required_cols:
            arr = df[col].values.astype(dtype)
            # 按股票填充到对应列
            input_dict[col][:, stock_idx] = arr
    
    return input_dict
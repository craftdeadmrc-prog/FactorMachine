"""
波动率因子
计算20日滚动波动率
"""
import pandas as pd
import numpy as np

dependencies = ["code", "return_ratio", "date"]

provided_columns = ["volatility_20"]

description = {
    "name": {
        "中文名": "20日波动率",
        "英文名": "20-Day Volatility",
        "变量名": "volatility_20"
    },
    "info": {
        "介绍": "20日滚动波动率，计算过去20个交易日收益率的标准差，反映短期价格波动性",
        "日期": "",
        "计算公式": "volatility_20 = std(return_ratio).rolling(20)"
    }
}

def compute_factor(df):
    # 20日滚动波动率
    df['volatility_20'] = df.groupby('code')['return_ratio'].transform(
        lambda x: x.rolling(window=20, min_periods=2).std()
    )
    
    return df
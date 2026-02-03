"""
波动率因子
计算60日滚动波动率
"""
import pandas as pd
import numpy as np

dependencies = ["code", "return_ratio", "date"]

provided_columns = ["volatility_60"]

description = {
    "name": {
        "中文名": "60日波动率",
        "英文名": "60-Day Volatility",
        "变量名": "volatility_60"
    },
    "info": {
        "介绍": "60日滚动波动率，计算过去60个交易日收益率的标准差，反映中期价格波动性",
        "日期": "",
        "计算公式": "volatility_60 = std(return_ratio).rolling(60)"
    }
}

def compute_factor(df):
    # 60日滚动波动率
    df['volatility_60'] = df.groupby('code')['return_ratio'].transform(
        lambda x: x.rolling(window=60, min_periods=2).std()
    )
    
    return df
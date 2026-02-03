"""
成交量比率因子
计算成交量比率（当日成交量/20日平均成交量）
"""
import pandas as pd
import numpy as np

dependencies = ["code", "volume", "volume_ma_20", "date"]

provided_columns = ["volume_ratio"]

description = {
    "name": {
        "中文名": "成交量比率",
        "英文名": "Volume Ratio",
        "变量名": "volume_ratio"
    },
    "info": {
        "介绍": "成交量比率，计算当日成交量相对于20日平均成交量的比率，反映交易活跃度的变化",
        "日期": "",
        "计算公式": "volume_ratio = volume / volume_ma_20"
    }
}

def compute_factor(df):
    # 成交量比率
    df['volume_ratio'] = df['volume'] / df['volume_ma_20']
    
    # 处理异常值
    df['volume_ratio'] = df['volume_ratio'].replace([np.inf, -np.inf], np.nan)
    
    return df
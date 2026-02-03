"""
收盘价位置因子
计算收盘价在20日内的位置
"""
import pandas as pd
import numpy as np

dependencies = ["code", "close", "high", "low", "date"]

provided_columns = ["close_position_20"]

description = {
    "name": {
        "中文名": "20日收盘价位置",
        "英文名": "20-Day Close Position",
        "变量名": "close_position_20"
    },
    "info": {
        "介绍": "20日收盘价位置，计算当日收盘价在过去20日价格区间中的相对位置，反映价格强度",
        "日期": "",
        "计算公式": "close_position_20 = (close - min(low).rolling(20)) / (max(high).rolling(20) - min(low).rolling(20)) * 100"
    }
}

def compute_factor(df):
    def calculate_position(group):
        # 计算20日最高价和最低价
        high_20 = group['high'].rolling(window=20, min_periods=1).max()
        low_20 = group['low'].rolling(window=20, min_periods=1).min()
        
        # 计算收盘价位置
        position = (group['close'] - low_20) / (high_20 - low_20) * 100
        
        return position
    
    # 计算20日收盘价位置
    df['close_position_20'] = df.groupby('code', group_keys=False).apply(calculate_position)
    
    return df
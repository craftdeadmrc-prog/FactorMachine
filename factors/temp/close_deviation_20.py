"""
收盘价离差因子
计算收盘价相对于20日移动平均线的离差
"""
import pandas as pd
import numpy as np

dependencies = ["code", "close", "ma_20", "date"]

provided_columns = ["close_deviation_20"]

description = {
    "name": {
        "中文名": "20日收盘价离差",
        "英文名": "20-Day Close Deviation",
        "变量名": "close_deviation_20"
    },
    "info": {
        "介绍": "20日收盘价离差，计算当日收盘价相对于20日移动平均线的百分比差异，反映价格偏离程度",
        "日期": "",
        "计算公式": "close_deviation_20 = (close - ma_20) / ma_20 * 100"
    }
}

def compute_factor(df):
    # 首先计算20日移动平均线（如果不存在）
    if 'ma_20' not in df.columns:
        df['ma_20'] = df.groupby('code')['close'].transform(
            lambda x: x.rolling(window=20, min_periods=1).mean()
        )
    
    # 计算收盘价离差
    df['close_deviation_20'] = (df['close'] - df['ma_20']) / df['ma_20'] * 100
    
    return df
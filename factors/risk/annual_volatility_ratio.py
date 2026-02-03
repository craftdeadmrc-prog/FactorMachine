"""
年化波动率因子计算
基于滚动窗口计算年化波动率
"""
import numpy as np
import pandas as pd

dependencies = ["code", "return_ratio", "date"]

provided_columns = ["annual_volatility_ratio"]

description = {
    "name": {
        "中文名": "年化波动率",
        "英文名": "Annual Volatility Ratio",
        "变量名": "annual_volatility_ratio"
    },
    "info": {
        "介绍": "基于滚动窗口计算的年化波动率，反映资产在一年时间尺度上的风险水平",
        "日期": "",
        "计算公式": "annual_volatility_ratio = std(return_ratio) * sqrt(year_days)"
    }
}

def compute_factor(df):
    from utils.compat.window import get_window_size
    
    _, year_days = get_window_size(df)
    
    if year_days is None:
        df['annual_volatility_ratio'] = np.nan
        return df
    
    # 使用 groupby + transform 替代 apply
    df['annual_volatility_ratio'] = df.groupby('code')['return_ratio'].transform(
        lambda x: x.rolling(window=year_days, min_periods=2).std() * (year_days ** 0.5)
    )
    
    return df
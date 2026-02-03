"""
本年至今回报率因子计算
计算从本年第一天到当前日期的收益率
"""
import pandas as pd
import numpy as np

dependencies = ["code", "close", "date"]

provided_columns = ["ytd_return_ratio"]

description = {
    "name": {
        "中文名": "本年至今回报率",
        "英文名": "Year-to-Date Return Ratio",
        "变量名": "ytd_return_ratio"
    },
    "info": {
        "介绍": "本年至今回报率，计算从当年第一个交易日至当前日期的累计收益率",
        "日期": "",
        "计算公式": "ytd_return_ratio = (current_close - first_close_of_year) / first_close_of_year * 100"
    }
}

def compute_factor(df):
    # 提取年份
    df['year'] = df['date'].dt.year
    
    # 使用 transform 计算本年至今收益率
    # 先按code和year分组，然后计算相对于每年第一个交易日的收益率
    df['ytd_return_ratio'] = df.groupby(['code', 'year'])['close'].transform(
        lambda x: (x - x.iloc[0]) / x.iloc[0] * 100 if len(x) > 0 else np.nan
    )
    
    # 清理辅助列
    df = df.drop(columns=['year'])
    
    return df
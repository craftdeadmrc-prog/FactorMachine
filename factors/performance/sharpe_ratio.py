"""
夏普比率因子计算
计算夏普比率
"""
import pandas as pd
import numpy as np

dependencies = ["code", "annual_return_ratio", "annual_volatility_ratio"]

provided_columns = ["sharpe_ratio"]

description = {
    "name": {
        "中文名": "夏普比率",
        "英文名": "Sharpe Ratio",
        "变量名": "sharpe_ratio"
    },
    "info": {
        "介绍": "夏普比率，衡量单位总风险所带来的超额收益，由诺贝尔奖得主威廉·夏普于1966年提出",
        "日期": "1966",
        "计算公式": "sharpe_ratio = (annual_return_ratio - 2.0) / annual_volatility_ratio"
    }
}

def compute_factor(df):
    risk_free_rate = 2.0

    df['sharpe_ratio'] = (df['annual_return_ratio'] - risk_free_rate) / df['annual_volatility_ratio']
    df['sharpe_ratio'] = df['sharpe_ratio'].replace([np.inf, -np.inf], np.nan)
    
    return df
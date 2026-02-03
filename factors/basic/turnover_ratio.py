"""
换手率因子计算
"""
import pandas as pd

dependencies = ["code", "volume", "outstanding_share"]

provided_columns = ["turnover_ratio"]

description = {
    "name": {
        "中文名": "换手率",
        "英文名": "Turnover Ratio",
        "变量名": "turnover_ratio"
    },
    "info": {
        "介绍": "换手率，反映股票的流通性和交易活跃程度",
        "日期": "",
        "计算公式": "turnover_ratio = volume / outstanding_share * 100"
    }
}

def compute_factor(df):
    df['turnover_ratio'] = (df['volume'] / df['outstanding_share']) * 100
    return df
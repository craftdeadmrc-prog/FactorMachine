"""
卡玛比率因子计算
计算卡玛比率
"""
import pandas as pd
import numpy as np

dependencies = ["code", "annual_return_ratio", "max_drawdown"]

provided_columns = ["calmar_ratio"]

description = {
    "name": {
        "中文名": "卡玛比率",
        "英文名": "Calmar Ratio",
        "变量名": "calmar_ratio"
    },
    "info": {
        "介绍": "卡玛比率，衡量单位最大回撤所带来的超额收益，强调对极端风险的调整，由特里·杨于1991年提出",
        "日期": "1991",
        "计算公式": "calmar_ratio = (annual_return_ratio - 2.0) / max_drawdown"
    }
}

def compute_factor(df):
    risk_free_rate = 2.0
    
    df['calmar_ratio'] = (df['annual_return_ratio'] - risk_free_rate) / df['max_drawdown']
    df['calmar_ratio'] = df['calmar_ratio'].replace([np.inf, -np.inf], np.nan)
    
    positive_return_mask = (df['max_drawdown'] < 0.01) & (df['annual_return_ratio'] > risk_free_rate)
    df.loc[positive_return_mask, 'calmar_ratio'] = 10.0
    
    return df
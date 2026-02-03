"""
索提诺比率因子计算
计算索提诺比率
"""
import pandas as pd
import numpy as np

dependencies = ["code", "annual_return_ratio", "annual_downside_volatility"]

provided_columns = ["sortino_ratio"]

description = {
    "name": {
        "中文名": "索提诺比率",
        "英文名": "Sortino Ratio",
        "变量名": "sortino_ratio"
    },
    "info": {
        "介绍": "索提诺比率，衡量单位下行风险所带来的超额收益，只惩罚负向波动，由弗兰克·索提诺于1994年提出",
        "日期": "1994",
        "计算公式": "sortino_ratio = (annual_return_ratio - 2.0) / annual_downside_volatility"
    }
}

def compute_factor(df):
    risk_free_rate = 2.0
    
    df['sortino_ratio'] = (df['annual_return_ratio'] - risk_free_rate) / df['annual_downside_volatility']
    df['sortino_ratio'] = df['sortino_ratio'].replace([np.inf, -np.inf], np.nan)
    
    positive_return_mask = (df['annual_downside_volatility'] == 0) & (df['annual_return_ratio'] > risk_free_rate)
    df.loc[positive_return_mask, 'sortino_ratio'] = 10.0
    
    return df
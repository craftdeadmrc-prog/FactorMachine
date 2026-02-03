"""
价格动量振荡因子
计算价格百分比振荡指标(PPO)
"""
import pandas as pd
import numpy as np

dependencies = ["code", "close", "ma_12", "ma_26", "date"]

provided_columns = ["ppo"]

description = {
    "name": {
        "中文名": "价格百分比振荡指标",
        "英文名": "Percentage Price Oscillator",
        "变量名": "ppo"
    },
    "info": {
        "介绍": "价格百分比振荡指标(PPO)，计算短期和长期移动平均线的百分比差异，反映价格动量变化",
        "日期": "",
        "计算公式": "ppo = (ma_12 - ma_26) / ma_26 * 100"
    }
}

def compute_factor(df):
    # 计算PPO
    df['ppo'] = (df['ma_12'] - df['ma_26']) / df['ma_26'] * 100
    
    # 处理除零错误和异常值
    df['ppo'] = df['ppo'].replace([np.inf, -np.inf], np.nan)
    
    return df
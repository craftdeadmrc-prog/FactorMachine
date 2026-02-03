"""
相对强弱指数因子
计算14日RSI
"""
import pandas as pd
import numpy as np

dependencies = ["code", "close", "date"]

provided_columns = ["rsi_14"]

description = {
    "name": {
        "中文名": "14日相对强弱指数",
        "英文名": "14-Day Relative Strength Index",
        "变量名": "rsi_14"
    },
    "info": {
        "介绍": "14日相对强弱指数(RSI)，衡量价格变动的速度和幅度，反映超买超卖状态，由威尔斯·怀尔德于1978年提出",
        "日期": "1978",
        "计算公式": "rsi_14 = 100 - 100 / (1 + rs)，其中rs = 平均上涨幅度 / 平均下跌幅度"
    }
}

def compute_factor(df):
    def calculate_rsi(series, period=14):
        # 计算价格变化
        delta = series.diff()
        
        # 分离上涨和下跌
        gain = (delta.where(delta > 0, 0)).rolling(window=period, min_periods=1).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period, min_periods=1).mean()
        
        # 计算RS
        rs = gain / loss.replace(0, np.nan)
        
        # 计算RSI
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(50)  # 当损失为0时，RSI为100；当收益为0时，RSI为0
        
        return rsi
    
    # 计算14日RSI
    df['rsi_14'] = df.groupby('code')['close'].transform(calculate_rsi)
    
    return df
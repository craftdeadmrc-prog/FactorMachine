"""
动量因子
计算60日动量
"""

dependencies = ["code", "close", "date"]

provided_columns = ["momentum_60"]

description = {
    "name": {
        "中文名": "60日动量",
        "英文名": "60-Day Momentum",
        "变量名": "momentum_60"
    },
    "info": {
        "介绍": "60日动量，计算当前价格相对于60日前价格的变化率，反映中期价格趋势",
        "日期": "",
        "计算公式": "momentum_60 = (close - close.shift(60)) / close.shift(60) * 100"
    }
}

def compute_factor(df):
    # 60日动量
    df['momentum_60'] = df.groupby('code')['close'].transform(
        lambda x: (x - x.shift(60)) / x.shift(60) * 100
    )
    
    return df
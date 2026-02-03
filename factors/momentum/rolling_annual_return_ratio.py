"""
年回报率因子计算
计算滚动年收益率
"""
import numpy as np

dependencies = ["code", "close", "date"]

provided_columns = ["rolling_annual_return_ratio"]

description = {
    "name": {
        "中文名": "滚动年回报率",
        "英文名": "Rolling Annual Return Ratio",
        "变量名": "rolling_annual_return_ratio"
    },
    "info": {
        "介绍": "滚动计算的年化收益率，反映最近一年的收益表现",
        "日期": "",
        "计算公式": "rolling_annual_return_ratio = (close - close.shift(year_days)) / close.shift(year_days) * 100"
    }
}

def compute_factor(df):
    from utils.compat.window import get_window_size    
    _, year_days = get_window_size(df)
    
    if year_days is None:
        df['rolling_annual_return_ratio'] = np.nan
        return df
    
    # 使用 groupby + transform 替代 apply
    df['rolling_annual_return_ratio'] = df.groupby('code')['close'].transform(
        lambda x: (x - x.shift(year_days)) / x.shift(year_days) * 100
    )
    
    return df
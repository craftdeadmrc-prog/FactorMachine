"""
月回报率因子计算
计算滚动月收益率
"""
import numpy as np

dependencies = ["code", "close", "date"]

provided_columns = ["rolling_monthly_return_ratio"]

description = {
    "name": {
        "中文名": "滚动月回报率",
        "英文名": "Rolling Monthly Return Ratio",
        "变量名": "rolling_monthly_return_ratio"
    },
    "info": {
        "介绍": "滚动计算的月收益率，反映最近一个月的收益表现",
        "日期": "",
        "计算公式": "rolling_monthly_return_ratio = (close - close.shift(month_days)) / close.shift(month_days) * 100"
    }
}


def compute_factor(df):
    from utils.compat.window import get_window_size    
    month_days, _ = get_window_size(df)
    
    if month_days is None:
        df['rolling_monthly_return_ratio'] = np.nan
        return df
    
    # 使用 groupby + transform 替代 apply
    df['rolling_monthly_return_ratio'] = df.groupby('code')['close'].transform(
        lambda x: (x - x.shift(month_days)) / x.shift(month_days) * 100
    )
    
    return df
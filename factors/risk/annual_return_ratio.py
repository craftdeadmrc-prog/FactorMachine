"""
年化收益率因子计算
基于滚动窗口计算年化收益率
"""
import numpy as np

dependencies = ["code", "return_ratio", "date"]

provided_columns = ["annual_return_ratio"]

description = {
    "name": {
        "中文名": "年化收益率",
        "英文名": "Annual Return Ratio",
        "变量名": "annual_return_ratio"
    },
    "info": {
        "介绍": "基于滚动窗口计算的年化收益率，反映资产在一年时间尺度上的收益能力",
        "日期": "",
        "计算公式": "annual_return_ratio = mean(return_ratio) * year_days"
    }
}

def compute_factor(df):
    from utils.compat.window import get_window_size
    
    _, year_days = get_window_size(df)
    
    if year_days is None:
        df['annual_return_ratio'] = np.nan
        return df
    
    # 使用 groupby + transform 替代 apply
    df['annual_return_ratio'] = df.groupby('code')['return_ratio'].transform(
        lambda x: x.rolling(window=year_days, min_periods=1).mean() * year_days
    )
    
    return df
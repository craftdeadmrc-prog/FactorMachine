"""
窗口计算工具
用于获取月和年交易日数
"""
import pandas as pd

def get_window_size(source_df):
    """
    获取月和年交易日数，不满足条件返回None
    
    参数:
    source_df: 包含date列的数据框，date列为datetime类型
    
    返回:
    tuple: (月交易日数, 年交易日数) 如果不满足条件返回(None, None)
    """
    # 获取第一个code的数据
    codes = source_df['code'].unique()
    if len(codes) == 0:
        return None, None
    df = source_df[source_df['code'] == codes[0]]
    
    # 获取最新日期
    latest_date = df['date'].max()
    
    # 计算最近一年的数据
    one_year_ago = latest_date - pd.DateOffset(years=1)
    year_days = len(df[df['date'] > one_year_ago])
    # 计算最近一个月的数据
    one_month_ago = latest_date - pd.DateOffset(months=1)
    month_days = len(df[df['date'] > one_month_ago])
    
    # 检查是否满足条件：年数据至少240个交易日，月数据至少20个交易日
    if year_days < 240 or month_days < 20:
        return None, None
    
    return month_days, year_days
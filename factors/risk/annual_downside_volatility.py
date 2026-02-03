"""
年化下行波动率因子计算
计算滚动年化下行波动率
"""
import pandas as pd
import numpy as np

dependencies = ["code", "return_ratio", "date"]

provided_columns = ["annual_downside_volatility"]

description = {
    "name": {
        "中文名": "年化下行波动率",
        "英文名": "Annual Downside Volatility",
        "变量名": "annual_downside_volatility"
    },
    "info": {
        "介绍": "基于滚动窗口计算的年化下行波动率，只考虑低于无风险利率的收益率波动",
        "日期": "",
        "计算公式": "annual_downside_volatility = std(downside_returns) * sqrt(year_days)"
    }
}

def compute_factor(df):
    from utils.compat.window import get_window_size
    import numpy as np
    import pandas as pd
    
    _, year_days = get_window_size(df)
    
    if year_days is None:
        df['annual_downside_volatility'] = np.nan
        return df
    
    risk_free_rate = 2.0
    daily_risk_free = risk_free_rate / year_days
    
    # 使用列表推导式收集结果，然后重新索引
    downside_vol_dict = {}
    
    for code, group in df.groupby('code'):
        return_values = group['return_ratio'].values
        downside_vol_list = []
        
        for i in range(len(return_values)):
            if i < year_days - 1:
                downside_vol_list.append(np.nan)
            else:
                window_returns = return_values[i-year_days+1:i+1]
                downside_returns = window_returns[window_returns < daily_risk_free]
                
                if len(downside_returns) > 1:
                    downside_vol = np.std(downside_returns) * (year_days ** 0.5)
                else:
                    downside_vol = 0.0
                
                downside_vol_list.append(downside_vol)
        
        # 将结果与原始索引对应
        for idx, value in zip(group.index, downside_vol_list):
            downside_vol_dict[idx] = value
    
    # 创建 Series 并保持原始索引顺序
    downside_vol_series = pd.Series(downside_vol_dict).reindex(df.index)
    df['annual_downside_volatility'] = downside_vol_series
    
    return df
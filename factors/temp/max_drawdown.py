"""
最大回撤因子计算
计算滚动最大回撤
"""
import pandas as pd
import numpy as np

dependencies = ["code", "close", "date"]

provided_columns = ["max_drawdown"]

description = {
    "name": {
        "中文名": "最大回撤",
        "英文名": "Maximum Drawdown",
        "变量名": "max_drawdown"
    },
    "info": {
        "介绍": "最大回撤，衡量在指定窗口内从最高点到最低点的最大跌幅，反映投资组合可能面临的最大损失风险",
        "日期": "",
        "计算公式": "max_drawdown = max((cumulative_max - current_price) / cumulative_max) * 100"
    }
}

def compute_factor(df):
    from utils.compat.window import get_window_size
    import numpy as np
    import pandas as pd
    
    _, year_days = get_window_size(df)
    
    if year_days is None:
        df['max_drawdown'] = np.nan
        return df
    
    # 使用列表推导式收集结果，然后重新索引
    max_drawdown_dict = {}
    
    for code, group in df.groupby('code'):
        close_values = group['close'].values
        max_drawdown_list = []
        
        for i in range(len(close_values)):
            if i < year_days - 1:
                max_drawdown_list.append(np.nan)
            else:
                window_prices = close_values[i-year_days+1:i+1]
                cumulative_max = np.maximum.accumulate(window_prices)
                drawdown = (cumulative_max - window_prices) / cumulative_max * 100
                max_dd = np.max(drawdown)
                max_drawdown_list.append(max_dd)
        
        # 将结果与原始索引对应
        for idx, value in zip(group.index, max_drawdown_list):
            max_drawdown_dict[idx] = value
    
    # 创建 Series 并保持原始索引顺序
    max_drawdown_series = pd.Series(max_drawdown_dict).reindex(df.index)
    df['max_drawdown'] = max_drawdown_series
    
    return df
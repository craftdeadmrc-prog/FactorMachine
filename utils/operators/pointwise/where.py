# utils/operators/pointwise/where.py
description = {
    "description": "条件选择算子（点算子）",
    "args": {
        "condition": "布尔型条件序列或标量",
        "x": "条件为 True 时选取的值或序列",
        "y": "条件为 False 时选取的值或序列"
    },
    "return": "按条件从 x 和 y 中选择得到的序列",
    "example": "where(sub(close, shift(close, 1)) > 0, sub(close, shift(close, 1)), 0)"
}

def where(condition, x, y):
    """
    条件选择算子
    返回 Series 当输入是 Series，以便后续算子可以调用 .rolling()
    """
    import numpy as np
    import pandas as pd
    
    # condition 是 Series：用 pandas 自带 where，保持索引
    if isinstance(condition, pd.Series):
        return x.where(condition, y)
    
    # condition 不是 Series：走 numpy.where 逻辑
    if isinstance(x, pd.Series) or isinstance(y, pd.Series):
        idx = x.index if isinstance(x, pd.Series) else y.index
        return pd.Series(np.where(condition, x, y), index=idx)
    else:
        return np.where(condition, x, y)
# utils/operators/cross_section/where.py
description = {
    "description": "条件选择算子（截面算子）",
    "args": {
        "condition": "布尔型条件序列或标量",
        "x": "条件为 True 时选取的值或序列",
        "y": "条件为 False 时选取的值或序列",
        "group_by": "分组字段，默认为 'code'"
    },
    "return": "按条件从 x 和 y 中选择得到的序列",
    "example": "where(lt(close, open), close, open, 'date')"
}

def where(condition, x, y, group_by='code'):
    """
    条件选择算子，等价于 numpy.where

    参数:
    - condition: 布尔型条件序列或标量
    - x: 条件为 True 时选取的值或序列
    - y: 条件为 False 时选取的值或序列
    - group_by: 分组字段，默认为 'code'
    """
    import numpy as np
    import pandas as pd

    # 统一转成 Series，保证有索引可对齐
    if not isinstance(condition, pd.Series):
        condition = pd.Series(condition)
    if not isinstance(x, pd.Series):
        x = pd.Series(x, index=condition.index)
    if not isinstance(y, pd.Series):
        y = pd.Series(y, index=condition.index)

    # 分组行为：按 group_by 分组后在每个组内做 where，返回 transform 形态的结果
    result = pd.Series(index=condition.index)
    # 这里的 group_by 一般是 working_df 里的某一列，比如 'code' 或 'date'
    for name, group_idx in condition.groupby(group_by).groups.items():
        cond_group = condition.loc[group_idx]
        x_group = x.loc[group_idx]
        y_group = y.loc[group_idx]
        result[group_idx] = np.where(cond_group, x_group, y_group)
    return result
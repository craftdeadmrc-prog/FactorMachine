# utils/operators/cross_section/compare.py
description = {
    "description": "比较算子，返回布尔序列（截面算子）",
    "args": {
        "x": "左侧序列或标量",
        "y": "右侧序列或标量",
        "group_by": "分组字段，默认为 'code'"
    },
    "return": "布尔序列",
    "example": "gt(close, open, 'date')"
}

import numpy as np
import pandas as pd

def lt(x, y, group_by='code'):
    """
    小于：x < y（支持分组）

    参数:
    - x: 左侧序列或标量
    - y: 右侧序列或标量
    - group_by: 分组字段，默认为 'code'
    """

    if not isinstance(x, pd.Series):
        x = pd.Series(x)
    if not isinstance(y, pd.Series):
        y = pd.Series(y, index=x.index)

    result = pd.Series(index=x.index, dtype=bool)
    groups = x.groupby(group_by)
    for name, group_idx in groups.groups.items():
        result[group_idx] = np.less(x.loc[group_idx], y.loc[group_idx])
    return result

def gt(x, y, group_by='code'):
    """大于：x > y（支持分组）"""
    import numpy as np
    import pandas as pd

    if not isinstance(x, pd.Series):
        x = pd.Series(x)
    if not isinstance(y, pd.Series):
        y = pd.Series(y, index=x.index)

    result = pd.Series(index=x.index, dtype=bool)
    groups = x.groupby(group_by)
    for name, group_idx in groups.groups.items():
        result[group_idx] = np.greater(x.loc[group_idx], y.loc[group_idx])
    return result

def le(x, y, group_by='code'):
    """小于等于：x <= y（支持分组）"""
    import numpy as np
    import pandas as pd

    if not isinstance(x, pd.Series):
        x = pd.Series(x)
    if not isinstance(y, pd.Series):
        y = pd.Series(y, index=x.index)

    result = pd.Series(index=x.index, dtype=bool)
    groups = x.groupby(group_by)
    for name, group_idx in groups.groups.items():
        result[group_idx] = np.less_equal(x.loc[group_idx], y.loc[group_idx])
    return result

def ge(x, y, group_by='code'):
    """大于等于：x >= y（支持分组）"""
    import numpy as np
    import pandas as pd

    if not isinstance(x, pd.Series):
        x = pd.Series(x)
    if not isinstance(y, pd.Series):
        y = pd.Series(y, index=x.index)

    result = pd.Series(index=x.index, dtype=bool)
    groups = x.groupby(group_by)
    for name, group_idx in groups.groups.items():
        result[group_idx] = np.greater_equal(x.loc[group_idx], y.loc[group_idx])
    return result

def eq(x, y, group_by='code'):
    """等于：x == y（支持分组）"""
    import numpy as np
    import pandas as pd

    if not isinstance(x, pd.Series):
        x = pd.Series(x)
    if not isinstance(y, pd.Series):
        y = pd.Series(y, index=x.index)

    result = pd.Series(index=x.index, dtype=bool)
    groups = x.groupby(group_by)
    for name, group_idx in groups.groups.items():
        result[group_idx] = np.equal(x.loc[group_idx], y.loc[group_idx])
    return result

def ne(x, y, group_by='code'):
    """不等于：x != y（支持分组）"""
    import numpy as np
    import pandas as pd

    if not isinstance(x, pd.Series):
        x = pd.Series(x)
    if not isinstance(y, pd.Series):
        y = pd.Series(y, index=x.index)

    result = pd.Series(index=x.index, dtype=bool)
    groups = x.groupby(group_by)
    for name, group_idx in groups.groups.items():
        result[group_idx] = np.not_equal(x.loc[group_idx], y.loc[group_idx])
    return result
# utils/operators/cross_section/winsorize.py
description = {
    "description": "对因子进行去极值处理（截面算子）",
    "args": {
        "x": "输入因子数据",
        "lower": "下界分位数，取值范围 [0, 1)，默认为 0.01",
        "upper": "上界分位数，取值范围 (0, 1]，默认为 0.99",
        "group_by": "分组字段，默认为'date'"
    },
    "return": "去极值后的因子数据，与输入形状相同",
    "example": "winsorize(factor_value, 0.01, 0.99, 'industry')"
}

def winsorize(x, lower=0.01, upper=0.99, group_by='date'):
    """
    去极值算子，支持全局和分组处理
    """
    import numpy as np

    if not (0.0 <= lower < upper <= 1.0):
        raise ValueError("lower 必须小于 upper 且二者均在 [0, 1] 范围内")

    def group_winsorize(group):
        q_low = np.nanquantile(group, lower)
        q_high = np.nanquantile(group, upper)
        return group.clip(lower=q_low, upper=q_high)
    return x.groupby(group_by).transform(group_winsorize)
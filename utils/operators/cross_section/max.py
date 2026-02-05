# utils/operators/cross_section/max.py
description = {
    "description": "计算输入序列的最大值（截面算子）",
    "args": {},
    "return": "最大值标量",
    "example": "max(high)"
}

def max(x):
    """
    简单最大值算子
    """
    # 因为会出现整体时间序列的max导致未来函数，所以仅用cummax
    return x.cummax()
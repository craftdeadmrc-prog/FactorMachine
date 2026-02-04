# utils/operators/pointwise/max.py
description = {
    "description": "计算输入序列的最大值（点算子）",
    "args": {},
    "return": "最大值标量",
    "example": "max(high)"
}

def max(series):
    """
    简单最大值算子
    """
    return series.max()
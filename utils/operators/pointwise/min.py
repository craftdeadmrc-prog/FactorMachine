# utils/operators/pointwise/min.py
description = {
    "description": "计算输入序列的最小值（点算子）",
    "args": {},
    "return": "最小值标量",
    "example": "min(low)"
}

def min(series):
    """
    简单最小值算子
    """
    return series.min()
# utils/operators/pointwise/abs.py
description = {
    "description": "计算输入序列的绝对值（点算子）",
    "args": {
        "x": "输入序列"
    },
    "return": "绝对值序列",
    "example": "abs(return_ratio)"
}

def abs(x):
    """
    绝对值算子
    """
    import numpy as np
    return np.abs(x)
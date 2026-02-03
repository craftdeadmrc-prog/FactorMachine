# utils/operators/pointwise/log.py
description = {
    "description": "计算输入序列的自然对数（点算子）",
    "args": {
        "x": "输入序列，必须为正值"
    },
    "return": "自然对数序列",
    "example": "log(close)"
}

def log(x):
    """
    自然对数算子
    """
    import numpy as np
    return np.log(x+1e-8)
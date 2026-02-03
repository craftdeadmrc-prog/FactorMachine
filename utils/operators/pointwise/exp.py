# utils/operators/pointwise/exp.py
description = {
    "description": "计算输入序列的指数函数（点算子）",
    "args": {
        "x": "输入序列"
    },
    "return": "指数函数结果序列",
    "example": "exp(log_return)"
}

def exp(x):
    """
    指数算子
    """
    import numpy as np
    return np.exp(x)
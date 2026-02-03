# utils/operators/pointwise/sin.py
description = {
    "description": "计算输入序列的正弦函数（点算子）",
    "args": {
        "x": "输入序列（弧度）"
    },
    "return": "正弦函数结果序列",
    "example": "sin(close)"
}

def sin(x):
    """
    正弦算子
    """
    import numpy as np
    return np.sin(x)
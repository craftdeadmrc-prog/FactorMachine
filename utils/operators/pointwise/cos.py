# utils/operators/pointwise/cos.py
description = {
    "description": "计算输入序列的余弦函数（点算子）",
    "args": {
        "x": "输入序列（弧度）"
    },
    "return": "余弦函数结果序列",
    "example": "cos(close)"
}

def cos(x):
    """
    余弦算子
    """
    import numpy as np
    return np.cos(x)
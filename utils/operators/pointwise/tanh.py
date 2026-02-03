# utils/operators/pointwise/tanh.py
description = {
    "description": "计算输入序列的双曲正切函数（点算子）",
    "args": {
        "x": "输入序列"
    },
    "return": "tanh 变换后的序列，取值区间为 (-1, 1)",
    "example": "tanh(zscore(return_ratio))"
}

def tanh(x):
    """
    双曲正切算子
    """
    import numpy as np
    return np.tanh(x)
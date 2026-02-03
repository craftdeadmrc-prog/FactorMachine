# utils/operators/pointwise/where.py
description = {
    "description": "条件选择算子，类似 numpy.where（点算子）",
    "args": {
        "condition": "布尔型条件序列或标量",
        "x": "条件为 True 时选取的值或序列",
        "y": "条件为 False 时选取的值或序列"
    },
    "return": "按条件从 x 和 y 中选择得到的序列",
    "example": "where(sub(close, shift(close, 1)) > 0, sub(close, shift(close, 1)), 0)"
}

def where(condition, x, y):
    """
    条件选择算子，等价于 numpy.where
    """
    import numpy as np
    return np.where(condition, x, y)
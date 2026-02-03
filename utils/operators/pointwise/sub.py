# FactorMachine/utils/operators/pointwise/sub.py
description = {
    "description": "点态减法算子，逐元素计算 x - y",
    "args": {
        "x": "被减数，可以是标量、序列或数组",
        "y": "减数，可以是标量、序列或数组"
    },
    "return": "逐元素相减后的结果",
    "example": "sub(close, open)"
}

def sub(x, y):
    """
    点态减法算子
    """
    return x - y


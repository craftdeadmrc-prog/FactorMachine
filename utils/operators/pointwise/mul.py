# FactorMachine/utils/operators/pointwise/mul.py
description = {
    "description": "点态乘法算子，逐元素计算 x * y",
    "args": {
        "x": "左操作数，可以是标量、序列或数组",
        "y": "右操作数，可以是标量、序列或数组"
    },
    "return": "逐元素相乘后的结果",
    "example": "mul(close, volume)"
}

def mul(x, y):
    """
    点态乘法算子
    """
    return x * y


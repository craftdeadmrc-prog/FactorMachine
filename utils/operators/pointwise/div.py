# FactorMachine/utils/operators/pointwise/div.py
description = {
    "description": "点态除法算子，逐元素计算 x / y，支持标量或数组间的广播运算",
    "args": {
        "x": "被除数，可以是标量、序列或数组",
        "y": "除数，可以是标量、序列或数组"
    },
    "return": "逐元素相除后的结果",
    "example": "div(close, open)"
}

def div(x, y):
    """
    点态除法算子
    """
    return x / y


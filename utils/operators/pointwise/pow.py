# FactorMachine/utils/operators/pointwise/pow.py
description = {
    "description": "幂运算算子，逐元素计算 x 的 y 次方（点算子）",
    "args": {
        "x": "底数，可以是标量、序列或数组",
        "y": "指数，可以是标量、序列或数组"
    },
    "return": "逐元素幂运算后的结果",
    "example": "pow(close, 2)"
}

def pow(x, y):
    """
    点态幂运算算子
    """
    return x ** y


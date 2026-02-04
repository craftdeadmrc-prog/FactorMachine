# utils/operators/pointwise/compare.py
description = {
    "description": "比较算子，返回布尔序列（点算子）",
    "args": {
        "x": "左侧序列或标量",
        "y": "右侧序列或标量"
    },
    "return": "布尔序列",
    "example": "lt(sub(close, shift(close, 1)), 0)"
}

import numpy as np
def lt(x, y):
    """小于：x < y"""
    return np.less(x, y)

def gt(x, y):
    """大于：x > y"""
    return np.greater(x, y)

def le(x, y):
    """小于等于：x <= y"""
    return np.less_equal(x, y)

def ge(x, y):
    """大于等于：x >= y"""
    return np.greater_equal(x, y)

def eq(x, y):
    """等于：x == y"""
    return np.equal(x, y)

def ne(x, y):
    """不等于：x != y"""
    return np.not_equal(x, y)
# utils/operators/pointwise/neg.py
description = {
    "description": "对输入序列取负值（点算子）",
    "args": {
        "x": "输入序列"
    },
    "return": "取负后的序列",
    "example": "neg(close)"
}

def neg(x):
    """
    取负算子
    """
    return -x
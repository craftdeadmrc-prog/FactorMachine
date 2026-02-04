# utils/operators/cross_section/cummax.py
description = {
    "description": "对输入序列计算从起始到当前的累计最大值（截面算子）",
    "args": {},
    "return": "累计最大值序列",
    "example": "cummax(close)"
}

def cummax(x):
    """
    累计最大值算子
    """
    return x.cummax()

# utils/operators/pointwise/std.py
description = {
    "description": "计算输入序列的标准差（点算子）",
    "args": {},
    "return": "标准差标量",
    "example": "std(return_ratio)"
}

def std(series):
    """
    简单标准差算子
    """
    return series.std()
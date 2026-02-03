# utils/operators/pointwise/mean.py
description = {
    "description": "计算输入序列的算术平均值（点算子）",
    "args": {},
    "return": "均值标量",
    "example": "mean(return_ratio)"
}

def mean(series):
    """
    简单均值算子
    """
    return series.mean()
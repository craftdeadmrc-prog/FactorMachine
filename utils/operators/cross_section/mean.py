# utils/operators/time_series/mean.py
description = {
    "description": "计算输入序列的算术平均值（时序算子）",
    "args": {},
    "return": "均值标量",
    "example": "mean(return_ratio)"
}

def mean(series):
    """
    简单均值算子
    """
    return series.mean()
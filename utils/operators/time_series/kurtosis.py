# utils/operators/time_series/kurtosis.py
description = {
    "description": "计算输入序列的峰度（时序算子）",
    "args": {
        "x": "输入序列"
    },
    "return": "峰度值（标量）",
    "example": "kurtosis(return_ratio)"
}

def kurtosis(x):
    """
    峰度算子
    """
    import scipy.stats as stats
    return stats.kurtosis(x)
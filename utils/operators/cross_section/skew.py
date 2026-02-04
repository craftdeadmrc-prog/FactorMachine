# utils/operators/cross_section/skew.py
description = {
    "description": "计算输入序列的偏度（截面算子）",
    "args": {
        "x": "输入序列"
    },
    "return": "偏度值（标量）",
    "example": "skew(return_ratio)"
}

def skew(x):
    """
    偏度算子
    """
    import scipy.stats as stats
    return stats.skew(x)
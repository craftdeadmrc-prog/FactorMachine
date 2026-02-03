# utils/operators/timeseries/rolling_sum.py
description = {
    "description": "对输入序列按给定窗口计算滚动求和（时间序列算子）",
    "args": {
        "window": "滚动窗口长度（正整数）",
        "min_periods": "窗口内最小有效观测数量，默认为 1"
    },
    "return": "滚动求和序列",
    "example": "rolling_sum(return_ratio, window=5)"
}

def rolling_sum(series, window, min_periods=1):
    """
    简单滚动求和算子
    """
    return series.rolling(window=window, min_periods=min_periods).sum()
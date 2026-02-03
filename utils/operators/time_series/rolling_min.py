# utils/operators/timeseries/rolling_min.py
description = {
    "description": "对输入序列按给定窗口计算滚动最小值（时间序列算子）",
    "args": {
        "window": "滚动窗口长度（正整数）",
        "min_periods": "窗口内最小有效观测数量，默认为 1"
    },
    "return": "滚动最小值序列",
    "example": "rolling_min(low, window=20)"
}

def rolling_min(series, window, min_periods=1):
    """
    简单滚动最小值算子
    """
    return series.rolling(window=window, min_periods=min_periods).min()
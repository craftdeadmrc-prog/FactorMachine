# utils/operators/timeseries/rolling_kurtosis.py
description = {
    "description": "对输入序列按给定窗口计算滚动峰度（时间序列算子）",
    "args": {
        "window": "滚动窗口长度（正整数）",
        "min_periods": "窗口内最小有效观测数量，默认为 1"
    },
    "return": "滚动峰度序列",
    "example": "rolling_kurtosis(return_ratio, window=60)"
}

def rolling_kurtosis(series, window, min_periods=1):
    """
    简单滚动峰度算子
    """
    import pandas as pd
    import scipy.stats as stats

    def _kurt(x):
        return stats.kurtosis(x)

    return series.rolling(window=window, min_periods=min_periods).apply(_kurt, raw=False)
# utils/operators/timeseries/rolling_skew.py
description = {
    "description": "对输入序列按给定窗口计算滚动偏度（时间序列算子）",
    "args": {
        "window": "滚动窗口长度（正整数）",
        "min_periods": "窗口内最小有效观测数量，默认为 1"
    },
    "return": "滚动偏度序列",
    "example": "rolling_skew(return_ratio, window=60)"
}

def rolling_skew(series, window, min_periods=1):
    """
    简单滚动偏度算子
    """
    import pandas as pd
    import scipy.stats as stats

    def _skew(x):
        return stats.skew(x)

    return series.rolling(window=window, min_periods=min_periods).apply(_skew, raw=False)
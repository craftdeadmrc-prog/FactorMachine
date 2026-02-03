# FactorMachine/utils/operators/time_series/rolling_zscore.py

description = {
    "description": "对时间序列进行滚动 z-score 标准化，仅使用过去 window 期数据",
    "args": {
        "x": "输入时间序列数据，通常为 pandas.Series",
        "window": "滚动窗口长度（大于 1 的正整数），例如 20 表示使用过去 20 期数据"
    },
    "return": "滚动 z-score 标准化后的时间序列，索引与输入一致；前 window-1 个点为 NaN",
    "example": "rolling_zscore(factor, 20)"
}

def rolling_zscore(x, window):
    """
    时间序列滚动 z-score 标准化算子
    """
    import pandas as pd
    import numpy as np

    if window is None or window <= 1:
        raise ValueError("window 必须为大于 1 的正整数")

    # 保证是 Series
    if not isinstance(x, pd.Series):
        x = pd.Series(x)

    def _last_point_zscore(arr):
        """
        对窗口内最后一个点做 z-score：(x_last - mean) / std
        """
        mean = np.nanmean(arr)
        std = np.nanstd(arr)
        if std == 0 or np.isnan(std):
            return np.nan
        return (arr[-1] - mean) / std

    # 仅基于窗口内历史数据计算当前点 z-score
    z = x.rolling(window=window, min_periods=window).apply(
        _last_point_zscore,
        raw=True
    )
    z.name = getattr(x, "name", None)
    return z
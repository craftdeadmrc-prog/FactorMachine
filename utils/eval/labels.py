# utils/eval/labels.py
# 标签计算模块（内部使用）

from __future__ import annotations

import numpy as np
import pandas as pd


def build_forward_return_label(
    df: pd.DataFrame,
    horizon: int = 1,
    log_return: bool = False,
) -> pd.Series:
    """
    构建未来 horizon 期收益率标签（逐股票按时间排序后计算）。

    参数:
        data_df : DataFrame
            至少包含列 ['date', 'code', 'close']，行表示 (code, date) 观测。
        horizon : int
            预测期长度（以行对应的交易日数计）。
        log_return : bool
            True 则使用对数收益 log(P_{t+h}/P_t)，否则使用简单收益 (P_{t+h}-P_t)/P_t。

    返回:
        pd.Series
            与 data_df 行顺序一一对应的标签序列。
    """

    def _calc_group(gp: pd.DataFrame) -> pd.Series:
        px = gp["close"]
        px_shift = px.shift(-horizon)
        if log_return:
            return np.log(px_shift / px)
        return (px_shift - px) / px
    series = df.groupby("code", group_keys=False).apply(_calc_group)
    # 直接 groupby + apply，group_keys=False 保持扁平索引
    return series.to_frame("label")


def build_forward_vol_label(
    data_df: pd.DataFrame,
    horizon: int = 1,
    window: int = 20,
) -> pd.Series:
    """
    构建未来波动率标签（用过去 window 期收益的滚动标准差并向前平移 horizon）。

    参数:
        data_df : DataFrame
            至少包含列 ['date', 'code', 'close']。
        horizon : int
            预测期长度（向前平移的步数）。
        window : int
            计算历史波动率的滚动窗口长度。

    返回:
        pd.Series
            与 data_df 行顺序一一对应的标签序列。
    """
    df = data_df.sort_values(["code", "date"])

    def _calc_group(gp: pd.DataFrame) -> pd.Series:
        px = gp["close"]
        ret = np.log(px / px.shift(1))
        vol = ret.rolling(window=window, min_periods=1).std()
        return vol.shift(-horizon)

    return df.groupby("code", group_keys=False).apply(_calc_group)
# utils/eval/ic.py
# IC 计算模块（内部使用）

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, Any


def calculate_ic_series(
    factor_panel: pd.DataFrame,
    label_panel: pd.DataFrame,
    method: str = "spearman",
) -> pd.Series:
    """
    计算因子 IC 时间序列（按日期逐截面相关性）。

    参数:
        factor_panel : DataFrame
            行索引为日期，列为 code，元素为因子值。
        label_panel : DataFrame
            行索引为日期，列为 code，元素为标签值（如未来收益）。
        method : str
            相关性方法，'spearman' 或 'pearson'。

    返回:
        pd.Series
            索引为日期的 IC 时间序列。
    """
    ic_dict: Dict[pd.Timestamp, float] = {}
    common_dates = factor_panel.index.intersection(label_panel.index)

    for date in common_dates:
        factor_series = factor_panel.loc[date]
        label_series = label_panel.loc[date]

        # 去除缺失值
        mask = ~(factor_series.isna() | label_series.isna())
        if mask.sum() < 5:
            ic_dict[date] = np.nan
            continue

        x = factor_series[mask].to_numpy(dtype=float)
        y = label_series[mask].to_numpy(dtype=float)

        if method.lower() == "spearman":
            ic, _ = stats.spearmanr(x, y)
        else:
            ic, _ = stats.pearsonr(x, y)

        ic_dict[date] = float(ic)

    return pd.Series(ic_dict).sort_index()


def calculate_ic_summary(ic_series: pd.Series) -> Dict[str, Any]:
    """
    根据 IC 时间序列计算统计指标。

    指标包括：
        - mean_ic        : 平均 IC
        - std_ic         : IC 标准差
        - t_value        : t 统计量
        - ic_ir          : IC 信息比率（mean / std）
        - positive_ratio : IC 为正的比例
        - valid_periods  : 有效样本期数

    参数:
        ic_series : pd.Series
            IC 时间序列。

    返回:
        dict
            IC 统计结果。
    """
    s = ic_series.dropna()
    n = len(s)

    if n == 0:
        return {
            "mean_ic": np.nan,
            "std_ic": np.nan,
            "t_value": np.nan,
            "ic_ir": np.nan,
            "positive_ratio": np.nan,
            "valid_periods": 0,
        }

    mean_ic = float(s.mean())
    std_ic = float(s.std())

    if std_ic != 0.0:
        t_value = mean_ic / (std_ic / np.sqrt(n))
        ic_ir = mean_ic / std_ic
    else:
        t_value = np.nan
        ic_ir = np.nan

    positive_ratio = float((s > 0).mean())

    return {
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "t_value": t_value,
        "ic_ir": ic_ir,
        "positive_ratio": positive_ratio,
        "valid_periods": n,
    }
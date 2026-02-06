# utils/eval/outlier.py

import pandas as pd


def cap_outliers(panel: pd.DataFrame, low_quantile: float = 0.05, high_quantile: float = 0.95) -> pd.DataFrame:
    """
    对面板数据中的每个因子列进行极值截断处理（winsorization），将超出指定分位数的值截断至该分位数。

    参数:
        panel: 包含因子列（除 date, code, label 外）的 DataFrame
        low_quantile: 低分位数（默认 0.05）
        high_quantile: 高分位数（默认 0.95）

    返回:
        DataFrame: 经过截断处理后的 DataFrame（副本）
    """
    # 创建副本以避免修改原始数据
    out = panel.copy()
    # 识别因子列（排除 date, code, label）
    factor_cols = [col for col in out.columns if col not in ["date", "code", "label"]]
    for col in factor_cols:
        # 计算分位数
        low = out[col].quantile(low_quantile)
        high = out[col].quantile(high_quantile)
        # 将超出范围的值截断
        out[col] = out[col].clip(lower=low, upper=high)
    return out
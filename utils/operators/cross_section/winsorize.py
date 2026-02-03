# FactorMachine/utils/operators/cross_section/winsorize.py

description = {
    "description": "对因子进行截面去极值处理（Winsorize），将截面上的极端值压缩到给定分位数上",
    "args": {
        "x": "输入因子数据，通常为一维 pandas.Series 或 pandas.DataFrame（按列独立处理）",
        "lower": "下界分位数，取值范围 [0, 1)，默认为 0.01",
        "upper": "上界分位数，取值范围 (0, 1]，默认为 0.99"
    },
    "return": "截面去极值后的因子数据，与输入形状相同",
    "example": "winsorize(factor_value, 0.01, 0.99)"
}

def winsorize(x, lower=0.01, upper=0.99):
    """
    截面去极值算子，将极端值压缩到指定分位数处
    """
    import numpy as np
    import pandas as pd

    if not (0.0 <= lower < upper <= 1.0):
        raise ValueError("lower 必须小于 upper 且二者均在 [0, 1] 范围内")

    # DataFrame：按列独立做截面 winsorize
    if isinstance(x, pd.DataFrame):
        result = x.copy()
        for col in result.columns:
            col_data = result[col]
            if col_data.notna().sum() == 0:
                # 全 NaN 列，跳过
                continue
            q_low = np.nanquantile(col_data, lower)
            q_high = np.nanquantile(col_data, upper)
            result[col] = col_data.clip(lower=q_low, upper=q_high)
        return result

    # Series 或一维 array：视作单个截面
    col_data = x
    if isinstance(x, pd.Series):
        col_data = x.values

    q_low = np.nanquantile(col_data, lower)
    q_high = np.nanquantile(col_data, upper)
    clipped = np.clip(col_data, q_low, q_high)

    # 保持与输入类型一致
    if isinstance(x, pd.Series):
        return x.__class__(clipped, index=x.index, name=x.name)
    else:
        return clipped
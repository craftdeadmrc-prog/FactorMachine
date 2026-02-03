# FactorMachine/utils/operators/cross_section/neutralize.py

description = {
    "description": "对因子进行截面中性化处理：按分组变量在组内做 z-score 标准化（减去组内均值并除以组内标准差）",
    "args": {
        "x": "输入因子数据，pandas.Series 或 pandas.DataFrame（按列独立处理中性化）",
        "by": "分组变量（如行业、市值分组等），与 x 在索引上对齐的 pandas.Series 或一维数组"
    },
    "return": "中性化后的因子数据，与 x 形状一致",
    "example": "neutralize(factor_value, industry_code)"
}

def neutralize(x, by):
    """
    截面中性化算子：按分组变量在组内做 z-score 标准化
    """
    import pandas as pd
    import numpy as np

    # 统一 by 为 Series，索引与 x 对齐
    if isinstance(x, pd.DataFrame) or isinstance(x, pd.Series):
        idx = x.index
    else:
        # x 非 pandas 类型时，只能假设 by 已内含正确索引或顺序
        idx = None

    by_series = by
    if not isinstance(by_series, pd.Series):
        by_series = pd.Series(by, index=idx)

    # DataFrame：对每一列分别中性化
    if isinstance(x, pd.DataFrame):
        result = x.copy()
        for col in result.columns:
            s = result[col]
            # 保证索引对齐
            s, g = s.align(by_series, join="left")
            group_mean = s.groupby(g).transform("mean")
            group_std = s.groupby(g).transform("std")
            std_safe = group_std.replace(0, np.nan)
            result[col] = (s - group_mean) / std_safe
        return result

    # Series：组内 z-score
    if isinstance(x, pd.Series):
        s, g = x.align(by_series, join="left")
        group_mean = s.groupby(g).transform("mean")
        group_std = s.groupby(g).transform("std")
        std_safe = group_std.replace(0, np.nan)
        return (s - group_mean) / std_safe

    # 其他类型：先转为 Series 再处理
    s = pd.Series(x, index=by_series.index)
    group_mean = s.groupby(by_series).transform("mean")
    group_std = s.groupby(by_series).transform("std")
    std_safe = group_std.replace(0, np.nan)
    return (s - group_mean) / std_safe
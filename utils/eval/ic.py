# utils/eval/ic.py

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def calculate_ic(
    panel: pd.DataFrame,
    method: str = "spearman",
) -> pd.DataFrame:
    """
    计算因子 IC 时间序列（按日期逐截面相关性）。

    参数
    ----
    panel : DataFrame
        列为 date, code, 若干个 factor，label。
    method : str
        相关性方法，"spearman" 表示 Rank IC，"pearson" 表示普通相关系数。

    返回
    ----
    pd.DataFrame
        索引为日期的若干个因子 IC 时间序列，列名为 "ic_因子名"。
    """
    # 获取因子列名（排除 date、code、label 列）
    factors = [col for col in panel.columns if col not in ["date", "code", "label"]]
    results = []

    # 按日期分组计算 IC
    for date, group in panel.groupby("date"):
        date_result = {"date": date}

        for factor in factors:
            factor_series = group[factor]
            label_series = group["label"]
            # 删除缺失值
            mask = ~(factor_series.isna() | label_series.isna())
            x = factor_series[mask].to_numpy(dtype=float)
            y = label_series[mask].to_numpy(dtype=float)
            if len(x) < 2:
                ic = np.nan
            else:
                if np.all(x == x[0]) or np.all(y == y[0]):
                    ic = np.nan
                else:
                    if method.lower() == "spearman":
                        ic, _ = stats.spearmanr(x, y)
                    elif method.lower() == "pearson":
                        ic, _ = stats.pearsonr(x, y)
                    else:
                        raise ValueError(f"不支持的method: {method}，请使用'spearman'或'pearson'")
            date_result[f"ic_{factor}"] = float(ic)

        results.append(date_result)
    if results:
        ic_df = pd.DataFrame(results)
        ic_df.set_index("date", inplace=True)
    else:
        ic_columns = [f"ic_{factor}" for factor in factors]
        ic_df = pd.DataFrame(columns=ic_columns)

    return ic_df


def calculate_ic_summary(ic_pd: pd.DataFrame) -> pd.DataFrame:
    """
    根据 IC 时间序列计算累积统计指标（逐步计算，避免未来信息泄露）。

    指标包括
    ----------
    {ic}_mean            : 累积平均 IC
    {ic}_std             : 累积 IC 标准差
    {ic}_t_value         : 累积 t 统计量
    {ic}_ic_ir           : 累积 IC 信息比率（mean / std）
    {ic}_positive_ratio  : 累积 IC 为正的比例
    {ic}_decay_rate      : 当前累计平均 IC 绝对值，相对历史最大累计平均 IC 绝对值的比率（0 ~ 1）

    参数
    ----
    ic_pd : pd.DataFrame

    返回
    ----
    pd.DataFrame
        索引为日期，列为各个因子的累积统计指标。
    """
    if len(ic_pd) == 0:
        return pd.DataFrame()

    result_dict = {}

    # 为每个 IC 列创建逐步累积统计序列
    for ic_col in ic_pd.columns.tolist():
        ic_series = ic_pd[ic_col]

        mean_series = []
        std_series = []
        t_value_series = []
        ic_ir_series = []
        positive_ratio_series = []

        # 从第 20 个样本开始滚动统计
        for i in range(20, len(ic_series) + 1):
            cumulative_data = ic_series.iloc[:i].dropna()
            n = len(cumulative_data)

            if n == 0:
                mean_series.append(np.nan)
                std_series.append(np.nan)
                t_value_series.append(np.nan)
                ic_ir_series.append(np.nan)
                positive_ratio_series.append(np.nan)
            else:
                mean_ic = cumulative_data.mean()
                std_ic = cumulative_data.std()

                if std_ic != 0.0 and n > 1:
                    t_value = mean_ic / (std_ic / np.sqrt(n))
                    ic_ir = mean_ic / std_ic
                else:
                    t_value = np.nan
                    ic_ir = np.nan

                positive_ratio = float((cumulative_data > 0).mean())

                mean_series.append(float(mean_ic))
                std_series.append(float(std_ic))
                t_value_series.append(float(t_value))
                ic_ir_series.append(float(ic_ir))
                positive_ratio_series.append(float(positive_ratio))

        result_dict[f"{ic_col}_mean"] = mean_series
        result_dict[f"{ic_col}_std"] = std_series
        result_dict[f"{ic_col}_t_value"] = t_value_series
        result_dict[f"{ic_col}_ic_ir"] = ic_ir_series
        result_dict[f"{ic_col}_positive_ratio"] = positive_ratio_series

    # 对齐索引（从第 20 天开始）
    ic_pd = ic_pd[19:]

    # 计算 IC 衰减率（使用绝对值，范围 0~1）
    for ic_col in ic_pd.columns.tolist():
        mean_series = result_dict[f"{ic_col}_mean"]
        mean_ser = pd.Series(mean_series, index=ic_pd.index)

        # 历史累计平均 IC 绝对值的最大值
        overall_max_abs = mean_ser.abs().max()

        if overall_max_abs != 0:
            decay_rate_series = mean_ser.abs() / overall_max_abs
        else:
            decay_rate_series = [np.nan] * len(mean_ser)

        result_dict[f"{ic_col}_decay_rate"] = list(decay_rate_series)

    result_df = pd.DataFrame(result_dict, index=ic_pd.index)

    return result_df


def calculate_monotonicity(panel: pd.DataFrame, num_groups: int = 5) -> pd.DataFrame:
    """
    计算每个因子的单调性：按截面对因子值分组，将股票分为 num_groups 组，
    计算每组平均回报，然后用组号与组回报的 Spearman 秩相关系数度量单调性。

    参数
    ----
    panel : DataFrame
        包含列 date, code, label 以及若干因子列。
    num_groups : int
        分组数量，通常为 5。

    返回
    ----
    DataFrame
        索引为日期，列为因子名，值为单调性（Spearman 秩相关系数）。
    """
    import numpy as np
    import pandas as pd
    from scipy import stats

    factor_cols = [col for col in panel.columns if col not in ["date", "code", "label"]]
    results = []

    for date, group in panel.groupby("date"):
        date_result = {"date": date}

        for factor in factor_cols:
            factor_series = group[factor]
            label_series = group["label"]

            # 移除缺失值
            mask = ~(factor_series.isna() | label_series.isna())
            factor_series = factor_series[mask]
            label_series = label_series[mask]

            if len(factor_series) < num_groups:
                monotonicity = np.nan
            else:
                # 使用 qcut 将因子值分成 num_groups 组（0 ~ num_groups-1）
                groups = pd.qcut(
                    factor_series,
                    q=num_groups,
                    labels=False,
                    duplicates="drop",
                )
                # 计算每组平均回报
                group_returns = label_series.groupby(groups).mean()
                present_groups = group_returns.index

                # 组数至少为 2 才能计算 Spearman
                if len(present_groups) > 1:
                    monotonicity, _ = stats.spearmanr(present_groups, group_returns)
                else:
                    monotonicity = np.nan

            date_result[factor] = monotonicity

        results.append(date_result)

    monotonicity_df = pd.DataFrame(results)
    monotonicity_df.set_index("date", inplace=True)
    monotonicity_df.index.name = None

    return monotonicity_df


def neutralize_factors(
    panel: pd.DataFrame,
    market_value_col: str = "total_market_value",
    industry_col: str = "industry",
) -> pd.DataFrame:
    """
    对面板中的因子做行业内市值中性化处理（可供其它 IC 计算流程调用）。

    在每个截面 (date) 内，再按行业列分组，在每个 (date, industry) 组中：
    使用对数市值 log(market_value_col) 对因子做一元线性回归，
    返回回归残差作为中性化后的因子值，从而同时控制行业和市值暴露。

    参数
    ----
    panel : pd.DataFrame
        包含列:
            - date
            - code
            - 若干因子列
            - 行业列（默认为 "industry"）
            - 市值列（"total_market_value" 或 "tradable_market_value"）
    market_value_col : str, 默认 "total_market_value"
        用于中性化的市值列名。
        通常使用 "total_market_value"；
        仅在主动测试流通市值对部分因子的效果时，调用方显式传入 "tradable_market_value"。
    industry_col : str, 默认 "industry"
        行业类别列名。

    返回
    ----
    pd.DataFrame
        仅包含中性化后因子列的 DataFrame，索引与输入 panel 对齐。
    """
    if market_value_col not in panel.columns or industry_col not in panel.columns:
        return panel

    # 因子列：排除基础标识列、标签列、行业列、市值列
    factor_cols = [
        col
        for col in panel.columns
        if col not in ["date", "code", "label", industry_col, market_value_col]
    ]
    if not factor_cols:
        # 没有任何可中性化的因子列时，直接返回原 panel 副本
        return panel

    # 按日期截面处理
    for date, group in panel.groupby("date"):
        if len(group) < 2:
            # 截面样本过少无法回归，跳过该日
            continue

        # 在截面内按行业分组
        for _, industry_group in group.groupby(industry_col):
            if len(industry_group) < 2:
                # 行业组样本过少无法回归，跳过该组
                continue

            # 市值必须为正，才能取对数
            mv_values = industry_group[market_value_col].to_numpy(dtype=float)
            if np.any(mv_values <= 0.0):
                # 若该行业组存在非正市值，跳过该组
                continue

            # 设计矩阵：常数项 + log(市值)
            x_log_mv = np.log(mv_values)
            X = np.column_stack([np.ones_like(x_log_mv, dtype=float), x_log_mv])

            # 对每个因子做一元线性回归，残差即为中性化后的因子值
            for factor in factor_cols:
                y = industry_group[factor].to_numpy(dtype=float)
                # 若该因子在该组内全部相同，则残差为 0，中性化后没有信息，直接赋值为 0
                if np.all(np.isnan(y)) or np.all(y == y[0]):
                    residual = np.full_like(y, np.nan, dtype=float)
                else:
                    beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
                    fitted = X @ beta
                    residual = y - fitted

                panel.loc[industry_group.index, factor] = residual

    return panel
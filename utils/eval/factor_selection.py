# utils/eval/factor_selection.py

"""
多因子选择与筛选工具模块

本模块提供：
1. orthogonalize_factors
   - 在每个截面(date)内，对因子做“回归残差式”正交化

2. filter_ic_by_corr_hierarchical
   - 基于因子 IC 序列之间的 Spearman 相关性
   - 使用层次聚类做去重，每簇只保留一个代表因子
   - 在控制台 print 被剔除的 ic 列名，外层无需关心

3. full_factor_filter_pipeline
   - 直接从原始面板 panel 出发，串联：
        行业/市值中性化 -> 因子正交化 -> 计算 IC -> IC 相关性聚类去重
   - 评估器中可以一行调用：
        ic = full_factor_filter_pipeline(panel, threshold=0.8)
"""

from __future__ import annotations

from typing import List, Dict

import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch

def orthogonalize_factors(
    panel: pd.DataFrame,
    method: str = "regression",
) -> pd.DataFrame:
    """
    在每个截面(date)内对因子做正交化，缓解因子之间的多重共线性。

    实现方式：回归残差法（regression based orthogonalization）

    对于某个截面内的因子矩阵 F = [f1, f2, ..., fk]:
        - 保留第一个因子作为基准（f1' = f1，截面内已中心化）
        - 对 i > 1，用 [f1', f2', ..., f(i-1)'] 回归 fi，取残差作为 fi'

    参数
    ----
    panel : pd.DataFrame
        包含列: date, code, label, 以及若干因子列。
    method : str, 默认 "regression"
        当前仅支持 "regression"，保留参数以便未来扩展。

    返回
    ----
    pd.DataFrame
        返回一个新的 DataFrame，其中因子列已经在每个截面内正交化，
        其它列（date, code, label, 行业、市值列等）保持不变。
    """
    if method.lower() != "regression":
        raise ValueError("orthogonalize_factors 目前仅支持 method='regression'")

    # 非因子列：保持不动
    exclude_cols = {
        "date",
        "code",
        "label",
        "industry",
        "total_market_value",
        "tradable_market_value",
    }
    factor_cols: List[str] = [c for c in panel.columns if c not in exclude_cols]

    if not factor_cols:
        # 没有因子列，直接返回拷贝
        return panel

    # 按日期截面进行正交化，防止未来信息泄露
    for date, group in panel.groupby("date"):
        if len(group) < 2:
            # 样本太少无法做稳定回归，跳过该日
            continue

        X_raw = group[factor_cols].astype(float)

        # 截面内均值中心化（正交化的必要步骤，与行业/市值中性化不冲突）
        X_raw = X_raw - X_raw.mean()

        # 用于存放正交化后的因子
        orthogonalized = pd.DataFrame(index=X_raw.index, columns=factor_cols, dtype=float)

        # 逐个因子按顺序做回归残差正交化
        for i, factor in enumerate(factor_cols):
            y = X_raw[factor].to_numpy()

            # 第一个因子：作为基准因子，直接保留（已中心化）
            if i == 0:
                orthogonalized[factor] = y
                continue

            # 取前面已经正交化完的因子作为自变量矩阵
            preceding_factors = factor_cols[:i]
            X_prev = orthogonalized[preceding_factors].to_numpy(dtype=float)

            # 若前面没有有效因子（理论上 i>0 时不会发生），直接保留当前因子
            if X_prev.shape[1] == 0:
                orthogonalized[factor] = y
                continue

            # 构造有效样本 mask（排除 NaN）
            mask = ~(np.isnan(X_prev).any(axis=1) | np.isnan(y))
            if mask.sum() < 2:
                # 有效样本过少，直接保留原值
                orthogonalized[factor] = y
                continue

            X_prev_clean = X_prev[mask]
            y_clean = y[mask]

            # 样本数必须大于自变量个数才能稳定回归
            if X_prev_clean.shape[0] <= X_prev_clean.shape[1]:
                orthogonalized[factor] = y
                continue

            # 使用最小二乘回归，取残差作为正交化后的因子值
            try:
                beta, _, _, _ = np.linalg.lstsq(X_prev_clean, y_clean, rcond=None)
                residual = y_clean - X_prev_clean @ beta

                # 先全部设为原值，再用残差覆盖有效样本位置，避免引入 NaN
                y_orth = y.copy()
                y_orth[mask] = residual
                orthogonalized[factor] = y_orth
            except np.linalg.LinAlgError:
                # 矩阵奇异等问题，回退为原值
                orthogonalized[factor] = y

        # 将当前截面正交化后的因子覆盖回结果
        for col in factor_cols:
            panel.loc[group.index, col] = orthogonalized[col].to_numpy()

    return panel


def filter_ic_by_corr_hierarchical(
    ic: pd.DataFrame,
    threshold: float = 0.8,
    use_ic_mean: bool = True,
) -> pd.DataFrame:
    """
    基于 IC 序列相关性的层次聚类去重函数。

    使用方式
    --------
    在评估流程中一行调用，例如：
        ic = filter_ic_by_corr_hierarchical(ic, threshold=0.8)

    参数
    ----
    ic : pd.DataFrame
        IC 时间序列 DataFrame，一般为 calculate_ic 的输出，
        列名通常为 "ic_<factor_name>"。
    threshold : float, 默认 0.8
        绝对相关性阈值。内部通过构造距离矩阵 d = 1 - |corr|，
        并以 (1 - threshold) 作为聚类切割距离。
        例如 threshold=0.8 => 切割距离为 0.2。
    use_ic_mean : bool, 默认 True
        是否使用「IC 均值」作为簇内代表因子选择标准。
        - True  : 在每个簇中选择 IC 均值最高的因子；
        - False : 在每个簇中按因子名排序，取第一个。

    返回
    ----
    pd.DataFrame
        仅保留通过层次聚类筛选后的 IC 时间序列 DataFrame，
        列为被保留的 "ic_<factor_name>"，索引与输入 ic 对齐。

    说明
    ----
    - 函数内部不会修改输入 ic，只会基于列名筛选并返回一个新的 DataFrame；
    - 会通过 print 打印出被剔除的因子列名列表，便于使用者查看。
    """
    # 空表或无列时直接返回
    if ic.empty or ic.shape[1] == 0:
        return ic

    # 提取因子名（去掉前缀 "ic_"）
    factor_names: List[str] = [col.replace("ic_", "") for col in ic.columns]

    # 计算 IC 序列之间的 Spearman 相关性矩阵
    corr_matrix: pd.DataFrame = ic.corr(method="spearman")

    # 构建距离矩阵：d_ij = 1 - |corr_ij|
    distance_matrix = 1.0 - np.abs(corr_matrix.values)

    # 使用平均链接（average linkage）做层次聚类
    linkage_matrix = sch.linkage(distance_matrix, method="average")

    # 按 (1 - threshold) 的距离切割聚类树，得到簇 ID
    cluster_ids = sch.fcluster(
        linkage_matrix,
        t=1.0 - threshold,
        criterion="distance",
    )

    # 将每个因子分配到对应簇
    clusters: Dict[int, List[str]] = {}
    for idx, factor in enumerate(factor_names):
        cid = int(cluster_ids[idx])
        clusters.setdefault(cid, []).append(factor)

    selected_factors: List[str] = []
    removed_factors: List[str] = []

    # 在每个簇中选择代表因子
    for _, cluster_factors in clusters.items():
        if len(cluster_factors) == 1:
            selected_factors.append(f"ic_{cluster_factors[0]}")
            continue

        if use_ic_mean:
            # 使用各因子 IC 序列的均值作为代表性指标
            factor_ic_cols = [f"ic_{f}" for f in cluster_factors]
            ic_means = ic[factor_ic_cols].mean()
            best_factor_col = ic_means.idxmax()  # 形如 "ic_xxx"
            best_factor = best_factor_col.replace("ic_", "")
        else:
            # 按因子名字典序选择第一个
            best_factor = sorted(cluster_factors)[0]

        # 簇内代表因子
        selected_factors.append(f"ic_{best_factor}")

        # 其余因子视为冗余，加入剔除列表
        for f in cluster_factors:
            if f != best_factor:
                removed_factors.append(f"ic_{f}")

    # 打印被剔除的因子列名
    if removed_factors:
        print("根据 IC 序列相关性层次聚类剔除的因子列:", removed_factors)
    else:
        print("根据 IC 序列相关性层次聚类，没有因子被剔除。")

    # 返回仅包含被保留列的 IC DataFrame
    # 注意：不改变列顺序，只按 selected_factors 中的顺序返回
    return ic[selected_factors]
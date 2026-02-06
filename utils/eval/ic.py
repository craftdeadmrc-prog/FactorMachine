# utils/eval/ic.py
# IC 计算模块（纯计算逻辑，不涉及 IO 或业务调度）

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, Any


def calculate_ic(
    panel: pd.DataFrame,
    method: str = "spearman",
) -> pd.DataFrame:
    """
    计算因子 IC 时间序列（按日期逐截面相关性）。

    参数
    ----
    panel : DataFrame
        行索引为日期，列为 date，code，若干个factor，label。
    method : str
        相关性方法，"spearman" 表示 Rank IC，"pearson" 表示普通相关系数。

    返回
    ----
    pd.DataFrame
        索引为日期的若干个因子IC的时间序列，列名为"ic_因子名"。
    """    
    # 获取因子列名（排除date、code、label列）
    factors = [col for col in panel.columns if col not in ["date", "code", "label"]]
    
    # 用于存储结果的列表
    results = []
    
    # 按日期分组计算IC
    for date, group in panel.groupby("date"):
        date_result = {"date": date}
        
        # 计算每个因子的IC
        for factor in factors:
            # 提取因子值和标签值
            factor_series = group[factor]
            label_series = group["label"]
            
            # 删除缺失值
            mask = ~(factor_series.isna() | label_series.isna())
            x = factor_series[mask].to_numpy(dtype=float)
            y = label_series[mask].to_numpy(dtype=float)
            
            # 如果有效数据少于2个，无法计算相关性
            if len(x) < 2:
                ic = np.nan
            else:
                # 根据method选择相关性计算方法
                if method.lower() == "spearman":
                    ic, _ = stats.spearmanr(x, y)
                elif method.lower() == "pearson":
                    ic, _ = stats.pearsonr(x, y)
                else:
                    raise ValueError(f"不支持的method: {method}，请使用'spearman'或'pearson'")
            
            # 将IC值存入结果，使用"ic_因子名"作为列名
            date_result[f"ic_{factor}"] = float(ic)
        
        results.append(date_result)
    
    # 将结果转换为DataFrame
    if results:
        ic_df = pd.DataFrame(results)
        ic_df.set_index("date", inplace=True)
        ic_df.index.name = None  # 移除索引名称
    else:
        # 如果没有结果，创建空的DataFrame，列名为各个因子的IC列名
        ic_columns = [f"ic_{factor}" for factor in factors]
        ic_df = pd.DataFrame(columns=ic_columns)
    return ic_df


import pandas as pd
import numpy as np

def calculate_ic_summary(ic_pd: pd.DataFrame) -> pd.DataFrame:
    """
    根据 IC 时间序列计算累积统计指标（逐步计算，避免未来信息泄露）。

    指标包括
    ----------
    {ic}_mean        : 累积平均 IC
    {ic}_std         : 累积 IC 标准差
    {ic}_t_value     : 累积 t 统计量（用于大致判断显著性）
    {ic}_ic_ir       : 累积 IC 信息比率（mean / std）
    {ic}_positive_ratio : 累积 IC 为正的比例

    参数
    ----
    ic_pd : pd.DataFrame
        IC 时间序列，索引为日期，列为各个因子的IC值（列名如"ic_ma_26"）。

    返回
    ----
    pd.DataFrame
        索引为日期，列为各个因子的累积统计指标。
    """
    if len(ic_pd) == 0:
        return pd.DataFrame()
    
    # 初始化结果字典
    result_dict = {}
    
    # 为每个IC列创建累积统计序列
    for ic_col in ic_pd.columns.tolist():
        # 获取当前IC序列
        ic_series = ic_pd[ic_col]
        
        # 初始化累积统计序列
        mean_series = []
        std_series = []
        t_value_series = []
        ic_ir_series = []
        positive_ratio_series = []
        
        # 逐步计算累积统计量，至少20日
        for i in range(20, len(ic_series) + 1):
            # 获取当前累积数据
            cumulative_data = ic_series.iloc[:i].dropna()
            n = len(cumulative_data)
            
            if n == 0:
                # 如果没有有效数据
                mean_series.append(np.nan)
                std_series.append(np.nan)
                t_value_series.append(np.nan)
                ic_ir_series.append(np.nan)
                positive_ratio_series.append(np.nan)
            else:
                # 计算累积统计量
                mean_ic = cumulative_data.mean()
                std_ic = cumulative_data.std()
                
                # 避免除零错误
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
        
        # 将结果添加到字典中，使用{ic}_stat格式的列名
        result_dict[f"{ic_col}_mean"] = mean_series
        result_dict[f"{ic_col}_std"] = std_series
        result_dict[f"{ic_col}_t_value"] = t_value_series
        result_dict[f"{ic_col}_ic_ir"] = ic_ir_series
        result_dict[f"{ic_col}_positive_ratio"] = positive_ratio_series
    ic_pd = ic_pd[19:]
    # 创建结果DataFrame
    result_df = pd.DataFrame(result_dict, index=ic_pd.index)
    
    return result_df
# utils/eval/factor_evaluator.py
import os
from pathlib import Path
from typing import Optional, List

import pandas as pd

from utils.eval.labels import build_forward_return_label
from utils.eval.ic import calculate_ic, calculate_ic_summary, calculate_monotonicity, neutralize_factors
from utils.eval.factor_selection import orthogonalize_factors, filter_ic_by_corr_hierarchical
from utils.eval.outlier import cap_outliers
from core.storage import load_dataframe, save_dataframe


class FactorEvaluator:

    def __init__(self, market_type: str) -> None:
        self.market_type = market_type
        self.factor_results_dir = os.path.join("factor_results")
        self.factor_eval_dir = os.path.join("factor_eval")
        os.makedirs(self.factor_eval_dir, exist_ok=True)

    def evaluate_factor(
        self,
        custom_factors: Optional[List[str]] = None,
        horizon: int = 1,
        log_return: bool = True,
    ) -> pd.DataFrame:
        if custom_factors:
            factors = set(custom_factors)
        else:
            base = Path(self.factor_results_dir)
            factors = []
            for root, _, files in os.walk(base):
                for file in files:
                    if not file.endswith(".parquet"):
                        continue
                    factors.append(str.removesuffix(file, ".parquet"))
        # 1. 基础数据
        base_data = load_dataframe(self.market_type)[["date", "code", "close"]]
        # 2. 标签（未来收益）
        label = build_forward_return_label(
            df=base_data,
            horizon=horizon,
            log_return=log_return,
        )
        base_data = base_data.drop(columns="close")
        panel = base_data.join(label)
        # 3. 因子序列
        for factor in factors:
            factor = load_dataframe(factor, self.factor_results_dir)
            panel = panel.join(factor)
        # 4. 异常值处理
        panel = cap_outliers(panel)
        # 5. 计算 IC 序列
        ic = calculate_ic(
            panel=panel,
            method="spearman",
        ).dropna()
        ic = neutralize_factors(ic)

        # 1. 因子间正交化
        ic = orthogonalize_factors(ic)
        # 3. 基于 IC 相关性的层次聚类去重
        ic = filter_ic_by_corr_hierarchical(ic)
        # 6. 计算 IC 汇总
        ic_summary = calculate_ic_summary(ic)
        
        # 7. 计算单调性
        monotonicity = calculate_monotonicity(panel)
        monotonicity.columns = [f"ic_{col}_monotonicity" for col in monotonicity.columns]
        ic_summary = ic_summary.join(monotonicity)
        # 输出结果
        # out_table = f"{self.market_type}_factors"
        # save_dataframe(ic_summary, out_table, self.factor_eval_dir)
        for ic_col in factors:
            ic_col = str.removeprefix(ic_col,f"{self.market_type}_")
            out_table = f"{self.market_type}_factors_{ic_col}"
            df = ic_summary[[f"ic_{ic_col}_mean",f"ic_{ic_col}_std",f"ic_{ic_col}_t_value",f"ic_{ic_col}_ic_ir",f"ic_{ic_col}_positive_ratio",f"ic_{ic_col}_monotonicity"]]
            save_dataframe(df, out_table, self.factor_eval_dir)
            
        return ic_summary
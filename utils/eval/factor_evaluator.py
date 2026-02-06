# utils/eval/evaluator.py
import os
from pathlib import Path
from typing import Optional,List

import pandas as pd

from utils.eval.labels import build_forward_return_label
from utils.eval.ic import calculate_ic, calculate_ic_summary
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
                    factors.append(str.removesuffix(file,".parquet"))
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
        # 5. 计算 IC 序列及汇总
        ic = calculate_ic(
            panel=panel,
            method="spearman",
        ).dropna()
        ic_summary = calculate_ic_summary(ic)
        print(ic_summary)
        out_table_name = f"{self.market_type}_factors"
        save_dataframe(ic_summary,out_table_name, self.factor_eval_dir)

        return ic_summary

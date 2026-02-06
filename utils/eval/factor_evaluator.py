# utils/eval/evaluator.py
# 单因子评估模块（只负责 IC 相关统计与结果存储）
import os
from pathlib import Path
from typing import Optional,List

import pandas as pd

from utils.eval.labels import build_forward_return_label
from utils.eval.ic import calculate_ic, calculate_ic_summary
from core.storage import load_dataframe, save_dataframe

class FactorEvaluator:
    """
    单因子评估器（严格单因子、单入口）。

    只做：
    - 基础数据加载
    - 单因子加载
    - 标签构造（未来收益）
    - 面板转换
    - IC 计算与统计
    - 结果写入 parquet

    不做：
    - 多因子循环（由外部多因子脚本调用）
    - 任意形式的回测（回测必须走 utils/backtest 模块）
    """

    def __init__(self, market_type: str) -> None:
        self.market_type = market_type
        # factor_eval/ 存因子 parquet
        self.factor_results_dir = os.path.join("factor_results")
        self.factor_eval_dir = os.path.join("factor_eval")
        os.makedirs(self.factor_eval_dir, exist_ok=True)

    # ---------- 单因子评估主流程 ----------

    def evaluate_factor(
        self,
        custom_factors: Optional[List[str]] = None,
        horizon: int = 1,
        log_return: bool = True,
    ) -> pd.DataFrame:
        """
        评估单个因子在指定 horizon 上的表现（仅做 IC 分析）。

        参数
        ----
        factors : List[str]
            因子名称。
        horizon : int, default 1
            预测期（未来收益的 horizon）。
        log_return : bool, default True
            标签是否使用对数收益。
        output_dir : str, default "factor_eval"
            评估结果 parquet 输出目录。

        返回
        ----
        dict
            {
                "factor_name": str,
                "horizon": int,
                "ic_summary": pd.DataFrame
            }
        """
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
        # 7. 保存报告到 parquet（每个因子一个文件，便于多因子脚本汇总）
        # 统一由 core.storage 控制压缩等细节
        out_table_name = f"{self.market_type}_factors"
        save_dataframe(ic_summary,out_table_name, self.factor_eval_dir)

        # 8. 返回结果字典，方便上层直接使用
        return ic_summary

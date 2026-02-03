# utils/eval/evaluator.py
# 因子评估模块（内部使用，负责调度和汇总）

from __future__ import annotations

import os
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.storage import load_dataframe

import pandas as pd

# 列筛选映射表：评估时只加载必要字段，避免读入换手率等无关列
COLUMN_MAPPING = {
    "date": "date",
    "code": "code",
    "close": "close",
    "open": "open",
    "high": "high",
    "low": "low",
    "volume": "volume",
    "amount": "amount",
}

from core.config import MAX_CONCURRENCY
from utils.eval.labels import build_forward_return_label
from utils.eval.ic import calculate_ic_series, calculate_ic_summary


class FactorEvaluator:
    def __init__(self, market_type: str):
        self.market_type = market_type
        # 因子结果目录名与现有工程保持一致：项目根下 factor_results
        self.factor_results_dir = os.path.join("factor_results")
        if not os.path.isdir(self.factor_results_dir):
            raise FileNotFoundError(f"因子结果目录不存在: {self.factor_results_dir}")
        self.max_workers = MAX_CONCURRENCY

    # 评估阶段需要的列统一在这里控制
    _column_mapping = {
        "date": "date",
        "code": "code",
        "close": "close",
        "open": "open",
        "high": "high",
        "low": "low",
        "volume": "volume",
        "amount": "amount",
    }

    def load_base_data(self, use_only: Optional[List[str]] = None) -> pd.DataFrame:
        """
        加载基础市场数据，只加载必要列。
        表名 = market_type，对应 DATA_PATH/{market_type}.parquet。
        """
        df = load_dataframe(self.market_type)

        cols_to_load = use_only or list(self._column_mapping.keys())
        df = df[cols_to_load]

        required_cols = ["date", "code", "close"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"基础数据必须包含列: {col}")
        return df

    def load_factor(self, factor_name: str) -> Optional[pd.Series]:
        """
        加载单个因子数据。
        表名 = {market_type}_{factor_name}
        实际 parquet 由 core.storage 决定路径（DATA_PATH/{表名}.parquet）。
        """
        # 仍然保留 factor_results 目录存在性判断，兼容你之前的约定
        file_path = os.path.join(
            self.factor_results_dir, f"{self.market_type}_{factor_name}.parquet"
        )
        if not os.path.exists(file_path):
            return None

        df = load_dataframe(f"{self.market_type}_{factor_name}")
        if df is None or df.empty:
            return None

        if isinstance(df, pd.DataFrame):
            if df.shape[1] == 1:
                return df.iloc[:, 0]
            elif factor_name in df.columns:
                return df[factor_name]
        return df

    def get_all_factor_names(self) -> List[str]:
        """
        从因子结果目录中推断所有因子名称。
        文件命名约定：{market_type}_{factor_name}.parquet
        """
        factor_names: List[str] = []
        prefix = f"{self.market_type}_"
        suffix = ".parquet"

        for filename in os.listdir(self.factor_results_dir):
            if filename.startswith(prefix) and filename.endswith(suffix):
                name = filename[len(prefix) : -len(suffix)]
                if name:
                    factor_names.append(name)

        return factor_names

    # ---------------- 面板转换与原子评估 ----------------

    def _to_panel(self, series: pd.Series, base_data: pd.DataFrame) -> pd.DataFrame:
        """
        将一维因子/标签序列转换为 date*code 面板。

        要求：
            - series 的长度与 base_data 行数一致。
        """
        if len(series) != len(base_data):
            raise ValueError("series 长度必须与基础数据行数一致")

        df = pd.DataFrame(
            {
                "date": base_data["date"].values,
                "code": base_data["code"].values,
                "value": series.values,
            }
        )
        panel = df.pivot(index="date", columns="code", values="value")
        return panel

    def _evaluate_single_factor_single_horizon(
        self,
        factor_name: str,
        horizon: int,
        base_data: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        原子评估单元：评估一个因子在一个 horizon 上的表现。
        不做任何 IO 操作。

        返回:
            {
                "factor": str,
                "horizon": int,
                "ic_series": pd.Series,
                "ic_summary": dict,
            }
        """
        factor_series = self.load_factor(factor_name)
        label_series = build_forward_return_label(
            data_df=base_data,
            horizon=horizon,
            log_return=False,
        )

        factor_panel = self._to_panel(factor_series, base_data)
        label_panel = self._to_panel(label_series, base_data)

        ic_series = calculate_ic_series(
            factor_panel=factor_panel,
            label_panel=label_panel,
            method="spearman",
        )
        ic_summary = calculate_ic_summary(ic_series)

        return {
            "factor": factor_name,
            "horizon": horizon,
            "ic_series": ic_series,
            "ic_summary": ic_summary,
        }

    # ---------------- 多因子多 horizon 评估 ----------------

    def evaluate_factors(
        self,
        factor_names: Optional[List[str]] = None,
        horizons: List[int] = (1, 5, 10),
        parallel: bool = True,
    ) -> Dict[str, Dict[int, Dict[str, Any]]]:
        """
        评估多个因子在多个预测期上的表现。

        参数:
            factor_names : 因子列表，None 表示评估所有可用因子
            horizons     : 预测期列表
            parallel     : 是否使用多线程

        返回:
            results[factor_name][horizon] = {
                "factor": ...,
                "horizon": ...,
                "ic_series": ...,
                "ic_summary": ...,
            }
        """
        base_data = self.load_base_data()

        if factor_names is None:
            factor_names = self.get_all_factor_names()

        results: Dict[str, Dict[int, Dict[str, Any]]] = {}

        if not parallel:
            for factor_name in factor_names:
                for horizon in horizons:
                    res = self._evaluate_single_factor_single_horizon(
                        factor_name=factor_name,
                        horizon=horizon,
                        base_data=base_data,
                    )
                    results.setdefault(factor_name, {})[horizon] = res
            return results

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for factor_name in factor_names:
                for horizon in horizons:
                    fut = executor.submit(
                        self._evaluate_single_factor_single_horizon,
                        factor_name,
                        horizon,
                        base_data,
                    )
                    futures[fut] = (factor_name, horizon)

            for fut in as_completed(futures):
                factor_name, horizon = futures[fut]
                res = fut.result()
                results.setdefault(factor_name, {})[horizon] = res

        return results

    # ---------------- 汇总报告 ----------------

    def generate_report(
        self,
        results: Dict[str, Dict[int, Dict[str, Any]]],
    ) -> pd.DataFrame:
        """
        将评估结果汇总为 DataFrame，便于导出与可视化。

        列包括：
            factor, horizon, mean_ic, std_ic, t_value,
            ic_ir, positive_ratio, valid_periods
        """
        rows = []

        for factor_name, horizon_dict in results.items():
            for horizon, res in horizon_dict.items():
                summary = res["ic_summary"]
                rows.append(
                    {
                        "factor": factor_name,
                        "horizon": horizon,
                        "mean_ic": summary["mean_ic"],
                        "std_ic": summary["std_ic"],
                        "t_value": summary["t_value"],
                        "ic_ir": summary["ic_ir"],
                        "positive_ratio": summary["positive_ratio"],
                        "valid_periods": summary["valid_periods"],
                    }
                )

        report = pd.DataFrame(rows)
        if not report.empty:
            report = report.sort_values(
                ["horizon", "mean_ic"],
                ascending=[True, False],
            )

        return report

    def run_evaluation(
        self,
        factor_names: Optional[List[str]] = None,
        horizons: List[int] = (1, 5, 10),
        parallel: bool = True,
    ) -> Tuple[Dict[str, Dict[int, Dict[str, Any]]], pd.DataFrame]:
        """
        运行完整评估流程，返回：
            - 详细结果字典
            - 汇总报告 DataFrame
        """
        results = self.evaluate_factors(
            factor_names=factor_names,
            horizons=list(horizons),
            parallel=parallel,
        )
        report = self.generate_report(results)
        return results, report


def run_factor_evaluation(
    market_type: str,
    factor_names: Optional[List[str]] = None,
    horizons: List[int] = (1, 5, 10),
    parallel: bool = True,
) -> Tuple[Dict[str, Dict[int, Dict[str, Any]]], pd.DataFrame]:
    """
    外部便捷入口：直接运行因子评估。

    参数:
        market_type : 市场类型
        factor_names: 因子名称列表，None 表示全部
        horizons    : 预测期列表
        parallel    : 是否并行

    返回:
        (results, report)
    """
    evaluator = FactorEvaluator(market_type=market_type)
    return evaluator.run_evaluation(
        factor_names=factor_names,
        horizons=list(horizons),
        parallel=parallel,
    )
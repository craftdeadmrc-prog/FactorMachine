# utils/eval/evaluator.py
# 因子评估模块（内部使用，负责调度和汇总）

from __future__ import annotations

import os
import sys
import inspect
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

# 确保项目根目录在 sys.path 中
_script_path = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(_script_path)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.config import MAX_CONCURRENCY
from utils.eval import labels, ic


class FactorEvaluator:
    """
    因子评估器：负责加载数据和因子，进行多线程评估并汇总结果。

    特点：
        - 只负责评估调度，不进行文件创建
        - 并发上限由 core.config.MAX_CONCURRENCY 控制
        - 返回结构化结果，便于导出和可视化
    """

    def __init__(self, market_type: str):
        self.market_type = market_type
        self.project_root = _project_root
        self.data_dir = os.path.join(self.project_root, "data")
        self.factor_results_dir = os.path.join(self.project_root, "factor_results")

        if not os.path.isdir(self.factor_results_dir):
            raise FileNotFoundError(f"因子结果目录不存在: {self.factor_results_dir}")

        self.max_workers = MAX_CONCURRENCY

    # ---------------- 基础数据与因子加载 ----------------

    def load_base_data(self) -> pd.DataFrame:
        """
        加载基础市场数据，要求路径：
            data/{market_type}.parquet
        且至少包含列：date, code, close
        """
        data_path = os.path.join(self.data_dir, f"{self.market_type}.parquet")
        if not os.path.isfile(data_path):
            raise FileNotFoundError(f"市场数据文件不存在: {data_path}")
        df = pd.read_parquet(data_path)
        return df

    def load_factor(self, factor_name: str) -> pd.Series:
        """
        加载单个因子数据，要求路径：
            factor_results/{market_type}_{factor_name}.parquet
        返回与基础数据行数对齐的一维 Series。
        """
        file_path = os.path.join(
            self.factor_results_dir, f"{self.market_type}_{factor_name}.parquet"
        )
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"因子文件不存在: {file_path}")

        factor_df = pd.read_parquet(file_path)
        if isinstance(factor_df, pd.DataFrame):
            if factor_df.shape[1] == 1:
                series = factor_df.iloc[:, 0]
            else:
                if factor_name in factor_df.columns:
                    series = factor_df[factor_name]
                else:
                    raise ValueError(f"因子文件 {file_path} 列不唯一且不包含列名 {factor_name}")
        else:
            series = factor_df

        return series

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
            - series 的 index 与 base_data.index 一一对应。
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
        label_series = labels.build_forward_return_label(
            data_df=base_data,
            horizon=horizon,
            log_return=False,
        )

        factor_panel = self._to_panel(factor_series, base_data)
        label_panel = self._to_panel(label_series, base_data)

        ic_series = ic.calculate_ic_series(
            factor_panel=factor_panel,
            label_panel=label_panel,
            method="spearman",
        )
        ic_summary = ic.calculate_ic_summary(ic_series)

        result: Dict[str, Any] = {
            "factor": factor_name,
            "horizon": horizon,
            "ic_series": ic_series,
            "ic_summary": ic_summary,
        }
        return result

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
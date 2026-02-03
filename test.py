#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import numpy as np
import pandas as pd
from typing import List

from utils.symbol.loader import FactorLoader
from utils.eval.evaluator import run_factor_evaluation


def load_all_factors(market_type: str) -> pd.DataFrame:
    """
    使用 FactorLoader 将所有已经计算好的因子加载为一个 DataFrame

    返回：每行对应 (date, code) 一条观测，数值列为所有因子，另外包含 code, date 两列
    """
    loader = FactorLoader(market_type=market_type)
    loader.load_parquet()  # 初始化 working_df & 加载已有因子

    all_factors = loader.get_all_factor_names()
    results = {}

    for factor in all_factors:
        series = loader.load_factor(factor)
        if series is not None:
            # loader.load_factor 返回的 Series 索引与 parquet 原始数据对齐
            results[factor] = series.values

    df = pd.DataFrame(results)
    df["code"] = loader.working_df["code"].values
    df["date"] = loader.working_df["date"].values
    return df


def compute_factor_correlation(
    df: pd.DataFrame,
    output_file: str | None = None
) -> pd.DataFrame | None:
    """
    计算因子之间的截面相关性（Spearman），按日独立计算。

    返回：
        多层索引 DataFrame，外层 index 为 date，内层为因子；列为因子名。
    """
    # 只保留数值型因子列
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    numeric_cols = [c for c in numeric_cols if c not in ["code", "date"]]

    if len(numeric_cols) < 2:
        print("没有足够的数值型因子进行相关性分析")
        return None

    corr_matrices = {}
    dates = sorted(df["date"].unique())

    for dt in dates:
        day_df = df[df["date"] == dt]
        if day_df.empty:
            continue
        # 截面 rank 相关性
        corr = day_df[numeric_cols].corr(method="spearman")
        corr_matrices[dt] = corr

    if not corr_matrices:
        print("无法计算任何日期的相关性矩阵")
        return None

    corr_panel = pd.concat(
        corr_matrices,
        axis=0,
        keys=corr_matrices.keys(),
        names=["date", "factor"]
    )

    if output_file:
        corr_panel.to_csv(output_file)
        print(f"因子相关性矩阵已保存到 {output_file}")

    return corr_panel


def evaluate_factors_with_ic(
    market_type: str,
    factor_names: List[str] | None = None,
    horizons: List[int] = [1, 5, 10]
):
    """
    调用现有 FactorEvaluator 完成因子 IC 评估，返回 (results, report)
    """
    print(f"\n开始对 {market_type} 市场进行 IC 评估 ...")
    results, report = run_factor_evaluation(
        market_type=market_type,
        factor_names=factor_names,
        horizons=horizons,
        parallel=True,
    )
    return results, report


def main():
    parser = argparse.ArgumentParser(description="因子相关性分析与IC评估工具")
    parser.add_argument("--market", default="ashare", help="市场类型 (如 ashare, fund)")
    parser.add_argument("--correlation", action="store_true", help="计算因子间截面相关性")
    parser.add_argument("--eval", action="store_true", help="进行因子IC评估")
    parser.add_argument(
        "--horizons",
        nargs="*",
        type=int,
        default=[1, 5, 10],
        help="IC评估的预测期列表"
    )
    parser.add_argument(
        "--output-corr",
        default="factor_corr.csv",
        help="相关性矩阵输出文件路径"
    )

    args = parser.parse_args()
    market_type = args.market

    if args.correlation:
        print(f"加载 {market_type} 市场因子数据 ...")
        df_factors = load_all_factors(market_type)
        print(f"共有 {len(df_factors)} 条记录，{len(df_factors.columns) - 2} 个因子")

        corr_panel = compute_factor_correlation(
            df_factors,
            output_file=args.output_corr,
        )
        if corr_panel is not None:
            print("\n相关性矩阵样例（前5行）:")
            print(corr_panel.head(5))

    if args.eval:
        results, report = evaluate_factors_with_ic(
            market_type=market_type,
            horizons=args.horizons,
        )
        print("\nIC评估汇总报告:")
        print(report)

        report_path = f"factor_ic_report_{market_type}.csv"
        report.to_csv(report_path, index=False)
        print(f"IC汇总报告已保存到 {report_path}")


if __name__ == "__main__":
    main()
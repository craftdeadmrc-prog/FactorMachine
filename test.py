#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Max Drawdown 因子计算验证脚本
-------------------------------------------------------------------
目标：
- 用 core.storage.load_dataframe 从 data/ashare.parquet 读取市场数据；
- 按因子定义 max(div(sub(cummax(close), close), cummax(close))) 手动计算一遍；
- 再从因子结果文件（例如 factor_results/ashare_max_drawdown.parquet
  或你自定义的 factors_results/max_drawdown.parquet）加载结果；
- 对比两者是否一致。

使用方法：
1. 先在项目根目录运行 main.py 计算因子（你可以只算 max_drawdown）：
   示例（按你自己的方式改）：
       python main.py --market ashare --factors --merge --concurrency 4
   确保已经生成相应的 max_drawdown 因子 parquet 文件。

2. 在项目根目录运行本脚本：
       python test_max_drawdown.py
-------------------------------------------------------------------
"""

import os
import sys
import pandas as pd
from core.config import DATA_PATH
from core.storage import load_dataframe


# ----------------------------------------------------------------------
# 1. 手动计算 max_drawdown
# ----------------------------------------------------------------------
def compute_max_drawdown(df: pd.DataFrame) -> pd.Series:
    """
    按照因子定义：
        max(div(sub(cummax(close), close), cummax(close)))
    从 data/ashare.parquet 中手动计算每日最大回撤。

    参数
    ----
    df : DataFrame
        至少包含 ['code', 'date', 'close'] 三列的长表数据。

    返回
    ----
    pd.Series
        索引为 date，值为当日所有股票中的最大回撤比例（0~1）。
    """
    df = df.copy()

    # 确保日期类型正确，并按 code + date 排序（保证 cummax 逻辑与时间一致）
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values(["code", "date"])

    # 对每只股票计算累计最高价 cummax(close)
    df["cummax"] = df.groupby("code")["close"].cummax()

    # 计算回撤比例 (cummax(close) - close) / cummax(close)
    # 与 pointwise/div 中的实现保持一致：分母加一个很小的数防止除零
    df["drawdown_ratio"] = (df["cummax"] - df["close"]) / (df["cummax"] + 1e-8)

    # 按日期对截面取 max -> max(div(sub(cummax(close), close), cummax(close)))
    max_dd = df.groupby("date")["drawdown_ratio"].max()

    # 按日期排序后返回
    return max_dd.sort_index()


# ----------------------------------------------------------------------
# 2. 加载因子结果（兼容 factor_results / factors_results 两种命名）
# ----------------------------------------------------------------------
def load_factor_result_max_drawdown(market: str = "ashare") -> pd.Series:
    """
    使用 core.storage.load_dataframe 加载 max_drawdown 因子结果。

    优先按仓库默认规则尝试：
        factor_results/{market}_max_drawdown.parquet
    同时兼容你题目中提到的：
        factors_results/max_drawdown.parquet

    返回
    ----
    pd.Series
        索引为 date，值为因子结果。
    """
    # 可能的路径组合：(path, table_name)
    candidates = [
        ("factor_results", f"{market}_max_drawdown"),
        ("factors_results", "max_drawdown"),
    ]

    last_error = None
    for path, table_name in candidates:
        try:
            df = load_dataframe(table_name, path=path)
            if df is None or df.empty:
                continue

            # 如果是 DataFrame，因子保存时是单列 DataFrame
            if isinstance(df, pd.DataFrame):
                if df.shape[1] == 1:
                    series = df.iloc[:, 0]
                else:
                    # 多列时优先尝试列名为因子名的列
                    if "max_drawdown" in df.columns:
                        series = df["max_drawdown"]
                    else:
                        # 退化：取第一列
                        series = df.iloc[:, 0]
            else:
                series = df

            # 索引转成 datetime（通常是 date 索引）
            series.index = pd.to_datetime(series.index, errors="coerce")
            series = series.sort_index()
            print(f"因子结果加载成功: path='{path}', table_name='{table_name}'")
            return series

        except Exception as e:
            last_error = e
            continue

    msg = (
        "无法加载 max_drawdown 因子结果，请检查：\n"
        "  1) 是否已经通过 main.py 正确生成因子文件；\n"
        "  2) 具体文件路径是否为以下之一：\n"
        "     - factor_results/ashare_max_drawdown.parquet\n"
        "     - factors_results/max_drawdown.parquet\n"
        f"  最后一次错误信息: {last_error}"
    )
    raise FileNotFoundError(msg)


# ----------------------------------------------------------------------
# 3. 主流程：加载数据 → 手算 → 加载因子文件 → 对比
# ----------------------------------------------------------------------
def main():
    # 确保项目根目录在 sys.path 中（一般从根目录运行就没问题，这里做兜底）
    root_dir = os.path.dirname(os.path.abspath(__file__))
    if root_dir not in sys.path:
        sys.path.append(root_dir)

    # 1) 加载 ashare 合并后的行情数据
    print("[1/4] 从 data/ashare.parquet 加载市场数据 ...")
    ashare_df = load_dataframe("ashare", path=DATA_PATH)
    if ashare_df is None or ashare_df.empty:
        print("  加载失败：data/ashare.parquet 为空或不存在，请先完成 spider + merge 流程。")
        sys.exit(1)

    print(f"  数据形状: {ashare_df.shape}")
    print(f"  部分列: {ashare_df.columns[:10].tolist()}")

    # 2) 手动计算 max_drawdown
    print("\n[2/4] 按公式手动计算 max_drawdown ...")
    manual_series = compute_max_drawdown(ashare_df)
    print(f"  手算结果长度: {len(manual_series)}")
    print("  手算结果前 5 行：")
    print(manual_series.tail(), "\n")
    
    # 3) 加载因子结果文件
    print("[3/4] 通过 core.storage.load_dataframe 加载因子结果 ...")
    factor_series = load_factor_result_max_drawdown(market="ashare")
    print(f"  因子结果长度: {len(factor_series)}")
    print("  因子结果前 5 行：")
    print(factor_series.tail(), "\n")

    # 4) 对齐索引并比较数值
    print("[4/4] 对齐日期并比较两者差异 ...")
    # 取两者公共日期
    common_dates = sorted(set(manual_series.index) & set(factor_series.index))
    if not common_dates:
        print("  公共日期为空，请检查两份数据的时间范围是否一致。")
        sys.exit(1)

    manual_aligned = manual_series.loc[common_dates]
    factor_aligned = factor_series.loc[common_dates]

    diff = manual_aligned - factor_aligned
    tol = 1e-6
    mismatches = diff[diff.abs() > tol]

    if mismatches.empty:
        print(f"✅ 校验通过：在 {len(common_dates)} 个公共日期上，两者完全一致（容差 {tol}）")
    else:
        print(f"❌ 校验未通过：在 {len(common_dates)} 个公共日期中，有 {len(mismatches)} 个日期差异超过容差 {tol}")
        print("\n  前 10 个有差异的日期（manual, factor, diff）：")
        report_df = pd.DataFrame({
            "manual": manual_aligned.loc[mismatches.index],
            "factor": factor_aligned.loc[mismatches.index],
            "diff": diff.loc[mismatches.index],
        }).head(10)
        print(report_df)
        print(f"\n  最大绝对误差: {diff.abs().max():.6e}")
        print(f"  平均绝对误差: {diff.abs().mean():.6e}")


if __name__ == "__main__":
    main()
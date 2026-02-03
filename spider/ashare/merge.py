#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from pathlib import Path

import pandas as pd

from core.config import DATA_PATH
from core.storage import load_dataframe, save_dataframe
import numpy as np
from tqdm import tqdm

# 1. 自动根据自身路径获取市场名（文件夹最后一级）
MARKET = Path(__file__).parent.name

# 2. 基表只通过名称确认（各市场各自的基表名）
BASE_TABLE_NAME = f"{MARKET}_stock_zh_a_daily"

# 3. 特殊表名 -> 处理函数名 的映射表（禁止硬编码 if-else，用统一映射）
SPECIAL_TABLE_HANDLERS = {
    f"{MARKET}_stock_industry_clf_hist": "merge_industry",
    # 新增特殊表时，在此添加 "表名": "处理函数名"
}

# 进度记录（简单打印进度用）
_progress_total = 0
_progress_current = 0


def _print_progress(message: str):
    """打印当前合并进度信息。"""
    global _progress_current, _progress_total
    _progress_current += 1
    print(f"进度 {_progress_current}/{_progress_total} - {message}")


def merge_default(base_df: pd.DataFrame, merge_df: pd.DataFrame) -> pd.DataFrame:
    """
    默认合并方式：按 ['code', 'date'] 左连接。
    仅合并 base_df 中不存在的列（避免重复覆盖）。
    """
    join_keys = ["code", "date"]

    # 需要 merge_df 至少包含 join_keys
    if not all(k in merge_df.columns for k in join_keys):
        return base_df

    # 只引入新列 + join_keys
    extra_cols = [
        c for c in merge_df.columns
        if c not in base_df.columns or c in join_keys
    ]
    if not extra_cols:
        return base_df

    merged = base_df.merge(
        merge_df[extra_cols],
        on=join_keys,
        how="left",
    )
    return merged


def merge_industry(base_df: pd.DataFrame,
                   industry_df: pd.DataFrame,
                   date_col: str = "date") -> pd.DataFrame:
    """
    行业特殊合并：
    - 使用 start_date 为每个 code 构造行业生效区间；
    - 将 (code, date) 落在区间内的行填充 industry_code。
    需保证 industry_df 至少包含: code, start_date, industry_code。
    """
    required_cols = {"code", "start_date", "industry_code"}
    if not required_cols.issubset(industry_df.columns):
        return base_df

    # 行业表只转换一次 start_date
    industry_df = industry_df[list(required_cols)].copy()
    industry_df["start_date"] = pd.to_datetime(industry_df["start_date"], errors="coerce")

    # 只保留出现在基表中的 code
    valid_codes = set(base_df["code"].unique())
    industry_df = industry_df[industry_df["code"].isin(valid_codes)]

    max_base_date = base_df[date_col].max()
    if "industry_code" not in base_df.columns:
        base_df["industry_code"] = pd.NA

    for code, group in tqdm(industry_df.groupby("code")):
        mask_code = (base_df["code"] == code)
        if not mask_code.any():
            continue

        # 当前 code 下所有生效起始日和行业代码
        starts = group["start_date"].values
        inds = group["industry_code"].values
        if len(starts) == 0:
            continue

        # 构造区间结束日：下一段开始日前一天，最后一段到基表最大日期
        ends = np.empty(len(starts), dtype="datetime64[ns]")            
        if len(starts) == 1:
            ends[0] = max_base_date
        else:
            ends[:-1] = starts[1:] - pd.Timedelta(days=1)
            ends[-1] = max_base_date
        valid = starts <= ends
        if not valid.all():
            starts = starts[valid]
            ends = ends[valid]
            inds = inds[valid]

        # 如果全部被过滤掉，就跳过这个 code
        if len(starts) == 0:
            continue

        intervals = pd.IntervalIndex.from_arrays(starts, ends, closed="both")

        # 只对当前 code 的日期做查找
        code_dates = base_df.loc[mask_code, date_col]
        positions = intervals.get_indexer(code_dates)

        hit = positions >= 0
        if not hit.any():
            continue

        # 取出这些命中的行索引，一次性赋值
        idx = base_df.index[mask_code][hit]
        base_df.loc[idx, "industry_code"] = inds[positions[hit]]
    return base_df


def merge_special(base_df: pd.DataFrame,
                  table_name: str,
                  merge_df: pd.DataFrame) -> pd.DataFrame:
    """
    特殊合并入口：
    - 根据表名在 SPECIAL_TABLE_HANDLERS 中查找对应的处理函数名；
    - 通过映射表调用对应的 merge_xxx 函数。
    """
    handler_name = SPECIAL_TABLE_HANDLERS.get(table_name)
    merge_func = globals().get(handler_name)
    return merge_func(base_df, merge_df)


def merge() -> None:
    """
    合并指定市场的全部 parquet 表。

    约定：
    - 基表名称由 BASE_TABLE_NAME 确定，例如 ashare_stock_zh_a_daily；
    - 所有表都存放在 DATA_PATH 下，通过文件名前缀 MARKET 区分；
    - 特殊表名通过 SPECIAL_TABLE_NAMES / SPECIAL_TABLE_HANDLERS 判定与分派；
    - 合并完成后结果表命名为市场名本身，例如 ashare.parquet。
    """
    # 1. 找出该市场全部 parquet 文件
    market_files = [
        f for f in os.listdir(DATA_PATH)
        if f.startswith(MARKET) and f.endswith(".parquet")
    ]
    if not market_files:
        print(f"市场 {MARKET} 无可用 parquet 文件")
        return

    # 2. 确认基表（只通过名称 BASE_TABLE_NAME）
    base_file_candidates = [
        f for f in market_files if os.path.splitext(f)[0] == BASE_TABLE_NAME
    ]
    if not base_file_candidates:
        print(f"基表 {BASE_TABLE_NAME} 不存在，跳过市场 {MARKET}")
        return

    base_file = base_file_candidates[0]
    base_table = os.path.splitext(base_file)[0]
    base_df = load_dataframe(base_table)
    base_df["date"] = pd.to_datetime(base_df["date"], errors="coerce")

    # 3. 依次合并其他表，补充进度输出
    global _progress_total, _progress_current
    others = [f for f in market_files if f != base_file]
    _progress_total = len(others)
    _progress_current = 0
    for file in others:
        table_name = os.path.splitext(file)[0]
        df = load_dataframe(table_name)
        if df is None or df.empty:
            _print_progress(f"{file} - 数据为空，跳过")
            continue

        # 判断是否为特殊表
        if table_name in SPECIAL_TABLE_HANDLERS.keys():
            base_df = merge_special(base_df, table_name, df)
            _print_progress(f"{file} - 特殊合并")
        else:
            base_df = merge_default(base_df, df)
            _print_progress(f"{file} - 默认合并")
    # 4. 保存最终结果：表名就是市场名
    save_dataframe(base_df, MARKET)
    print(f"市场 {MARKET} 合并完成，结果保存为 {MARKET}.parquet")


if __name__ == "__main__":
    merge()
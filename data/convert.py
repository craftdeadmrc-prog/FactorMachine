#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
将旧格式的 20250518.parquet 转换为与 ashare_stock_zh_a_daily_spider.py
输出结构尽量一致的日线数据，方便本地测试使用。

使用方式示例：
    python convert.py 20250518.parquet
    python convert.py 20250518.parquet output.parquet
"""

import argparse
from pathlib import Path

import pandas as pd


def convert_parquet_to_ashare_daily(input_file: str, output_file: str | None = None) -> None:
    """
    将旧格式日线 parquet 文件转换为标准 A 股日线格式。

    预期输入示例字段（中文）：
        Unnamed: 0, 日期, 股票代码, 开盘, 收盘, 最高, 最低,
        成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率, stock_id, __index_level_0__

    输出字段（英文，尽量贴合 ashare_stock_zh_a_daily_spider）：
        date, code, market,
        open, close, high, low,
        volume, amount,
        amplitude_ratio, change_ratio, change, turnover_ratio
    """
    # 1. 读取原始 parquet
    df = pd.read_parquet(input_file)
    df = df.drop(columns="Unnamed: 0")
    df = df.drop(columns="stock_id")
    df['成交量'] = df['成交量'] * 100
    df['换手率'] = df['换手率'] / 10000
    # 2. 重命名中文列到英文列
    rename_map = {
        "日期": "date",
        "股票代码": "code",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude_ratio",
        "涨跌幅": "change_ratio",
        "涨跌额": "change",
        "换手率": "turnover_ratio",
    }
    for cn, en in rename_map.items():
        if cn in df.columns:
            df = df.rename(columns={cn: en})

    # 3. 处理日期格式 -> YYYYMMDD
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # 4. 处理股票代码为 6 位字符串 & 添加 market
    if "code" in df.columns:
        df["code"] = df["code"].astype(str).str.strip().str.zfill(6)

        def _infer_market(x: str) -> str:
            if not isinstance(x, str) or len(x) == 0:
                return ""
            # 简单规则：6 打头为沪市，其余视为深市
            return "sh" if x.startswith("6") else "sz"

        df["market"] = df["code"].apply(_infer_market)

    # 5. 数值列类型统一为 float（volume 可以保留为整数，也没关系）
    numeric_cols = [
        "open",
        "close",
        "high",
        "low",
        "volume",
        "amount",
        "amplitude_ratio",
        "change_ratio",
        "change",
        "turnover_ratio",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 7. 输出 parquet
    if output_file is None:
        # 默认输出名：{原文件名}_ashare.parquet
        stem = Path(input_file).stem
        output_file = f"{stem}_ashare.parquet"
    df.fillna(value=pd.NA, inplace=True)
    df.to_parquet(output_file, index=False)
    print(f"转换完成: {input_file} -> {output_file}")
    print("预览前几行：")
    print(df.head())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="将旧格式 A 股日线 parquet 转为 ashare_stock_zh_a_daily_spider 风格数据"
    )
    parser.add_argument("input_file", help="输入 parquet 文件路径，例如 20250518.parquet")
    parser.add_argument(
        "output_file",
        nargs="?",
        default=None,
        help="输出 parquet 文件路径（可选，不填则自动生成 *_ashare.parquet）",
    )
    args = parser.parse_args()

    convert_parquet_to_ashare_daily(args.input_file, args.output_file)


if __name__ == "__main__":
    main()
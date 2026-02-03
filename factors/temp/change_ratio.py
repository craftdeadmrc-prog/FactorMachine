"""
涨幅因子计算
"""
import pandas as pd

dependencies = ["code", "open", "close"]

provided_columns = ["change_ratio"]

description = {
    "name": {
        "中文名": "当日涨幅",
        "英文名": "Daily Change Ratio",
        "变量名": "change_ratio"
    },
    "info": {
        "介绍": "当日涨幅，反映股票当日开盘到收盘的价格变化幅度",
        "日期": "",
        "计算公式": "change_ratio = (close - open) / open * 100"
    }
}

def compute_factor(df):
    df["change_ratio"] = (df["close"] - df["open"]) / df["open"] * 100
    return df
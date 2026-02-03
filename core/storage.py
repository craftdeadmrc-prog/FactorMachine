# core/storage.py
import os
import json
import pandas as pd
from datetime import date
from utils.compat.normalize_date import normalize_date_str

from .config import DATA_PATH


os.makedirs(DATA_PATH, exist_ok=True)


def _get_config_path(table_name: str) -> str:
    return os.path.join(DATA_PATH, f"{table_name}_config.json")


def load_table_config(table_name: str) -> dict:
    path = _get_config_path(table_name)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_table_config(table_name: str, config: dict):
    path = _get_config_path(table_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False)


def get_last_update_date(table_name: str):
    """
    返回 YYYYMMDD 或 None
    """
    config = load_table_config(table_name)
    return config.get("last_update")

def load_dataframe(table_name: str) -> pd.DataFrame:
    file_path = os.path.join(DATA_PATH, f"{table_name}.parquet")
    if not os.path.exists(file_path):
        return pd.DataFrame()
    return pd.read_parquet(file_path)


def save_dataframe(df: pd.DataFrame, table_name: str):
    """
    通用保存：
    - 接收任意 DataFrame + 表名
    - 自动按数值范围选择较小整型/浮点型
    - 写 parquet
    - 写 [table_name]_config.json 中的 types & last_update
    """
    if df is None or df.empty:
        return

    config = load_table_config(table_name)
    table_conf = config.get(table_name, {})
    col_types = {}

    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            col_min = df[col].min()
            col_max = df[col].max()
            if pd.api.types.is_integer_dtype(df[col].dtype):
                if -32768 <= col_min <= col_max <= 32767:
                    df[col] = df[col].astype("int16")
                    col_types[col] = "int16"
                elif -2147483648 <= col_min <= col_max <= 2147483647:
                    df[col] = df[col].astype("int32")
                    col_types[col] = "int32"
                else:
                    df[col] = df[col].astype("int64")
                    col_types[col] = "int64"
            else:
                df[col] = df[col].astype("float32")
                col_types[col] = "float32"

    table_conf["types"] = col_types
    config[table_name] = table_conf

    config["last_update"] = normalize_date_str(date.today().isoformat())

    save_table_config(table_name, config)

    file_path = os.path.join(DATA_PATH, f"{table_name}.parquet")
    df.to_parquet(file_path, index=False)
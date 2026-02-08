import os
import json
import pandas as pd
import numpy as np
from datetime import date
from core.config import DATA_PATH
from utils.compat.normalize_date import normalize_date_str
# 手动定义 float16 范围常量，避免 np.finfo 引起的 overflow warning
FLOAT16_MAX = 65504.0
FLOAT16_MIN = -65504.0


def _get_config_path(table_name: str, path=DATA_PATH) -> str:
    """
    获取配置文件的路径
    """
    return os.path.join(path, f"{table_name}_config.json")


def load_table_config(table_name: str, path=DATA_PATH) -> dict:
    """
    加载表格配置
    """
    cfg_path = _get_config_path(table_name, path)
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_table_config(table_name: str, config: dict, path=DATA_PATH):
    """
    保存表格配置
    """
    os.makedirs(path, exist_ok=True)
    cfg_path = _get_config_path(table_name, path)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False)


def get_last_update_date(table_name: str, path=DATA_PATH) -> str | None:
    """
    返回最后更新日期（字符串），或 None
    """
    config = load_table_config(table_name, path)
    return config.get("last_update")


def load_dataframe(table_name: str, path=DATA_PATH) -> pd.DataFrame:
    """
    加载 DataFrame，并根据保存时记录的 types 恢复列精度
    """
    file_path = os.path.join(path, f"{table_name}.parquet")
    if not os.path.exists(file_path):
        return pd.DataFrame()

    df = pd.read_parquet(file_path)

    # 从配置中取出列类型信息，恢复精度
    config = load_table_config(table_name, path)
    table_conf = config.get(table_name, {})
    col_types = table_conf.get("types", {})

    for col, dtype in col_types.items():
        if col in df.columns:
            df[col] = df[col].astype(dtype)

    return df


def _effective_decimal_digits(value: float) -> int:
    """
    计算单个浮点数的十进制“整体有效数字位数”（不是小数点后位数）：
    - 使用科学计数法；
    - 去掉小数点、前导 0 和尾随 0；
    - 剩余数字长度即为有效数字位数。
    """
    if value == 0 or not np.isfinite(value):
        return 0
    s = f"{value:.12e}"            # 例如 1.234500000000e+02
    mantissa, _ = s.lower().split("e")
    digits = mantissa.replace(".", "")
    digits = digits.lstrip("0").rstrip("0")
    return len(digits)


def _max_effective_decimal_digits(col: pd.Series) -> int:
    """
    计算一列中所有非空、有限值的最大“整体有效数字位数”
    """
    non_null = col.dropna()
    if non_null.empty:
        return 0
    vals = [v for v in non_null.values if np.isfinite(v) and v != 0]
    if not vals:
        return 0
    return max(_effective_decimal_digits(v) for v in vals)


def _median_effective_decimal_digits(col: pd.Series) -> int:
    """
    计算一列中所有非空、有限值的“典型整体有效数字位数”（中位数）
    用于判断主流精度，避免少数异常值拉高平均。
    """
    non_null = col.dropna()
    if non_null.empty:
        return 0
    digits_list = [
        _effective_decimal_digits(v)
        for v in non_null.values
        if np.isfinite(v) and v != 0
    ]
    if not digits_list:
        return 0
    return int(np.median(digits_list))


def _round_to_significant_digits(value: float, digits: int) -> float:
    """
    将值四舍五入到指定的整体有效数字位数
    """
    if value == 0 or not np.isfinite(value):
        return value
    # 使用通用格式 'g'，保留 digits 位有效数字
    return float(f"{value:.{digits}g}")


def _process_float_outliers(col_series: pd.Series) -> pd.Series:
    """
    处理浮点列中的异常值（整体有效数字位数突然增多的情况）：
    - 先取这一列的“典型有效位数” typical_digits（中位数）；
    - 若最大有效位数比 typical_digits 高出 2 位以上，认为存在异常值；
    - 对这些异常值按 typical_digits 位有效数字进行四舍五入。
    """
    typical_digits = _median_effective_decimal_digits(col_series)
    if typical_digits == 0:
        return col_series

    outlier_threshold = typical_digits + 2
    max_digits_before = _max_effective_decimal_digits(col_series)
    if max_digits_before <= outlier_threshold:
        # 没有明显异常，直接返回
        return col_series

    result = col_series.copy()
    for i, val in enumerate(col_series):
        if np.isfinite(val):
            cur_digits = _effective_decimal_digits(val)
            if cur_digits > outlier_threshold:
                result.iloc[i] = _round_to_significant_digits(val, typical_digits)
    return result


def save_dataframe(df: pd.DataFrame, table_name: str, path=DATA_PATH):
    """
    通用保存：
    - 接收任意 DataFrame + 表名；
    - 自动按数值范围选择较小整型/浮点型；
    - 整数列：
        - 非负：优先压缩为 uint8/16/32/64；
        - 含负：压缩为 int16/32/64；
    - 浮点列：
        - 若“数值上全是整数”（全 .0 且无 NaN）：转为整数列再按上面规则压缩；
        - 其余浮点列：
            - 若整列在 float16 范围 [-65504, 65504] 内：
                - 先按典型整体有效数字位数修剪异常长尾；
                - 再看修剪后的最大整体有效数字位数：
                    - ≤ 4 → 用 float16；
                    - > 4 → 用 float32；
            - 超出 float16 范围 → 用 float32；
    - 写 parquet；
    - 写 [table_name]_config.json 中的 types & last_update。
    """
    if df is None or df.empty:
        return
    os.makedirs(path, exist_ok=True)
    config = load_table_config(table_name, path)
    table_conf = config.get(table_name, {})
    col_types: dict[str, str] = {}

    # 复制一份，避免对上游 DataFrame 的切片直接赋值导致 SettingWithCopyWarning
    df = df.copy()

    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue

        # 1. 若为浮点列，先判断是否是“数值上整数的浮点列”（全为 .0），无 NaN 才转换
        if pd.api.types.is_float_dtype(df[col].dtype):
            non_null = df[col].dropna()
            if len(non_null) > 0 and (non_null % 1 == 0.0).all():
                # 列中无 NaN 时，安全地转为 int64
                if not df[col].isnull().any():
                    df[col] = df[col].astype("int64")

        # 2. 整数列（包含原本就是整数的列，以及上一步转换得到的整数列）
        if pd.api.types.is_integer_dtype(df[col].dtype):
            col_min = df[col].min()
            col_max = df[col].max()

            # 非负整数：优先用无符号类型压缩
            if col_min >= 0:
                if col_max <= np.iinfo(np.uint8).max:
                    df[col] = df[col].astype("uint8")
                    col_types[col] = "uint8"
                elif col_max <= np.iinfo(np.uint16).max:
                    df[col] = df[col].astype("uint16")
                    col_types[col] = "uint16"
                elif col_max <= np.iinfo(np.uint32).max:
                    df[col] = df[col].astype("uint32")
                    col_types[col] = "uint32"
                else:
                    df[col] = df[col].astype("uint64")
                    col_types[col] = "uint64"
            else:
                # 有符号整数：沿用原范围压缩逻辑
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
            # 3. 浮点列（不能安全转为整数或本来就有小数部分）
            non_null = df[col].dropna()
            if non_null.empty:
                # 全 NaN 列：保持原 dtype，记录一下
                col_types[col] = str(df[col].dtype)
                continue

            col_min = non_null.min()
            col_max = non_null.max()
            print(col)
            print(col_min)
            print(col_max)
            # 使用手动定义的 float16 范围，避免 np.finfo 带来的 cast 溢出 warning
            # 链式比较，确保整个列都在 float16 范围内
            in_f16_range = FLOAT16_MIN <= col_min <= col_max <= FLOAT16_MAX

            if in_f16_range:
                # 先处理异常值：将整体有效数字位数突然增长的异常值，四舍五入回主流位数
                df[col] = _process_float_outliers(df[col])

                # 再基于处理后的列评估最大整体有效数字位数
                max_digits = _max_effective_decimal_digits(df[col])

                # float16 大致能稳定表示 3–4 位十进制整体有效数字
                if max_digits <= 4:
                    df[col] = df[col].astype("float16")
                    col_types[col] = "float16"
                else:
                    df[col] = df[col].astype("float32")
                    col_types[col] = "float32"
            else:
                df[col] = df[col].astype("float32")
                col_types[col] = "float32"

    table_conf["types"] = col_types
    config[table_name] = table_conf
    config["last_update"] = normalize_date_str(date.today().isoformat())
    save_table_config(table_name, config, path)

    file_path = os.path.join(path, f"{table_name}.parquet")
    df.to_parquet(file_path, index=False)